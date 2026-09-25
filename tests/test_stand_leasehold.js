// Независимая проверка экономики и статусов задачника на чистых фикстурах.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../static/stand/tasks.html'), 'utf8');
function functions(names) {
  return names.map(name => {
    const found = html.match(new RegExp(`^function ${name}\\([^]*?^}`, 'm'));
    assert.ok(found, `Функция ${name} отсутствует`);
    return found[0];
  }).join('\n');
}
function run(names, context) {
  vm.createContext(context);
  vm.runInContext(functions(names), context);
  return context;
}
const round2 = x => Math.round(x * 100) / 100;

// Предвыбранное назначение Coins не означает, что конвертация уже прошла.
{
  const d = {id: 1, step: 's15', closed: false, postConv: 'coins',
    pay: {}, rates: {}, log: []};
  const fields = {p_dev: 'Developer', p_amt: '350000', p_bank: 'Bank',
    p_acc: '123', p_purp: 'Invoice', p_inv: 'INV-1', p_due: '30.09'};
  const ctx = run(['act'], {
    S: {deals: [d]}, deal: () => d,
    document: {getElementById: () => null}, saveNote: () => {},
    need: () => false, val: key => fields[key] || '',
    cleanNum: x => String(x).replace(/[^\d.,]/g, ''),
    num: x => parseFloat(String(x).replace(',', '.')),
    flowOf: () => ['s14', 's15', 's18', 's18w', 's22', 's23', 's24', 's25', 's26'],
    go: (x, step) => { x.step = step; }, log: (x, t) => x.log.push(t),
    toast: () => {}, money: String, Math,
  });
  ctx.act(1, 's15');
  assert.equal(d.step, 's18');
  d.step = 's15';
  d.invoiceDetailsReturn = true;
  ctx.act(1, 's15');
  assert.equal(d.step, 's26');
  assert.ok(!d.invoiceDetailsReturn);
}

// Заявленная сумма никогда не подменяет подтвержденную сумму из сети.
{
  const ctx = run(['sendList', 'sendSum', 'sendDeclared', 'sendLeft', 'sendDone'], {
    pcAmount: x => x.transfer.amount, Math, Number,
  });
  const x = {transfer: {amount: 100, sends: [
    {amount: 100, status: 'pending'},
  ]}};
  assert.equal(ctx.sendDeclared(x), 100);
  assert.equal(ctx.sendSum(x), 0);
  assert.equal(ctx.sendDone(x), false);
  x.transfer.sends[0] = {amount: 100, verifiedAmount: 60, status: 'confirmed'};
  assert.equal(ctx.sendSum(x), 60);
  assert.equal(ctx.sendLeft(x), 40);
  assert.equal(ctx.sendDone(x), false);
  x.transfer.sends.push({amount: 40, status: 'failed'});
  assert.equal(ctx.sendDeclared(x), 100);
  assert.equal(ctx.sendSum(x), 60);
  x.transfer.sends[1] = {amount: 40, verifiedAmount: 40, status: 'confirmed'};
  assert.equal(ctx.sendDone(x), true);
}

// Каждую входящую транзакцию делим в целых центах; суммы долей равны ее факту.
{
  const deals = [
    {id: 1, code: 'СД-1', step: 's18w', conv: [2, 3], pay: {}, rates: {broker: '81,40', usdtThb: '31,20'}, log: [], demoTransfers: true},
    {id: 2, code: 'СД-2', step: 'pack', pay: {}, rates: {}, log: []},
    {id: 3, code: 'СД-3', step: 'pack', pay: {}, rates: {}, log: []},
  ];
  const conv = {status: 'sent', sources: [
    {dealId: 1, rub: 931000, usdt: 11400},
    {dealId: 2, rub: 238000, usdt: 2900},
    {dealId: 3, rub: 64000, usdt: 700},
  ], txs: [
    {amount: 12345.67, net: 'TRC20', hash: 'tx-a', status: 'confirmed', demo: true},
    {amount: 2345.01, net: 'TRC20', hash: 'tx-b', status: 'confirmed', demo: true},
  ]};
  const ctx = run(['act'], {
    S: {deals}, document: {getElementById: () => null},
    deal: id => deals.find(d => d.id === id), convOf: () => conv,
    hashSum: list => list.length ? round2(list.reduce((s, t) => s + t.amount, 0)) : null,
    saveNote: () => {}, log: (d, t) => d.log.push(t),
    go: (d, step) => { d.step = step; }, toast: () => {},
    avgUsdt: () => 31.2, exSum: () => 302000, exMargin: () => 0,
    money: String, usd: String, pcOut: () => 0, now: () => '24.09, 17:00',
    Math, Number, String,
  });
  ctx.act(1, 's18w');
  assert.equal(deals[0].step, 's22');
  assert.equal(conv.status, 'received');
  for (let i = 0; i < conv.txs.length; i++) {
    const totalCents = conv.sources.reduce((sum, src) =>
      sum + Math.round(deals.find(d => d.id === src.dealId).payinHashes[i].amount * 100), 0);
    assert.equal(totalCents, Math.round(conv.txs[i].amount * 100));
  }
  assert.equal(round2(conv.sources.reduce((s, src) => s + src.usdtFact, 0)), 14690.68);
  assert.equal(deals[0].pay.usdt, conv.sources[0].usdtFact);
}

// Для лизхолда себестоимость по факту перевода, а батовая часть по факту Coins.
{
  const d = {type: 'Оплата недвижимости', kind: 'Лизхолд', amountThb: 350000,
    rates: {usdtThb: '31,20', broker: '81,40'}, postConv: 'coins', companyPct: 1,
    transfer: {amount: 11217.95, rate: '31,20', thb: 353500},
    mfPayout: [{hash: 'tx-a', amount: 7000}, {hash: 'tx-b', amount: 4217.95}],
    payout: {}, pay: {coinsCredit: {thb: 353000, ref: 'scb-1'}}, agents: []};
  const ctx = run(['econ'], {
    payinParts: () => [{usdt: 12000, calc: 11990, fact: 12000, kept: 0, ctrl: 0}],
    mfList: x => x.mfPayout, mfSum: x => round2(x.mfPayout.reduce((s, t) => s + t.amount, 0)),
    hashSum: () => null, pcAmount: x => x.transfer.amount,
    refAgents: () => [], num: x => x == null ? null : parseFloat(String(x).replace(',', '.')),
    cleanNum: x => String(x).replace(/[^\d.,]/g, ''), Math,
  });
  const e = ctx.econ(d);
  assert.equal(e.cost, 11217.95);
  assert.equal(e.sentThb, 353000);
  assert.equal(e.feeThb, 3000);
  assert.equal(round2(e.crypto), 782.05);
  assert.equal(round2(e.gross), round2(782.05 + 3000 / 31.2));
  assert.equal(e.ready, true);
}

// Coins: сначала уведомление, затем один SCB credit; инвойс списывается один раз.
{
  const d = {id: 1, code: 'СД-1', step: 's25', closed: false, type: 'Оплата недвижимости',
    kind: 'Лизхолд', amountThb: 350000, postConv: 'coins',
    transfer: {thb: 353500, amount: 11217.95,
      sends: [{amount: 11217.95, verifiedAmount: 11217.95, status: 'confirmed', hash: 'tx-a'}]},
    pay: {}, payTo: {acc: '123', amount: 350000, dev: 'Developer'}, docs: {},
    payout: {source: 'Coins / Bitazza', usdt: 11217.95}, log: []};
  const S = {deals: [d], wallets: {scb: 2100000}};
  const inputs = {};
  let scb = 2100000;
  const toasts = [];
  const ctx = run(['act'], {
    S, document: {getElementById: () => null}, deal: () => d,
    saveNote: () => {}, cnvMembers: () => [d], pcSends: () => true,
    sendDone: () => d.transfer.sends[0].status === 'confirmed',
    val: k => inputs[k] || '', toast: t => toasts.push(t),
    log: (x, t) => x.log.push(t), save: () => {}, render: () => {},
    go: (x, step) => { x.step = step; },
    cleanNum: x => String(x).replace(/[^\d.,]/g, ''),
    num: x => parseFloat(String(x).replace(',', '.')),
    coinsThb: () => 353500, bal: () => ({scb}), balOf: () => scb,
    balTake: (_src, amount) => {scb -= amount; return amount;},
    SOURCES_PAY: {scb: {t: 'SCB'}}, approx: () => ({thb: 350000}),
    now: () => '24.09, 17:00', moneyKop: String, money: String,
    Math, Number, String,
  });
  // bal() в настоящем состоянии возвращает объект по ссылке.
  ctx.bal = () => ({get scb() {return scb;}, set scb(v) {scb = v;}});
  ctx.act(1, 's25');
  assert.equal(d.step, 's25');
  assert.equal(d.pay.coinsNotified, true);
  assert.equal(scb, 2100000);
  inputs.coins_thb = '353000'; inputs.coins_ref = 'SCB-QA-1';
  inputs.coins_gap = 'Комиссия Coins 500 THB';
  // расхождение с заявкой шаг не запирает — пишется в журнал (Карим, 25.09)
  ctx.act(1, 's25');
  assert.equal(d.step, 's26');
  assert.ok(d.log.some(l => String(l.text || l).includes('расхождение с заявкой')), 'расхождение записано');
  assert.equal(scb, 2453000);
  assert.equal(d.pay.coinsCredit.thb, 353000);
  ctx.act(1, 's26');
  assert.equal(d.step, 's26', 'без чека нельзя списать инвойс');
  assert.equal(scb, 2453000);
  d.docs.receipt = true;
  ctx.act(1, 's26');
  assert.equal(d.step, 's27');
  assert.equal(scb, 2103000);
  assert.equal(d.payout.usdt, 11217.95);
  assert.equal(d.payout.invoice.thb, 350000);
  ctx.act(1, 's26');
  assert.equal(scb, 2103000, 'повторное действие не списывает деньги');
}

console.log('stand leasehold: send statuses, cents, economics, Coins/SCB PASS');
