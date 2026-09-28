// QA перепроверка T7 (5-й раунд, после влития stage): три оставшихся пути.
// FAIL №4: приглашение админа (copyAdminInvite) копировало зашитый боевой
// grusha.up.railway.app/login даже когда админ сидит на стенде — теперь всегда
// location.origin (тот же результат на проде, правильный на стенде).
// FAIL №5: если проверка режима ответила успешно, но поля 'stand' в ответе нет —
// это тоже «неизвестно», а не «прод»: !!undefined===false раньше молча выдавало
// такой ответ за подтверждённый прод. Только явное stand===false — прод.
// FAIL №6: внешняя платёжная ссылка сделки (doc_payment_url) на стенде — не
// кликабельна, честная пометка вместо <a href>; документы Google Drive
// (doc_invoice_url/doc_contract_url) не трогаем — их не рендерит как ссылку.
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

// ---------- FAIL №4: copyAdminInvite() — location.origin вместо боевого домена ----------
{
  const source = extractIndented(crmHtml, 'copyAdminInvite');
  function invite(origin) {
    const copied = [];
    const ctx = {
      location: {origin},
      navigator: {clipboard: {writeText: async t => { copied.push(t); return Promise.resolve(); }}},
      showToast: () => {}, prompt: () => {},
    };
    vm.createContext(ctx);
    vm.runInContext(source, ctx);
    ctx.copyAdminInvite('QA', '@qa');
    return copied[0] || '';
  }
  assert.ok(!crmHtml.includes("Открой https://grusha.up.railway.app/login"),
    'боевой домен не должен быть зашит в тексте приглашения');
  assert.ok(invite('https://grusha-stand.up.railway.app').includes('grusha-stand.up.railway.app/login'),
    'на стенде приглашение должно вести на текущий стенд');
  assert.ok(invite('https://grusha.up.railway.app').includes('grusha.up.railway.app/login'),
    'на проде результат не меняется — тот же домен через location.origin');
  console.log('copyAdminInvite: FAIL №4 закрыт — 3 проверки PASS');
}

// ---------- FAIL №5: отсутствие поля 'stand' в ответе — «неизвестно», не «прод» ----------
{
  // crm.html: loadAuthStand()
  const authSrc = extractIndented(crmHtml, 'loadAuthStand', 'async function')
    + '\n' + extractIndented(crmHtml, 'refreshStandDependentLinks');
  (async () => {
    const ctx = {
      API_URL: '', AUTH_STAND: null,
      fetch: async () => ({json: async () => ({success: true, user: {id: 1}})}), // поля stand нет
    };
    vm.createContext(ctx);
    vm.runInContext(authSrc, ctx);
    await ctx.loadAuthStand();
    assert.equal(ctx.AUTH_STAND, null, 'ответ без поля stand — AUTH_STAND должен остаться null (неизвестно)');
    console.log('loadAuthStand: FAIL №5 (crm.html) закрыт — 1 проверка PASS');
  })().catch(e => { console.error(e.stack); process.exitCode = 1; });

  // referrer/index.html: startBotLogin() и checkStand()
  const loginSrc = extractIndented(refHtml, 'startBotLogin', 'async function');
  const checkSrc = extractIndented(refHtml, 'checkStand', 'async function');
  (async () => {
    const opened = [];
    const st = {textContent: '', innerHTML: ''};
    const ctx = {
      document: {getElementById: () => st},
      fetch: async (url) => {
        if (String(url).includes('/api/health')) return {json: async () => ({success: true})}; // поля stand нет
        return {json: async () => ({success: true, nonce: 'n', link: 'https://t.me/grusha_lk_bot?start=login_n'})};
      },
      window: {open: u => opened.push(u)},
      setInterval: () => 1, clearInterval: () => {},
      Date, encodeURIComponent, token: 'q', t: x => x, botPollTimer: null,
    };
    vm.createContext(ctx);
    vm.runInContext(loginSrc, ctx);
    await ctx.startBotLogin();
    assert.equal(opened.length, 0, 'ответ /api/health без поля stand не должен считаться прод-подтверждением — бот не открывается');

    const ctx2 = {IS_STAND: null, fetch: async () => ({json: async () => ({success: true})})};
    vm.createContext(ctx2);
    vm.runInContext(checkSrc, ctx2);
    await ctx2.checkStand();
    assert.equal(ctx2.IS_STAND, null, 'checkStand(): ответ без поля stand оставляет IS_STAND непроверенным');
    console.log('startBotLogin/checkStand: FAIL №5 (referrer) закрыт — 2 проверки PASS');
  })().catch(e => { console.error(e.stack); process.exitCode = 1; });
}

// ---------- FAIL №6: doc_payment_url — не кликабельна на стенде/непроверенном окружении ----------
{
  const line = crmHtml.split('\n').find(x => x.includes('deal.doc_payment_url ?') && x.includes('Подтверждение платежа:'));
  assert.ok(line, 'не нашли рендер doc_payment_url');
  const expr = line.trim().slice(2, -1); // ${ ... } -> ...
  function renderLine(isStand, unverified) {
    const ctx = {
      deal: {doc_payment_url: 'https://payments.example.test/pay/real-order'},
      escapeHtml: x => x,
      standLinkState: () => ({isStand, unverified}),
    };
    vm.createContext(ctx);
    return vm.runInContext('(' + expr + ')', ctx);
  }
  assert.ok(renderLine(false, false).includes('href="https://payments.example.test/pay/real-order"'),
    'на проде платёжная ссылка сделки остаётся кликабельной, как раньше');
  assert.ok(!renderLine(true, false).includes('href='), 'на стенде платёжная ссылка не должна быть кликабельной');
  assert.ok(!renderLine(false, true).includes('href='), 'непроверенное окружение — тоже без ссылки (fail-closed)');
  assert.ok(renderLine(true, false).includes('ссылка выключена'), 'вместо ссылки — честная пометка, а не тишина');

  // Документы Google Drive (лидер: доступ контролирует Google, эти поля не трогаем)
  // не рендерятся этой же строкой — убеждаемся, что фикс не расширился на них по ошибке.
  assert.ok(!crmHtml.includes('deal.doc_invoice_url ?') || !/standLinkState/.test(
    (crmHtml.split('\n').find(x => x.includes('deal.doc_invoice_url ?')) || '')),
    'doc_invoice_url — документ Google Drive, его видимость не должна зависеть от standLinkState()');

  console.log('doc_payment_url: FAIL №6 закрыт — 4 проверки PASS');
}
