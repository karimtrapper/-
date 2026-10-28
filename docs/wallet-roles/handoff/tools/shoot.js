// Скриншоты задачника: локальный стенд (STAND_MODE=1), реальные эндпоинты, cookie по ролям.
const fs = require('node:fs'), path = require('node:path');
const {chromium} = require('playwright');
const ORIGIN = 'http://127.0.0.1:5871';
const OUT = process.argv[2];
const ready = fs.readFileSync('/tmp/wallet-handoff-qa/shots_server.log', 'utf8').split('\n').find(l => l.startsWith('READY '));
const {cookies, users} = JSON.parse(ready.slice(6));
const REALTY = 'TDuDeRiwrLLN3hnnA57G5yM6ibg58A6wZk', EXCHANGE = 'TA6S3RBEY57jq8fXEVVsU6H9JZ18inenG4';
const DEAL = 1472;
const base = JSON.parse(fs.readFileSync('static/stand/walkthrough/leasehold-rub/13.json', 'utf8')).state;
fs.mkdirSync(OUT, {recursive: true});

async function api(role, method, url, body) {
  const r = await fetch(ORIGIN + url, {method, headers: {'content-type': 'application/json', cookie: 'session=' + cookies[role]},
    body: body ? JSON.stringify(body) : undefined});
  return r.json();
}
async function walletIds() {
  const j = await api('admin', 'GET', '/api/wallets?no_balances=true&all=true');
  return Object.fromEntries(j.wallets.map(w => [w.address, w]));
}
async function seed(address, patch = {}) {
  const wallets = await walletIds();
  const w = wallets[address];
  const state = JSON.parse(JSON.stringify(base));
  const mirror = {id: w.id, addr: address, multisig: true, role: 'findir', owner: 'компания', name: w.label,
    purpose: w.purpose, limit_usd: w.limit_usd, initiator_roles: w.initiator_roles, confirmer_roles: w.confirmer_roles,
    owner_can_alone: w.owner_can_alone, signer_addresses: w.signer_addresses};
  state.wallets = state.wallets.concat([mirror]);
  const d = state.deals[0];
  Object.assign(d, {walletId: w.id, demoTransfers: false, assigneeAdminId: null, manager: 'Елизавета',
    transfer: {addr: 'TQgQCBXkewuW4RoieDKFP9Ko2SopBh8jso', amount: 5000, net: 'TRC-20', to: 'Coins.co.th', sends: [], rate: '31,20', thb: 156000}});
  state.convs[0].walletId = w.id;
  state.notes = [];
  Object.assign(d, patch);
  await api('admin', 'POST', '/__shots/board', {state});
  return {w, state};
}
async function open(browser, role, width, height) {
  const ctx = await browser.newContext({viewport: {width, height}});
  await ctx.addCookies([{name: 'session', value: cookies[role], url: ORIGIN}]);
  const page = await ctx.newPage();
  await page.route('**/*', route => new URL(route.request().url()).origin === ORIGIN ? route.continue() : route.abort());
  page.on('pageerror', e => console.log('PAGEERROR', role, e.message));
  await page.goto(ORIGIN + '/tasks', {waitUntil: 'domcontentloaded'});
  await page.waitForFunction(() => typeof S !== 'undefined' && S.deals && S.deals.length && typeof CRM_WALLETS !== 'undefined' && CRM_WALLETS.length, null, {timeout: 20000});
  await page.evaluate(id => { openTask(id, null); }, DEAL);
  await page.waitForTimeout(500);
  return {ctx, page};
}
async function shot(page, name, width) {
  await page.waitForTimeout(300);
  const file = path.join(OUT, `${name}__${width}.png`);
  /* высота окна увеличена только для захвата: закреплённые элементы встают на свои места */
  const full = await page.evaluate(() => document.documentElement.scrollHeight);
  await page.setViewportSize({width, height: Math.min(Math.max(full, 600), 3200)});
  await page.waitForTimeout(300);
  await page.screenshot({path: file});
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
  console.log(name, width, 'overflow=' + overflow);
  return overflow;
}
async function scenario(browser, title, role, address, patch, steps, name, afterSeed) {
  for (const [width, height] of [[1280, 900], [375, 812]]) {
    await seed(address, patch);
    if (afterSeed) await afterSeed();
    const {ctx, page} = await open(browser, role, width, height);
    try { if (steps) await steps(page); await shot(page, name, width); }
    finally { await ctx.close(); }
  }
}
const click = async (page, sel) => { await page.locator(sel).first().click(); await page.waitForTimeout(700); };

async function state() { const j = await api('admin', 'GET', '/api/stand/state'); return j; }
async function mutate(fn) { const j = await state(); fn(j.data.deals.find(d => d.id === DEAL), j.data); await api('admin', 'POST', '/__shots/board', {state: j.data}); }
async function act(role, path, extra = {}) {
  const j = await state();
  const r = await api(role, 'POST', '/api/stand/transfer/' + path, {dealId: DEAL, version: j.version, ...extra});
  if (!r.success) console.log('ACT FAIL', role, path, JSON.stringify(r).slice(0, 200));
  return r;
}
async function crmShot(browser, role, width, height, name) {
  const ctx = await browser.newContext({viewport: {width, height}});
  await ctx.addCookies([{name: 'session', value: cookies[role], url: ORIGIN}]);
  const page = await ctx.newPage();
  await page.route('**/*', route => new URL(route.request().url()).origin === ORIGIN ? route.continue() : route.abort());
  page.on('pageerror', e => console.log('PAGEERROR crm', e.message));
  await page.goto(ORIGIN + '/crm', {waitUntil: 'domcontentloaded'});
  await page.waitForTimeout(1500);
  await page.evaluate(() => { document.querySelector('[data-section="transactions"]')?.click(); });
  await page.waitForTimeout(1500);
  const box = await page.locator('#addWalletForm').evaluate(el => { const r = el.getBoundingClientRect(); return {top: r.top + scrollY, height: r.height}; });
  await page.setViewportSize({width, height: Math.ceil(box.top + box.height + 120)});
  await page.waitForTimeout(400);
  await page.evaluate(() => scrollTo(0, 0));
  const file = path.join(OUT, `${name}__${width}.png`);
  await page.screenshot({path: file, clip: {x: 0, y: Math.max(0, box.top - 70), width, height: Math.min(box.height + 90, 1200)}});
  console.log(name, width, 'overflow=' + await page.evaluate(() => document.documentElement.scrollWidth - innerWidth));
  await ctx.close();
}

(async () => {
  const browser = await chromium.launch({headless: true});
  const only = process.argv[3] ? new Set(process.argv[3].split(',')) : null;
  const run = (name, fn) => (!only || only.has(name)) ? fn() : null;
  await run('01', () => scenario(browser, '', 'operator', REALTY, {step: 's23'}, async page => {
    await click(page, '[data-handoff-open]');
  }, '01_operator_handoff_picker'));
  await run('02', () => scenario(browser, '', 'findir', REALTY, {step: 's23'}, null, '02_findir_after_handoff',
    async () => { await act('admin', 'handoff', {toRole: 'findir'}); }));
  await run('03', () => scenario(browser, '', 'teodor', REALTY, {step: 's23'}, null, '03_owner_after_handoff',
    async () => { await act('admin', 'handoff', {toRole: 'findir'}); await act('admin', 'handoff', {toRole: 'teodor'}); }));
  await run('04', () => scenario(browser, '', 'admin', EXCHANGE, {step: 's23'}, async page => {
    await page.screenshot({path: '/tmp/wallet-handoff-qa/debug04.png', fullPage: true});
    await click(page, '[data-handoff-open]');
  }, '04_sign_reassign_picker', async () => {
    await act('operator', 'claim');
    await mutate(d => { d.step = 's24'; });
  }));
  await run('05', async () => { for (const [w, h] of [[1280, 900], [375, 812]]) await crmShot(browser, 'admin', w, h, '05_crm_new_wallet_form'); });
  await run('06', () => scenario(browser, '', 'admin', REALTY, {step: 's23'}, async page => {
    await click(page, '[data-handoff-open]');
    await click(page, '[data-handoff-to="findir"]');
  }, '06_takeover_confirm_dialog', async () => { await act('operator', 'claim'); }));
  const takeover = async () => {
    await act('operator', 'claim');
    const j = await state();
    const claim = j.data.deals.find(d => d.id === DEAL).transferClaim;
    await act('admin', 'handoff', {toRole: 'findir', takeover: true, claimAt: claim.at});
  };
  await run('07', () => scenario(browser, '', 'findir', REALTY, {step: 's23'}, null, '07_new_executor_warning', takeover));
  await run('08', () => scenario(browser, '', 'operator', REALTY, {step: 's23'}, null, '08_former_executor_handed_over', takeover));
  await run('09', () => scenario(browser, '', 'teodor', REALTY, {step: 's23'}, null, '09_two_transfers_alarm', async () => {
    await act('operator', 'claim');
    await mutate(d => { d.transferAlarm = {hashes: ['a1'.repeat(32), 'b2'.repeat(32)], at: Date.now()}; });
  }));
  const ownerTask = async () => { await act('admin', 'handoff', {toRole: 'teodor'}); };
  await run('10', () => scenario(browser, '', 'operator', REALTY, {step: 's23'}, null, '10_operator_money_sent_owner_task', ownerTask));
  await run('11', () => scenario(browser, '', 'manager', REALTY, {step: 's23'}, null, '11_manager_no_dispatch_buttons', ownerTask));
  await browser.close();
})().catch(e => { console.error(e); process.exit(1); });
