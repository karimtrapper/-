const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const html = fs.readFileSync('static/stand/tasks.html', 'utf8');
for (const script of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g)) new vm.Script(script[1]);
const fn = name => {
  const match = html.match(new RegExp(`^function ${name}\\([^]*?^}`, 'm'));
  assert.ok(match, name);
  return match[0];
};
const d = {id: 1483, step: 's12', type: 'Оплата недвижимости', kind: 'Лизхолд',
  payType: 'По реквизитам', curBase: 'thb', amountThb: 1000, amountRub: 2700,
  incomeAmount: 2700, payinParts: [{incId: 10, amountRub: 2700}],
  expect: {amount: 2700, tol: 0},
  rates: {client: '2,70', rubUsdt: '85', usdtThb: '31', at: 1},
  docVersion: 1, docPack: {version: 1, amount: '2700', rate: '2.70'},
  docFields: {fio: 'Ксения Тест', amountPay: '2700', amountThb: '1000', rate: '2,70'},
  quotes: [{dir: 'rub', rate: '85'}], log: []};
const inputs = {r3: '2,90', r4: '2900', r1c: '87'};
const messages = [];
const ctx = vm.createContext({d, S: {role: 'manager'}, Date,
  deal: id => id === 1483 ? d : null,
  val: id => inputs[id] || '', num: value => Number(String(value || '').replace(',', '.')),
  cleanNum: value => String(value || '').replace(/[^\d.,]/g, ''),
  approx: deal => ({pay: deal.amountRub, thb: deal.amountThb, sign: '₽'}),
  fake: () => ({}), parsed: () => '', prevPassport: () => ({}),
  isCrypto: () => false, payinWallet: () => null,
  MF: {rubName: 'MF', inn: '9909726886', kpp: '770387001', bank: 'Сбер',
    acc: '40807810938720000286', ks: '30101810400000000225', bik: '044525225'},
  PAYIN_TOL: 0.01, payinSum: deal => deal.payinParts.reduce((sum, part) => sum + part.amountRub, 0),
  payinGot: () => 0, money: (amount, sign) => `${amount} ${sign}`,
  noteAdd: () => {}, go: (deal, step) => { deal.step = step; },
  toast: text => messages.push(text), save: () => {}, render: () => {},
  exchangeSpec: () => null, exchangeSync: () => {},
});
for (const name of ['docFields', 'expectOf', 'canRerate', 'rerateBalance',
                    'rerate', 'syncClient']) vm.runInContext(fn(name), ctx);

vm.runInContext('rerate(1483)', ctx);
assert.equal(d.step, 's5');
assert.equal(d.incomeAmount, 2700);
assert.equal(d.payinParts[0].amountRub, 2700);
assert.equal(d.docVersion, 1);
assert.equal(d.rerateExpectFollowsDeal, true);
assert.equal(d.rerateDocVersion, 1);

// Fresh quote arrives and the manager agrees a new price for the same invoice.
d.step = 's6'; d.rates = {rubUsdt: '87', usdtThb: '31', at: Date.now()};
vm.runInContext("syncClient(1483, 'rate')", ctx);
assert.equal(d.amountRub, 2900);
assert.equal(vm.runInContext('expectOf(d).amount', ctx), 2900);
assert.match(vm.runInContext('rerateBalance(d)', ctx), /Недоплата 200 ₽/);
let fields = vm.runInContext('docFields(d)', ctx);
assert.equal(fields.amountPay, 2900);
assert.equal(fields.rate, '2,90');
assert.equal(fields.fio, 'Ксения Тест');

inputs.r3 = '2,50';
vm.runInContext("syncClient(1483, 'rate')", ctx);
assert.equal(d.amountRub, 2500);
assert.equal(vm.runInContext('expectOf(d).amount', ctx), 2500);
assert.match(vm.runInContext('rerateBalance(d)', ctx), /Переплата 200 ₽/);
assert.equal(d.incomeAmount, 2700);

// The manager's own-rate route stays on the calculation step, with empty old quotes.
d.step = 's12'; d.selfRate = true;
vm.runInContext('rerate(1483)', ctx);
assert.equal(d.step, 's6');
assert.equal(Object.keys(d.rates).length, 0);
vm.runInContext("syncClient(1483, 'rubUsdt')", ctx);
assert.equal(d.rates.rubUsdt, '87');
assert.ok(d.rates.at);
console.log('rerate UI and credited-balance recalculation: PASS');
