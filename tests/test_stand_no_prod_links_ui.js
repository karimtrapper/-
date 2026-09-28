// QA (Codex) FAIL №4/№6/№7/№8: даже если сервер один раз пришлёт боевые ссылки в
// данных (bot_link/wa_link/referral_link реферала, deep-link на grusha_lk_bot),
// фронт на стенде не должен их рисовать, копировать в буфер или открывать —
// защита должна жить в UI и не зависеть от одного сигнала. Перепроверка 28.09
// потребовала: 1) признак стенда в crm.html не должен зависеть только от того,
// успел ли загрузиться /api/stand/roles — берём ИЛИ этот сигнал, ИЛИ 'stand' из
// /api/auth/me; если auth/me не ответил, окружение считается непроверенным и
// боевые ссылки всё равно не рисуются (fail-closed); 2) в кабинете реферала бот
// открывается только при явном /api/health {stand:false} — если health не
// ответил, вместо открытия бота показывается «повторите» (тоже fail-closed).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function extractIndented(src, name, prefix = 'function') {
  const re = new RegExp(`^([ \\t]*)${prefix} ${name}\\(`, 'm');
  const m = src.match(re);
  assert.ok(m, `нет функции ${name}`);
  const indent = m[1];
  const tail = src.slice(m.index);
  const closeRe = new RegExp(`^${indent}\\}`, 'm');
  const end = tail.search(closeRe);
  assert.ok(end >= 0, `не нашли конец функции ${name}`);
  return tail.slice(0, end + tail.slice(end).indexOf('}') + 1);
}

const crmHtml = fs.readFileSync(path.join(__dirname, '../static/crm/crm.html'), 'utf8');
const refHtml = fs.readFileSync(path.join(__dirname, '../static/referrer/index.html'), 'utf8');

// ---------- FAIL №4/№7: static/crm/crm.html — renderReferrers() ----------
{
  const source = extractIndented(crmHtml, 'standLinkState') + '\n' + extractIndented(crmHtml, 'renderReferrers');
  const referrer = {
    id: 1, name: 'QA', code: 'QA', active: true, token: 'x',
    bot_link: 'https://t.me/Grushath_bot?start=ref__QA',
    wa_link: 'https://wa.me/66810000000',
    referral_link: 'https://grusha.space/?ref=QA',
  };

  function render(vars) {
    const list = {innerHTML: ''};
    const ctx = Object.assign({
      _referrersCache: [referrer],
      document: {getElementById: id => (id === 'referrersList' ? list : null)},
      window: {location: {origin: 'http://127.0.0.1:1'}},
      showToast: () => {},
    }, vars);
    vm.createContext(ctx);
    vm.runInContext(source, ctx);
    ctx.renderReferrers();
    return list.innerHTML;
  }
  const hasReal = html => html.includes('https://t.me/Grushath_bot')
    && html.includes('https://wa.me/66810000000') && html.includes('https://grusha.space');
  const hasNone = html => !html.includes('https://t.me/Grushath_bot')
    && !html.includes('https://wa.me/66810000000') && !html.includes('https://grusha.space');

  // Прод, оба сигнала это подтверждают: ссылки видны как обычно.
  assert.ok(hasReal(render({STAND_ROLES: null, AUTH_STAND: false})), 'прод: оба сигнала false/null → ссылки видны');

  // Стенд по STAND_ROLES (auth/me ещё не успел ответить) — раньше это был дефект (FAIL №4).
  assert.ok(hasNone(render({STAND_ROLES: {admin: 'Админ'}, AUTH_STAND: null})),
    'STAND_ROLES подтвердил стенд — ссылки скрыты, даже если auth/me ещё не ответил');

  // Стенд по AUTH_STAND (/api/stand/roles упал с ошибкой, STAND_ROLES остался null) —
  // именно этот сценарий раньше показывал боевые ссылки как на проде.
  assert.ok(hasNone(render({STAND_ROLES: null, AUTH_STAND: true})),
    'FAIL №4: сбой /api/stand/roles не должен выдавать стенд за прод, если /api/auth/me говорит stand:true');

  // /api/auth/me не ответил вообще (AUTH_STAND остаётся null) и роли тоже не подтвердили
  // стенд — окружение не проверено, fail-closed: ссылки всё равно скрыты.
  const unverified = render({STAND_ROLES: null, AUTH_STAND: null});
  assert.ok(hasNone(unverified), 'окружение не проверено — боевые ссылки не рисуем (fail-closed)');
  assert.ok(unverified.includes('не удалось проверить окружение'), 'должна быть честная причина, а не молчание');

  // standLinkState() не должна падать, если STAND_ROLES/AUTH_STAND вообще не
  // объявлены (например, при выдёргивании функции в изолированный тест) —
  // typeof-проверка обязана это покрывать без ReferenceError; поведение — тоже
  // fail-closed (реальная страница всегда объявляет оба как let ... = null,
  // так что renderReferrers() целиком проверяем с этим более реалистичным ctx).
  {
    const stateSrc = extractIndented(crmHtml, 'standLinkState');
    const stateCtx = {};
    vm.createContext(stateCtx);
    vm.runInContext(stateSrc, stateCtx);
    let state;
    assert.doesNotThrow(() => { state = stateCtx.standLinkState(); });
    assert.equal(state.isStand, false);
    assert.equal(state.unverified, true);
  }

  console.log('crm renderReferrers: FAIL №4/№7 закрыты — 5 сценариев PASS');
}

// ---------- FAIL №6/№8: static/referrer/index.html — startBotLogin() ----------
(async () => {
  const source = extractIndented(refHtml, 'startBotLogin', 'async function');

  async function run(healthBehavior) {
    const opened = [];
    const st = {textContent: '', innerHTML: ''};
    const ctx = {
      document: {getElementById: () => st},
      fetch: async (url) => {
        if (String(url).includes('/api/health')) {
          if (healthBehavior === 'error') throw new Error('health failed');
          return {json: async () => ({stand: healthBehavior === 'stand'})};
        }
        return {json: async () => ({success: true, nonce: 'n', link: 'https://t.me/grusha_lk_bot?start=login_n'})};
      },
      window: {open: u => opened.push(u)},
      setInterval: () => 1, clearInterval: () => {},
      Date, encodeURIComponent,
      token: 'x', t: x => x, botPollTimer: null,
    };
    vm.createContext(ctx);
    vm.runInContext(source, ctx);
    await ctx.startBotLogin();
    return {opened, text: st.textContent};
  }

  // На стенде /api/health явно отдаёт stand:true — бот не открывается.
  {
    const {opened, text} = await run('stand');
    assert.equal(opened.length, 0, 'на стенде окно с ботом открываться не должно');
    assert.ok(text && text.length > 0, 'должна быть понятная пометка вместо тишины');
  }
  // На проде /api/health явно отдаёт stand:false — поведение не меняется.
  {
    const {opened} = await run('prod');
    assert.equal(opened.length, 1);
    assert.ok(opened[0].includes('grusha_lk_bot'));
  }
  // FAIL №6: /api/health недоступен — раньше это трактовалось как «прод» и бот
  // открывался; теперь это fail-closed — бот НЕ открывается, показывается «повторите».
  {
    const {opened, text} = await run('error');
    assert.equal(opened.length, 0, 'health недоступен — бот не должен открываться (fail-closed)');
    assert.ok(text && text.length > 0, 'должна быть пометка «не удалось проверить», а не тишина');
  }

  console.log('referrer startBotLogin: FAIL №6/№8 закрыты — 3 сценария PASS');
})().catch(e => { console.error(e.stack); process.exitCode = 1; });

// ---------- п.5: собственный кабинет реферала (сайт/бот/WA в статистике) ----------
// Та же fail-closed логика: IS_STAND инициализируется null, а не false, и
// checkStand() при ошибке health оставляет его null — реальные ссылки не рисуются.
{
  assert.ok(/let IS_STAND = null/.test(refHtml), 'IS_STAND должен начинаться с null (непроверено), а не false (прод по умолчанию)');
  for (const field of ['d.referral_link', 'd.bot_link', 'd.wa_link']) {
    assert.ok(refHtml.includes(`refLinkText(${field})`), `${field} должен идти через refLinkText()`);
  }
  const refLinkTextSrc = extractIndented(refHtml, 'refLinkText');
  assert.ok(/IS_STAND === false/.test(refLinkTextSrc), 'реальная ссылка показывается только при явном IS_STAND===false');
  assert.ok(refHtml.includes('async function checkStand()'), 'должна быть функция проверки стенда через /api/health');
  assert.ok(refHtml.includes("catch (e) { IS_STAND = null; }"), 'сбой /api/health должен оставлять IS_STAND непроверенным, а не считать прод');
  assert.ok(refHtml.includes('checkStand().then(loadStats)'), 'проверка стенда должна выполняться до первого рендера кабинета');
  console.log('referrer cabinet (сайт/бот/WA): п.5 закрыт (fail-closed) — источники проверены статически');
}

// ---------- лидер: рендер до резолва loadAuthStand() не должен застревать в
// «не удалось проверить окружение» на проде — после ответа список обязан
// перерисоваться сам, без перезагрузки страницы ----------
(async () => {
  const renderSrc = extractIndented(crmHtml, 'standLinkState') + '\n' + extractIndented(crmHtml, 'renderReferrers');
  const authSrc = extractIndented(crmHtml, 'loadAuthStand', 'async function');
  const refreshSrc = extractIndented(crmHtml, 'refreshStandDependentLinks');
  const referrer = {
    id: 1, name: 'QA', code: 'QA', active: true, token: 'x',
    bot_link: 'https://t.me/Grushath_bot?start=ref__QA',
    wa_link: 'https://wa.me/66810000000',
    referral_link: 'https://grusha.space/?ref=QA',
  };

  async function scenario(authResponse) {
    const list = {innerHTML: ''};
    const ctx = {
      _referrersCache: [referrer],
      STAND_ROLES: null, AUTH_STAND: null,
      API_URL: '',
      document: {getElementById: id => (id === 'referrersList' ? list : null)},
      window: {location: {origin: 'http://127.0.0.1:1'}},
      showToast: () => {},
      fetch: async () => ({json: async () => authResponse}),
    };
    vm.createContext(ctx);
    vm.runInContext(renderSrc + '\n' + refreshSrc + '\n' + authSrc, ctx);

    // Вкладка отрисовалась ДО ответа /api/auth/me — сигналы ещё не разрешены.
    ctx.renderReferrers();
    const before = list.innerHTML;

    await ctx.loadAuthStand();
    const after = list.innerHTML;
    return {before, after};
  }

  const hasReal = html => html.includes('https://t.me/Grushath_bot')
    && html.includes('https://wa.me/66810000000') && html.includes('https://grusha.space');
  const hasNone = html => !html.includes('https://t.me/Grushath_bot')
    && !html.includes('https://wa.me/66810000000') && !html.includes('https://grusha.space');

  // Прод: рендер до ответа — честно «не проверено»; после ответа (stand:false) —
  // список сам перерисовался, ссылки рабочие, без перезагрузки страницы.
  {
    const {before, after} = await scenario({success: true, user: {stand: false}});
    assert.ok(!hasReal(before), 'до ответа auth/me ссылки не должны быть видны (fail-closed)');
    assert.ok(hasReal(after), 'после подтверждённого прод-ответа список обязан перерисоваться с рабочими ссылками');
  }
  // Стенд: рендер до ответа — «не проверено»; после ответа (stand:true) — по-прежнему
  // нейтрально («на стенде выключено»), просто без лишнего «не удалось проверить».
  {
    const {before, after} = await scenario({success: true, user: {stand: true}});
    assert.ok(hasNone(before) && hasNone(after), 'на стенде боевые ссылки не появляются ни до, ни после ответа');
    assert.ok(after.includes('на стенде выключено'), 'после подтверждения стенда — обычная стендовая пометка, а не «не удалось проверить»');
  }

  console.log('crm renderReferrers: авто-перерисовка после loadAuthStand() — 2 сценария PASS');
})().catch(e => { console.error(e.stack); process.exitCode = 1; });
