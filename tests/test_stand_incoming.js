// Приход Сбера выбирается из API; тестовые записи и другие счета не выбираются.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const html = fs.readFileSync('static/stand/tasks.html', 'utf8');
const names = ['incomeRubBasis', 'partRubBasis', 'sberFree', 'payinSum', 'payinIssues', 'payinDone', 'sberTake',
  'rubApiAccount', 'expectOf', 'expectSet', 'payinPool'];
const source = names.map(name => {
  const match = html.match(new RegExp(`^function ${name}\\([^]*?^}`, 'm'));
  assert.ok(match, name);
  return match[0];
}).join('\n');

function fixture(overrides = {}) {
  const deal = {id: 1, code: 'СД-1', client: 'Клиент', step: 's14',
    amountRub: 100000, payinParts: [], log: [], rubReceivingAccount: {mode: 'sber'},
    expect: {amount: 100000, tol: 1000, acc: '…0286 · Сбер',
      account: '40807810938720000286', purpose: 'Договор СД-1'}, ...overrides};
  const S = {deals: [deal], incomes: [], role: 'operator'};
  const events = [];
  const ctx = {S, deal: () => deal, incomes: () => S.incomes,
    MF: {bank: 'ПАО Сбербанк', acc: '40807810938720000286'},
    FLOWSOLE: {bank: 'БАНК СГБ', acc: '40807810819000000261'},
    approx: d => ({pay: d.amountRub, cur: 'rub'}),
    docFields: () => ({purpose: 'Договор СД-1'}), isCrypto: () => false,
    editApply: () => {}, save: () => {}, render: () => {},
    log: (d, message) => d.log.push(message), go: (d, step) => {d.step = step;},
    afterPayin: d => {d.step = 's18'; d.reqTask = 'open';},
    toast: message => events.push(message), money: n => String(n),
    sberText: String, Number, Math, String, Set};
  vm.createContext(ctx); vm.runInContext(source, ctx);
  return {ctx, deal, S, events};
}

function income(id, rub, extra = {}) {
  return {id, rub, source: 'sber', kind: 'банк', acc: '…0286 · Сбер',
    purpose: 'Договор СД-1', payer: 'Клиент', date: '12.10',
    dealId: null, excluded: false, ...extra};
}

{
  const {ctx, deal, S} = fixture();
  S.incomes.push(income('sber:1', 60000), income('sber:2', 40000));
  ctx.sberTake(1, 'sber:1'); ctx.sberTake(1, 'sber:2'); ctx.payinDone(1);
  assert.equal(deal.step, 's18');
  assert.equal(deal.incomeAmount, 100000);
  assert.equal(deal.payinParts.length, 2);
}
{
  const {ctx, deal, S, events} = fixture();
  S.role = 'manager'; S.incomes.push(income('sber:manager', 100000));
  ctx.sberTake(1, 'sber:manager'); ctx.payinDone(1);
  assert.equal(deal.payinParts.length, 0);
  assert.equal(deal.step, 's14');
  assert.match(events.at(-1), /операционист/);
}
{
  const {ctx, deal, S, events} = fixture();
  S.incomes.push(income('sber:3', 100000, {demo: true}));
  assert.doesNotMatch(ctx.payinPool(deal), /Забрать<\/button>/);
  ctx.sberTake(1, 'sber:3');
  assert.equal(deal.payinParts.length, 0);
  assert.match(events.at(-1), /операционист/);
}
{
  const {ctx, deal, S, events} = fixture({rubReceivingAccount: {mode: 'flowsole'}});
  S.incomes.push(income('sber:4', 100000));
  ctx.sberTake(1, 'sber:4');
  assert.equal(deal.payinParts.length, 0);
  assert.match(events.at(-1), /операционист/);
}
{
  const {ctx, deal, S} = fixture();
  S.incomes.push(income('sber:5', 98999));
  ctx.sberTake(1, 'sber:5'); ctx.payinDone(1);
  assert.equal(deal.step, 's14m');
  assert.ok(deal.incomeReview.some(x => x.includes('Недоплата')));
}
assert.doesNotMatch(html, /Зарегистрировать тестовый приход|Создать тестовый приход|DEMO · тестовый приход|Вебхук банка · DEMO/);
assert.doesNotMatch(html, /function (?:incomeExact|incomeOff|sberManual|payinDemo)\(/);
console.log('stand incoming API: 4 сценария PASS');
