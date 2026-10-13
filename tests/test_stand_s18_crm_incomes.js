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
  amountRub: 10000, rates: {}, conv: []};
const incomes = [{id: 'sber:main', source: 'sber', dealId: 100, rub: 10000,
  grossRub: 10000}];
const ctx = {S: {deals: [main], incomes}, d: main, ap: {rub: 10000},
  s18Candidates: [{id: 2, uuid: 'crm2', rub: 20000, dealId: 42,
    client: 'Обмен', payer: 'Иванов', date: '13.10'},
  {id: 3, uuid: 'crm3', rub: 5000, dealId: null, payer: 'Петров', date: '13.10'}],
  s18Selected: new Set([2, 3]),
  incomes: () => incomes, deal: id => ctx.S.deals.find(d => d.id === id),
  isCrypto: () => false, exSum: () => 0, exMargin: () => 0,
  rubBatchReady: () => true, brokerPicked: () => '', brokerQuote: () => null,
  quoteUsed: () => null, brokerOpts: () => [], brokerRate: () => '',
  brokerSend: rub => ({sent: rub - rub * .003 - 40, held: rub * .003 + 40,
    ctrl: rub * .001 + 40, ours: rub * .002, ctrlPct: .1, oursPct: .2, fix: 40}),
  walletById: () => null, walletCards: () => '', transferModeBlock: () => '',
  convMarginBlock: () => '', money: String, moneyKop: String, usd: String,
  htmlText: String, num: Number, pct: String};
vm.createContext(ctx);
vm.runInContext(['pendingEx', 's18Sber', 's18Rub', 's18CrmRows'].map(fn).join('\n')+
  '\nlet s18Candidates=[], s18Selected=new Set(), s18SelectedDealId=null;\n'+stepCode, ctx);
// Глобальные let заполняем внутри контекста: браузер хранит выбор локально.
vm.runInContext(`s18Candidates=${JSON.stringify(ctx.s18Candidates)};s18Selected=new Set([2,3]);s18SelectedDealId=100;`, ctx);
let rendered = vm.runInContext('stepS18()', ctx);
assert.match(rendered, /Сделка #42 · Обмен/);
assert.match(rendered, /Поступление без сделки/);
assert.match(rendered, /35[\s\u00a0]*000/);
main.payinParts = [{incId: 'manual:1', amountRub: 10000}];
main.manualBankReceipt = {bank: 'БАНК СГБ', account: '40807810819000000261'};
incomes[0] = {id: 'manual:1', source: 'manual_confirmed', dealId: 100,
  rub: 10000, grossRub: 10000};
rendered = vm.runInContext('stepS18()', ctx);
assert.match(rendered, /поступления Сбера сюда не добавить/);
assert.doesNotMatch(rendered, /Сделка #42|Поступление без сделки/);
main.manualBankReceipt = {bank: 'Банк клиента', account: '40702810123456789012'};
rendered = vm.runInContext('stepS18()', ctx);
assert.match(rendered, /Банк клиента · 40702810123456789012/);
assert.doesNotMatch(rendered, /Сделка #42|Поступление без сделки/);
incomes[0] = {id: 'sber:main', source: 'sber', dealId: 100, rub: 9930,
  grossRub: 10000};
main.payinParts = [{incId: 'sber:main', amountRub: 10000}];
assert.equal(vm.runInContext('s18Rub(d)', ctx), 9930);
console.log('s18 CRM income UI: PASS');
