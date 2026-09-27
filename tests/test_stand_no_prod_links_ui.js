// QA (Codex) FAIL №7 и №8: даже если сервер один раз пришлёт боевые ссылки в
// данных (bot_link/wa_link реферала, deep-link на grusha_lk_bot), фронт на стенде
// не должен их рисовать, копировать в буфер или открывать — защита должна жить в
// UI и не зависеть от того, что именно вернул конкретный ответ API (Карим, 28.09).
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

// ---------- FAIL №7: static/crm/crm.html — renderReferrers() ----------
{
  const source = extractIndented(crmHtml, 'renderReferrers');
  const referrer = {
    id: 1, name: 'QA', code: 'QA', active: true, token: 'x',
    bot_link: 'https://t.me/Grushath_bot?start=ref__QA',
    wa_link: 'https://wa.me/66810000000',
    referral_link: 'https://grusha.space/?ref=QA',
  };

  function render(standRoles) {
    const list = {innerHTML: ''};
    const ctx = {
      _referrersCache: [referrer],
      document: {getElementById: id => (id === 'referrersList' ? list : null)},
      window: {location: {origin: 'http://127.0.0.1:1'}},
      showToast: () => {},
      STAND_ROLES: standRoles,
    };
    vm.createContext(ctx);
    vm.runInContext(source, ctx);
    ctx.renderReferrers();
    return list.innerHTML;
  }

  // Прод (STAND_ROLES===null, как до /api/stand/roles): ссылки видны как раньше.
  const prodHtml = render(null);
  assert.ok(prodHtml.includes('https://t.me/Grushath_bot'), 'на проде ссылка на бота рисуется как обычно');
  assert.ok(prodHtml.includes('https://wa.me/66810000000'), 'на проде WA-ссылка доступна для копирования как обычно');
  assert.ok(prodHtml.includes('https://grusha.space/?ref=QA'), 'на проде ссылка на сайт видна как обычно');

  // Стенд (STAND_ROLES заполнен /api/stand/roles): ни ссылка на бота, ни WA, ни сайт не рисуются.
  const standHtml = render({admin: 'Админ'});
  assert.ok(!standHtml.includes('https://t.me/Grushath_bot'), 'на стенде боевая ссылка на бота не должна попадать в разметку');
  assert.ok(!standHtml.includes('https://wa.me/66810000000'), 'на стенде боевой WhatsApp не должен попадать в разметку');
  assert.ok(!standHtml.includes('https://grusha.space'), 'на стенде боевая ссылка на сайт (воронка) не должна попадать в разметку');
  assert.ok(standHtml.includes('на стенде выключено') || standHtml.toLowerCase().includes('выключен'),
    'на стенде должна быть честная пометка вместо ссылки');

  // Функция не должна падать, если STAND_ROLES вообще не объявлена в области видимости
  // (например, при выдёргивании функции в изолированный тест) — typeof-проверка обязана
  // это покрывать без ReferenceError.
  {
    const list = {innerHTML: ''};
    const ctx = {
      _referrersCache: [referrer],
      document: {getElementById: id => (id === 'referrersList' ? list : null)},
      window: {location: {origin: 'http://127.0.0.1:1'}},
      showToast: () => {},
    };
    vm.createContext(ctx);
    vm.runInContext(source, ctx);
    assert.doesNotThrow(() => ctx.renderReferrers());
  }

  console.log('crm renderReferrers: FAIL №7 закрыт — 3 сценария PASS');
}

// ---------- FAIL №8: static/referrer/index.html — startBotLogin() ----------
(async () => {
  const source = extractIndented(refHtml, 'startBotLogin', 'async function');

  async function run(healthResponse) {
    const opened = [];
    const st = {textContent: '', innerHTML: ''};
    const ctx = {
      document: {getElementById: () => st},
      fetch: async (url) => {
        if (String(url).includes('/api/health')) {
          return {json: async () => healthResponse};
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

  // На стенде /api/health отдаёт stand:true — бот не открывается вообще, даже
  // если ответ tg-start (замокан выше) содержит боевую ссылку на grusha_lk_bot.
  {
    const {opened, text} = await run({success: true, stand: true});
    assert.equal(opened.length, 0, 'на стенде окно с ботом открываться не должно');
    assert.ok(text && text.length > 0, 'должна быть понятная пометка вместо тишины');
  }
  // На проде (stand:false) поведение не меняется — бот открывается как раньше.
  {
    const {opened} = await run({success: true, stand: false});
    assert.equal(opened.length, 1);
    assert.ok(opened[0].includes('grusha_lk_bot'));
  }
  // /api/health недоступен (сеть мигнула) — по умолчанию считаем, что это НЕ стенд,
  // чтобы реальным партнёрам на проде вход не сломался из-за временной ошибки сети.
  {
    const opened = [];
    const st = {textContent: '', innerHTML: ''};
    const ctx = {
      document: {getElementById: () => st},
      fetch: async (url) => {
        if (String(url).includes('/api/health')) throw new Error('network blip');
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
    assert.equal(opened.length, 1, 'сетевая ошибка health-check не должна сама по себе блокировать прод-вход');
  }

  console.log('referrer startBotLogin: FAIL №8 закрыт — 3 сценария PASS');
})().catch(e => { console.error(e.stack); process.exitCode = 1; });

// ---------- п.5: собственный кабинет реферала (сайт/бот/WA в статистике) ----------
{
  for (const [id, field] of [['url-site', 'd\\.referral_link'], ['url-bot', 'd\\.bot_link'], ['url-wa', 'd\\.wa_link']]) {
    const re = new RegExp(`id="${id}">\\$\\{IS_STAND \\? t\\('stand_link_disabled'\\) : esc\\(${field}\\)\\}`);
    assert.ok(re.test(refHtml), `${id} должен показывать пометку вместо ${field} на стенде`);
  }
  assert.ok(refHtml.includes('async function checkStand()'), 'должна быть функция проверки стенда через /api/health');
  assert.ok(refHtml.includes('checkStand().then(loadStats)'), 'проверка стенда должна выполняться до первого рендера кабинета');
  console.log('referrer cabinet (сайт/бот/WA): п.5 закрыт — источники проверены статически');
}
