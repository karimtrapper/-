// Проверка нового блока чеков на настоящих функциях задачника.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const html = fs.readFileSync('static/stand/tasks.html', 'utf8');
const names = ['fileValid', 'filesOf', 'fileSync', 'fileAppend', 'fileDel',
  'clientPayinCanAdd', 'clientPayinCanDelete', 'clientPayinNote',
  'clientPayinBlock', 'docListRows'];
const source = names.map(name => {
  const match = html.match(new RegExp(`^(?:async )?function ${name}\\([^]*?^}`, 'm'));
  assert.ok(match, name);
  return match[0];
}).join('\n');

const safe = v => String(v == null ? '' : v).replace(/[&<>"']/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const deal = {id: 1485, step: 's12', docs: {}, files: {}, log: []};
const ctx = {S: {role: 'manager', deals: [deal]}, standMe: 'manager', standMeId: 1,
  STAND_EMPLOYEES: [{id: 1, display_name: 'Елизавета'}],
  ROLES: {manager: {n: 'Елизавета'}}, deal: () => deal,
  managerDraftDocTarget: () => null, htmlText: safe, now: () => '12.10',
  log: (d, text) => d.log.push({text}), save: () => {}, render: () => {},
  toast: () => {}, DOCT: {clientPayinReceipt: 'Чеки клиента об оплате'},
  docFileOf: () => null, doctOf: () => 'Документ', docIssuedTitle: () => '',
  docExt: () => '', fileUrl: () => '', atob, crypto: {randomUUID: () => '12345678-1234-1234-1234-123456789abc'},
  docFileNameHtml: safe, STAND: false, SCREEN: false, SNAP: false};
vm.createContext(ctx);
vm.runInContext(source, ctx);

assert.match(ctx.clientPayinBlock(deal), /приход подтверждает только операционист/i);
assert.doesNotMatch(ctx.clientPayinBlock(deal), /Загрузить/);
deal.docsSent = {at: '12.10', version: 3};
assert.match(ctx.clientPayinBlock(deal), /Загрузить/);
const data = 'data:application/pdf;base64,' + Buffer.from('%PDF-1.4\nreceipt').toString('base64');
(async () => {
  await ctx.fileAppend(1485, 'clientPayinReceipt', {file: 'client.pdf', size: '1 КБ',
    at: '12.10', mime: 'application/pdf', bytes: 16, data, demo: false});
  assert.equal(deal.files.clientPayinReceipt.length, 1);
  assert.equal(deal.docs.clientPayinReceipt, undefined);
  assert.match(deal.log[0].text, /Чек клиента прикреплён · client.pdf · Елизавета/);
  assert.match(ctx.clientPayinBlock(deal), /client.pdf/);
  assert.match(ctx.docListRows(deal).client.join(''), /Чек клиента об оплате/);
  ctx.clientPayinNote(1485, 0, '50 000 ₽ · 12.10 · Иванов');
  assert.match(ctx.clientPayinBlock(deal), /50 000 ₽/);
  ctx.S.role = 'operator'; ctx.standMe = 'operator'; ctx.standMeId = 2;
  assert.doesNotMatch(ctx.clientPayinBlock(deal), /Убрать/);
  ctx.fileDel(1485, 'clientPayinReceipt', 0);
  assert.equal(deal.files.clientPayinReceipt.length, 1);
  ctx.standMe = 'admin'; ctx.standMeId = 3;
  ctx.fileDel(1485, 'clientPayinReceipt', 0);
  assert.equal(deal.files.clientPayinReceipt.length, 0);
  assert.match(deal.log.at(-1).text, /Чек клиента удалён/);
  console.log('client payin receipts UI: passed');
})().catch(error => {console.error(error); process.exitCode = 1;});

// Верхняя сводка берёт только подтверждённый приход клиента, даже при авансе.
const summaryNames = ['clientPayinSummarySupported', 'clientPayinSummaryData', 'clientPayinSummary'];
const summarySource = summaryNames.map(name => {
  const match = html.match(new RegExp(`^function ${name}\\([^]*?^}`, 'm'));
  assert.ok(match, name);
  return match[0];
}).join('\n');
const bankIncomes = [
  {id: 1, dealId: 99, source: 'sber', rub: 3000, acc: 'Сбер · 40807810938720000286'},
  {id: 2, dealId: 99, source: 'sber', rub: 2000, acc: 'Сбер · 40807810938720000286', demo: true},
  {id: 3, dealId: 88, source: 'sber', rub: 1000, acc: 'Чужой банк · 40702810900000012345'},
  {id: 4, dealId: 99, source: 'manual_confirmed', manualReceiptId: 'm1',
    rub: 1500, acc: 'Другой банк · 40702810900000012345'},
  {id: 5, dealId: 99, source: 'sber', rub: 1000, acc: 'Сбер · 40807810938720000286'},
  {id: 6, dealId: 99, source: 'sber', rub: 9800, grossRub: 10000,
    acc: 'Сбер эквайринг · 40807810938720002118'}
];
const summaryCtx = vm.createContext({
  isCrypto: d => d.payType === 'Крипта', payCur: d => d.input||
    (d.payType === 'Крипта'?'usdt':'rub'), approx: d => ({pay: d.amountUsdt}),
  expectOf: d => ({amount: d.amountRub, acc: 'Ожидаемый счёт', tol: 1000}),
  S: {incomes: bankIncomes}, payinForeign: (d, h) => !!h.unknownSender,
  incomeRubBasis: (income, isNet) => isNet?income.rub:(income.grossRub??income.rub),
  partRubBasis: (deal, part) => part.rubIsNet===true,
  payinWallet: () => ({name: 'Кошелёк Grusha', net: 'TRC-20', addr: 'TWallet'}),
  payinNet: () => 'TRC-20', accountShortLabel: account => account,
  rnd2: value => Math.round(value * 100) / 100, PAYIN_TOL: 5,
  moneyKop: (value, currency) => `${value} ${currency}`, htmlText: safe
});
vm.runInContext(summarySource, summaryCtx);
const cryptoPayin = {id: 99, payType: 'Крипта', amountUsdt: 100, walletId: 'wallet',
  prepay: {amount: 100}, payinHashes: [
    {amount: 40, verified: true, to: 'TWallet'},
    {amount: 20, verified: false, to: 'TWallet'},
    {amount: 10, verified: true, unknownSender: true, to: 'TWallet'},
    {amount: 5, verified: true, demo: true, to: 'TWallet'}
  ]};
assert.equal(summaryCtx.clientPayinSummaryData(cryptoPayin).received, 40);
assert.match(summaryCtx.clientPayinSummary(cryptoPayin), /Частичный приход · осталось 60 USDT/);
assert.match(summaryCtx.clientPayinSummary(cryptoPayin), /Кошелёк Grusha · TRC-20 · TWallet/);
cryptoPayin.payinHashes = [{amount: 100, verified: false}];
assert.equal(summaryCtx.clientPayinSummaryData(cryptoPayin).received, 0);
assert.match(summaryCtx.clientPayinSummary(cryptoPayin), /Есть перевод без подтверждения/);
assert.match(summaryCtx.clientPayinSummary(cryptoPayin), /class="client-payin-summary empty"/);
cryptoPayin.payinHashes = [{amount: 30, verified: true, network: 'TRC20', to: 'TWallet'},
  {amount: 10, verified: true, network: 'ERC20', to: '0xWallet'}];
assert.match(summaryCtx.clientPayinSummary(cryptoPayin), /TRC20 · TWallet — 30 USDT/);
assert.match(summaryCtx.clientPayinSummary(cryptoPayin), /ERC20 · 0xWallet — 10 USDT/);
const rubPayin = {id: 99, payType: 'По реквизитам', amountRub: 10000,
  payinParts: [{incId: 1, amountRub: 3000}, {incId: 2, amountRub: 2000},
    {incId: 3, amountRub: 1000}, {incId: 4, amountRub: 1500},
    {incId: 5, amountRub: 900}],
  manualBankReceipt: {id: 'm1', status: 'pending', actualAmount: 1500}};
assert.equal(summaryCtx.clientPayinSummaryData(rubPayin).received, 3000);
assert.match(summaryCtx.clientPayinSummary(rubPayin), /Сбер · 40807810938720000286/);
rubPayin.manualBankReceipt = {id: 'm1', status: 'confirmed', actualAmount: 1500,
  confirmedAt: '2026-11-09', confirmedBy: 7};
assert.equal(summaryCtx.clientPayinSummaryData(rubPayin).received, 4500);
assert.match(summaryCtx.clientPayinSummary(rubPayin), /Другой банк · 40702810900000012345/);
assert.match(summaryCtx.clientPayinSummary(rubPayin), /Сбер · 40807810938720000286 — 3000 ₽/);
assert.match(summaryCtx.clientPayinSummary(rubPayin), /Другой банк · 40702810900000012345 — 1500 ₽/);
const acquiring = {...rubPayin, payinParts: [{incId: 6, amountRub: 10000}],
  amountRub: 10000};
assert.equal(summaryCtx.clientPayinSummaryData(acquiring).received, 10000);
assert.match(summaryCtx.clientPayinSummary(acquiring), /На счёт: 9800 ₽ · Сбер эквайринг/);
const twoBanksWithFee = {...rubPayin, payinParts: [{incId: 1, amountRub: 3000},
  {incId: 6, amountRub: 10000}], amountRub: 13000};
assert.match(summaryCtx.clientPayinSummary(twoBanksWithFee), /Сбер · 40807810938720000286 — 3000 ₽/);
assert.match(summaryCtx.clientPayinSummary(twoBanksWithFee), /Сбер эквайринг · 40807810938720002118 — 9800 ₽/);
bankIncomes.push(
  {id: 7, dealId: 99, source: 'sber', rub: 1000,
    acc: 'Другой банк · 40702810000000001234'},
  {id: 8, dealId: 99, source: 'sber', rub: 2000,
    acc: 'Другой банк · 40702819999999991234'});
summaryCtx.accountShortLabel = account => account.startsWith('Другой банк · 407028')?
  'Другой банк …1234':account;
const sameTailAccounts = {...rubPayin, payinParts: [{incId: 7, amountRub: 1000},
  {incId: 8, amountRub: 2000}]};
assert.equal(summaryCtx.clientPayinSummaryData(sameTailAccounts).destinations.length, 2);
assert.match(summaryCtx.clientPayinSummary(sameTailAccounts), /40702810000000001234 — 1000 ₽/);
assert.match(summaryCtx.clientPayinSummary(sameTailAccounts), /40702819999999991234 — 2000 ₽/);
const liveShape = {...rubPayin, amountRub: 189134.29,
  payinParts: [{incId: 4, amountRub: 189134.37, rubIsNet: true}]};
bankIncomes[3].rub = 189134.37;
liveShape.manualBankReceipt.actualAmount = 189134.37;
assert.match(summaryCtx.clientPayinSummary(liveShape), /Получено · ожидали 189134.29 ₽/);
assert.equal(summaryCtx.clientPayinSummarySupported({...rubPayin, cashPartnerUsdt: true}), false);
assert.equal(summaryCtx.clientPayinSummarySupported({...rubPayin, input: 'thb'}), false);
assert.equal(summaryCtx.clientPayinSummarySupported({...rubPayin, payType: 'Наличные'}), false);
assert.equal(summaryCtx.clientPayinSummarySupported(cryptoPayin), true);
console.log('client payin summary: passed');
