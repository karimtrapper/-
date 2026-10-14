// Рендер s18: поступления Сбера доступны только при отправке с того же счёта.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const html = fs.readFileSync('static/stand/tasks.html', 'utf8');
const fn = name => {
  const match = html.match(new RegExp(`^function ${name}\\([^]*?^}`, 'm'));
  assert.ok(match, name);
  return match[0];
};
const step = html.match(/  s18:\(\)=>\{[^]*?\n  s18w:\(\)=>\{/);
assert.ok(step);
const stepCode = `const stepS18=({${step[0].slice(0, -'  s18w:()=>{'.length)}}).s18;`;
const main = {id: 100, code: 'СД-100', client: 'Клиент', step: 's18',
  payinParts: [{incId: 'sber:main', amountRub: 10000}], incomeAmount: 10000,
  amountRub: 10000, amountThb: 10000, rates: {broker: 100}, conv: []};
const incomes = [{id: 'sber:main', source: 'sber', dealId: 100, rub: 10000,
  grossRub: 10000}];
const ctx = {S: {deals: [main], incomes}, d: main, ap: {rub: 10000},
  s18Candidates: [{id: 2, uuid: 'crm2', rub: 20000, dealId: 42,
    client: 'Обмен', payer: 'Иванов', date: '2026-10-13T17:31:00',
    dealRub: 20000, payoutUsdt: 150},
  {id: 3, uuid: 'crm3', rub: 5000, dealId: null, payer: 'Петров', date: '2026-10-12T12:00:00'}],
  s18Selected: new Set([2, 3]),
  incomes: () => incomes, deal: id => ctx.S.deals.find(d => d.id === id),
  isCrypto: () => false, exSum: () => 0, exMargin: () => 0,
  rubBatchReady: () => true, brokerPicked: () => '', brokerQuote: () => null,
  quoteUsed: () => null, brokerOpts: () => [], brokerRate: () => '100',
  brokerSend: rub => ({sent: rub - rub * .003 - 40, held: rub * .003 + 40,
    ctrl: rub * .001 + 40, ours: rub * .002, ctrlPct: .1, oursPct: .2, fix: 40}),
  walletById: () => null, walletCards: () => '', transferModeBlock: () => '',
  money: String, moneyKop: (v,c) => Number(v).toLocaleString('ru-RU',
    {minimumFractionDigits:2,maximumFractionDigits:2})+(c?' '+c:''), usd: String,
  htmlText: String, num: Number, pct: String,
  avgUsdt: () => 33, approx: () => ({thb: 0}), econ: () => ({sentUsd: 0})};
vm.createContext(ctx);
vm.runInContext(['pendingEx', 's18Sber', 's18Rub', 's18CrmRows',
  's18DateKey', 's18DateLabel', 's18FilteredRows', 's18CrmSection',
  'convMargin', 'convMarginBlock'].map(fn).join('\n')+
  '\nlet s18Candidates=[], s18Selected=new Set(), s18SelectedDealId=null;'+
  "let s18Filters={query:'',from:'',to:''},s18Expanded={crm:false,unlinked:false};\n"+stepCode, ctx);
// Глобальные let заполняем внутри контекста: браузер хранит выбор локально.
vm.runInContext(`s18Candidates=${JSON.stringify(ctx.s18Candidates)};s18Selected=new Set([2,3]);s18SelectedDealId=100;`, ctx);
let rendered = vm.runInContext('stepS18()', ctx);
assert.match(rendered, /Сделка #42 · Обмен/);
assert.match(rendered, /Поступление без сделки/);
assert.match(rendered, /Состав пачки · 3 поступл\./);
assert.match(rendered, /Отметьте поступления для этого перевода/);
assert.match(rendered, /Сделки CRM/);
assert.match(rendered, /12\.10, 12:00/);
assert.match(rendered, /Ориентировочная прибыль по сделкам с известными обязательствами/);
assert.match(rendered, /Фикс 40 ₽ за поручение делится по долям/);
assert.match(rendered, /<details class="deal-detail s18-detail"><summary>Удержания/);
assert.doesNotMatch(rendered, /Объём обмена<\/label><input/);
assert.match(rendered, /Период с <span class="sub2">дд\.мм\.гггг<\/span>/);
assert.match(html, /\.s18-batch-summary\{[^}]*background:#fff/);
assert.match(rendered, /прибыль не считаем — сделки нет/);
const withUnknown = vm.runInContext('convMargin(d,35000,100,s18Candidates)', ctx);
const withoutUnknown = vm.runInContext('convMargin(d,30000,100,[s18Candidates[0]])', ctx);
assert.equal(withUnknown.unlinkedRub, 5000);
assert.equal(withUnknown.crmCost, 150);
assert.ok(Math.abs(withUnknown.profit-withoutUnknown.profit)<1);
assert.ok(withUnknown.profit<100);
const splitCrm = vm.runInContext(`convMargin(d,30000,100,[
  {dealId:42,rub:10000,dealRub:20000,payoutUsdt:150},
  {dealId:42,rub:10000,dealRub:20000,payoutUsdt:150}])`, ctx);
assert.equal(splitCrm.crmCost, 150); // две части одной сделки — одно обязательство
const missingCost = vm.runInContext('convMargin(d,15000,100,[{dealId:43,rub:5000}])', ctx);
assert.equal(missingCost.missingCrm, 1);
assert.ok(missingCost.usdtIn<150); // неизвестная себестоимость не становится прибылью
vm.runInContext("s18Filters.query='Иванов'", ctx);
assert.equal(vm.runInContext('s18FilteredRows(s18Candidates).length', ctx), 1);
vm.runInContext("s18Filters.query='#42'", ctx);
assert.equal(vm.runInContext('s18FilteredRows(s18Candidates).length', ctx), 1);
vm.runInContext("s18Filters.query='';s18Filters.from='2026-10-13'", ctx);
assert.equal(vm.runInContext('s18FilteredRows(s18Candidates).length', ctx), 1);
vm.runInContext("s18Filters.from='';s18Filters.to='2026-10-12'", ctx);
assert.equal(vm.runInContext('s18FilteredRows(s18Candidates).length', ctx), 1);
vm.runInContext("s18Filters.to=''", ctx);
const many = Array.from({length: 25}, (_, i) => ({id: i+10, rub: 100,
  payer: 'Плательщик '+i, date: '2026-10-12T17:31:00'}));
ctx.many = many;
let section = vm.runInContext("s18CrmSection(many,'unlinked','Поступления без сделки',v=>v)", ctx);
assert.match(section, /Показать все \(25\)/);
assert.equal((section.match(/s18ToggleCrm\(/g)||[]).length, 10);
vm.runInContext('s18Expanded.unlinked=true', ctx);
section = vm.runInContext("s18CrmSection(many,'unlinked','Поступления без сделки',v=>v)", ctx);
assert.equal((section.match(/s18ToggleCrm\(/g)||[]).length, 25);
assert.match(section, /Свернуть до 10/);
main.payinParts = [{incId: 'manual:1', amountRub: 10000}];
main.manualBankReceipt = {bank: 'БАНК СГБ', account: '40807810819000000261'};
incomes[0] = {id: 'manual:1', source: 'manual_confirmed', dealId: 100,
  rub: 10000, grossRub: 10000};
rendered = vm.runInContext('stepS18()', ctx);
assert.match(rendered, /СД-100 · Клиент/);
assert.doesNotMatch(rendered, /поступления Сбера сюда не добавить|Первая строка|Отметьте поступления/);
assert.doesNotMatch(rendered, /Сделка #42|Поступление без сделки/);
main.manualBankReceipt = {bank: 'Банк клиента', account: '40702810123456789012'};
rendered = vm.runInContext('stepS18()', ctx);
assert.doesNotMatch(rendered, /Банк клиента · 40702810123456789012|Отметьте поступления/);
assert.doesNotMatch(rendered, /Сделка #42|Поступление без сделки/);
incomes[0] = {id: 'sber:main', source: 'sber', dealId: 100, rub: 9930,
  grossRub: 10000};
main.payinParts = [{incId: 'sber:main', amountRub: 10000}];
assert.equal(vm.runInContext('s18Rub(d)', ctx), 9930);
console.log('s18 CRM income UI: PASS');
