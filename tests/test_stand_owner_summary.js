const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../static/stand/tasks.html'), 'utf8');
const names = ['brokerSend', 'freeholdFee', 'freeholdSend', 'freeholdEstimate', 'freeholdSummary6',
  'ownerDate', 'ownerEstimate', 'ownerSummary'];
const source = 'const BROKER_FEE={ctrl:0.1,fix:40,ours:0.2};\n' + names.map(name => {
  const found = html.match(new RegExp(`^function ${name}\\([^]*?^}`, 'm'));
  assert.ok(found, name);
  return found[0];
}).join('\n');
const incomes = [];
const conversions = [];
const wallets = [{id: 10, name: 'Кошелёк Теодора', owner: 'Теодор'},
  {id: 20, name: 'Кошелёк брокера', owner: 'компания'}];
const ctx = {
  S: {incomes},
  htmlText: value => String(value == null ? '' : value).replace(/[&<>"']/g,
    ch => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[ch])),
  moneyKop: (n, sign) => `${Number(n).toLocaleString('ru-RU', {minimumFractionDigits: 2})} ${sign}`,
  money: (n, sign) => `${n} ${sign}`, usd: n => `$${Number(n).toFixed(2)}`,
  usdMark: (d, n) => `${d.invoiceUsdEstimate ? '≈ ' : ''}$${Number(n).toFixed(2)}`,
  plural: (n, one, few, many) => n === 1 ? one : n < 5 ? few : many,
  employeeName: id => id === 9 ? 'Операционист Мария' : null,
  expectOf: d => ({amount: d.expectedRub || 192666.3}),
  filesOf: (d, kind) => d.files?.[kind] || [],
  explorer: (hash, net) => `https://scan.example/${net}/${hash}`,
  isCrypto: d => d.payType === 'Крипта',
  econ: d => d.economics,
  num: value => value == null || value === '' ? null : Number(String(value).replace(',', '.')),
  rateUnit: () => '₽/$',
  dealWallet: d => d.prepay?.wallet || wallets.find(w => w.id === d.walletId),
  walletById: id => wallets.find(w => w.id === id),
  convOf: d => conversions.find(c => c.id === d.cnvId),
  ippsTariff: () => ({label: 'Банк · 0,8% + 50$', percent: 0.8, fixed: 50}),
};
vm.createContext(ctx);
vm.runInContext(source, ctx);

const base = {
  type: 'Оплата недвижимости', kind: 'Фрихолд', object: 'Квартира 4A', dev: 'Застройщик',
  payType: 'Рубли', payTo: {dev: 'Получатель', inv: 'INV-1487'},
  invoiceUsd: 2152.47, rates: {client: 90, broker: 88},
  economics: {ready: true, gross: 50, pct: 2.1, byFact: false, payin: 2284.76,
    cost: 2234.76, bankFee: 82.22, sentUsd: 2234.76},
  files: {}, payout: {}, transfer: {amount: 2234.76, addr: 'IPPS-ADDRESS'},
};
const deal1487 = {...base, id: 1487, step: 's23', cnvId: 1,
  prepay: {wallet: wallets[0], amount: 2234.76},
  payinParts: [{amountRub: 192666.3, incId: 101, manualReceiptId: 'm1'}],
  manualBankReceipt: {bank: 'СГБ', account: '40807810819000000261',
    statementDate: '13.10.2026', statementRef: 'строка 15', confirmedBy: 9, status: 'confirmed'},
  files: {bankCreditEvidence: [{file: 'выписка.pdf'}],
    clientPayinReceipt: [{file: 'чек клиента.png'}]},
};
incomes.push({id: 101, source: 'manual_confirmed', acc: 'Flow Sole …0261 · СГБ',
  payer: 'Татьяна', date: '13.10.2026'});
conversions.push({id: 1, broker: 'Tradex', rate: 88, sentTs: '13.10 12:00',
  walletId: 20, sources: [{dealId: 1487, rub: 192666.3, usdt: 2189.39}], txs: []});
let card = ctx.ownerSummary(deal1487);
for (const text of ['192', 'Flow Sole …0261', 'Татьяна', 'строка 15', 'выписка.pdf',
  'чек клиента.png', 'Операционист Мария', 'INV-1487', 'Квартира 4A',
  '2 234,76 USDT', 'IPPS', '2152.47', 'Кошелёк Теодора', 'Tradex', 'ждём 2 189,39 USDT',
  '$50.00', '2,10 %', 'ждём USDT брокера']) assert.ok(card.includes(text), text);
assert.match(card, /Чеки клиента \(не подтверждают приход\)/);
assert.equal((card.match(/class="owner-line"/g) || []).length, 6);

const deal1484 = {...base, id: 1484, cnvId: 2, prepay: {wallet: wallets[0], amount: 2234.76},
  payinParts: [{amountRub: 250000, incId: 102}], files: {},
  economics: {...base.economics, byFact: true}};
incomes.push({id: 102, source: 'sber', acc: '…0286 · Сбер', docNumber: 'PAY-102'});
conversions.push({id: 2, broker: 'Tradex', receivedAt: '13.10', walletId: 20,
  sources: [{dealId: 1484, rub: 250000, usdt: 2800, usdtFact: 2799}],
  txs: [{hash: 'abc', net: 'TRC20', amount: 2799}]});
card = ctx.ownerSummary(deal1484);
for (const text of ['…0286 · Сбер', 'поступление из API Сбера', 'PAY-102',
  'USDT получены', '2799.00', 'факт по USDT брокера', 'scan.example/TRC20/abc']) assert.ok(card.includes(text), text);

const ordinary = {...deal1484, id: 1490, prepay: null, cnvId: 3, payinParts: []};
conversions.push({id: 3, broker: 'Tradex', receivedAt: '13.10', sources: [{dealId: 1490, usdtFact: 2500}], txs: []});
card = ctx.ownerSummary(ordinary);
assert.equal((card.match(/class="owner-line"/g) || []).length, 5);
assert.doesNotMatch(card, /Возмещение/);

const noReceipt = {...base, id: 1491, payinParts: [], rates: {},
  files: {clientPayinReceipt: [{file: '<img src=x onerror=alert(1)>.png'}]},
  economics: {ready: false}};
card = ctx.ownerSummary(noReceipt);
assert.match(card, /не пришли/);
assert.match(card, /нельзя посчитать: нет курса брокера/);
assert.match(card, /&lt;img src=x onerror=alert\(1\)&gt;/);
assert.doesNotMatch(card, /<img src=x/);
const saved1484 = JSON.parse(fs.readFileSync(path.join(__dirname,
  'fixtures/stand_1484_s23_anonymized.json'), 'utf8'));
const olderDeal = {...saved1484.deals[0], economics: {ready: false},
  expectedRub: saved1484.deals[0].amountRub};
const oldCard = ctx.ownerSummary(olderDeal);
assert.match(oldCard, /DEMO запись · реальный приход не подтверждён/);
assert.match(oldCard, /не пришли/);
assert.doesNotMatch(oldCard, /поступление из API Сбера/);
assert.match(oldCard, /Flow Sole …0261/);
assert.match(oldCard, /Инвойс.*E2E inv/);

// Снимок структуры живой 1487: котировка s6 есть, пачки пока нет.
const live1487 = {...base, id: 1487, cnvId: null, step: 's23',
  amountRub: 192666.31, incomeAmount: 192666.31,
  rates: {client: '89.51', rubUsdt: '84.95'},
  quotes: [{cpId: 'tradex', name: 'Tradex', rate: '84.95'}],
  docVersion: 3, docPack: {version: 3, at: Date.parse('2026-10-13T09:00:00Z'),
    amount: '192666.31', transfer: '2152.47'},
  prepay: {wallet: wallets[0], amount: 2234.76},
  manualBankReceipt: {status: 'confirmed', bank: 'Московский филиал "БАНК СГБ"',
    account: '40807810819000000261', statementDate: '2026-10-13',
    statementRef: 'строка 15', confirmedBy: 9, confirmedRole: 'operator',
    confirmedAt: '2026-10-13T09:15:00Z'},
  payinParts: [{amountRub: 192666.31, incId: 103, manualReceiptId: 'm3'}],
  files: {bankCreditEvidence: [{file: 'выписка.pdf'}]},
  economics: {ready: false, sentUsd: 2234.76, bankFee: 82.22}};
incomes.push({id: 103, source: 'manual_confirmed',
  acc: 'Московский филиал "БАНК СГБ" · 40807810819000000261',
  date: '13.10', payer: 'Татьяна'});
const expected = ctx.freeholdEstimate(live1487, 192666.31, 84.95);
assert.ok(expected.profit > 0 && expected.incoming > 2234.76);
const s6Rate = 192666.31 / 2152.47;
const s6View = ctx.freeholdSummary6({...live1487,
  rates: {...live1487.rates, client: String(s6Rate)}});
assert.ok(s6View.includes(ctx.moneyKop(expected.profit, 'USDT')));
card = ctx.ownerSummary(live1487);
for (const text of ['✓ пришли 13.10', '192 666,31 ₽', 'Flow Sole (СГБ) …0261 · выписка',
  '2 234,76 USDT → IPPS · застройщику $2152.47',
  'не отправлено', 'котировка Tradex 84,95',
  `ждём USDT ≈ ${ctx.moneyKop(expected.incoming, 'USDT')}`,
  `≈ $${expected.profit.toFixed(2)}`, 'ориентир по доступным данным договора от 13.10',
  'Операционист Мария', 'Сверка подтверждена', '13.10, 12:15']) assert.ok(card.includes(text), text);

live1487.ownerEconomyAtDoc = {version: 3, at: live1487.docPack.at,
  amountRub: 192666.31, invoiceUsd: 2152.47, ippsTariff: 'bank',
  brokerRate: 84.95, brokerName: 'Tradex'};
live1487.rates.rubUsdt = '93';
live1487.quotes = [{cpId: 'other', name: 'Другой', rate: '93'}];
card = ctx.ownerSummary(live1487);
assert.match(card, /ориентир на момент договора от 13\.10 · котировка Tradex 84,95/);
assert.ok(card.includes(`≈ $${expected.profit.toFixed(2)}`));
assert.doesNotMatch(card, /котировка Другой 93/);

live1487.docVersion = 4;
live1487.docPack = {...live1487.docPack, version: 4, at: Date.parse('2026-10-14T09:00:00Z')};
live1487.ownerEconomyAtDoc = {...live1487.ownerEconomyAtDoc, version: 4,
  at: live1487.docPack.at, brokerRate: 90, brokerName: 'Новый брокер'};
card = ctx.ownerSummary(live1487);
assert.match(card, /ориентир на момент договора от 14\.10 · котировка Новый брокер 90/);
assert.doesNotMatch(card, /котировка Tradex 84,95/);

live1487.cnvId = 4;
live1487.rates.broker = '89';
live1487.economics = {...live1487.economics, ready: true, gross: 18.5,
  pct: 0.82, payin: 2253.26, cost: 2234.76, byFact: false};
conversions.push({id: 4, broker: 'Tradex', rate: '89', sentTs: '14.10',
  sources: [{dealId: 1487, usdt: 2253.26}], txs: []});
card = ctx.ownerSummary(live1487);
assert.match(card, /ориентир по курсу пачки 89/);
assert.doesNotMatch(card, /ориентир на момент договора/);
live1487.economics.byFact = true;
conversions[conversions.length - 1].sources[0].usdtFact = 2250;
card = ctx.ownerSummary(live1487);
assert.match(card, /факт по USDT брокера/);
const cryptoFreehold = {...base, id: 1492, payType: 'Крипта', cnvId: null,
  payinHashes: [{hash: 'crypto-1', amount: 2300, verified: true}],
  economics: {...base.economics, byFact: true, gross: 65.24, pct: 2.84, payin: 2300}};
card = ctx.ownerSummary(cryptoFreehold);
assert.match(card, /факт по подтверждённым USDT клиента/);
assert.match(card, /crypto-1/);
const noDoc = {...live1487, cnvId: null, docVersion: null, docPack: null,
  ownerEconomyAtDoc: null, rates: {client: '89.51', rubUsdt: '84.95'},
  quotes: [{cpId: 'tradex', name: 'Tradex', rate: '84.95'}]};
card = ctx.ownerSummary(noDoc);
assert.match(card, /оценка по котировке · котировка Tradex 84,95/);
assert.match(html, /view==='task'&&\['s23','s24'\]\.includes\(d\.step\)&&\['teodor','findir','admin'\]\.includes\(S\.role\)\)body=ownerSummary\(d\)\+body/);
assert.match(html, /view==='deal'&&\['teodor','findir','admin'\]\.includes\(S\.role\)\?ownerSummary\(d\)/);
console.log('owner summary: prepay Flow Sole, Sber API, broker, no receipt, roles and escaping OK');
