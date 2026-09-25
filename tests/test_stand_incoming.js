// Проверяет фактический путь RUB-прихода в задачнике без браузера и сети.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const html = fs.readFileSync(path.join(__dirname, '../static/stand/tasks.html'), 'utf8');
const names = ['sberFree', 'payinSum', 'payinIssues', 'payinDone', 'sberTake',
  'sberManual', 'expectOf', 'expectSet', 'incomeExact', 'incomeOff'];
const source = names.map(name => {
  const found = html.match(new RegExp(`^function ${name}\\([^]*?^}`, 'm'));
  assert.ok(found, `нет функции ${name}`);
  return found[0];
}).join('\n');

function fixture(overrides = {}) {
  const deal = {id: 1, code: 'СД-1', client: 'Тест Клиент', step: 's14',
    amountRub: 100000, payinParts: [], log: [], expect: {
      amount: 100000, tol: 1000, acc: '…0286 · Сбер', purpose: 'Договор СД-1'
    }, ...overrides};
  const S = {deals: [deal], incomes: [], role: 'manager'};
  const events = [];
  const ctx = {S, deal: () => deal, incomes: () => S.incomes,
    approx: d => ({pay: d.amountRub, cur: 'rub'}), docFields: () => ({purpose: 'Договор СД-1'}),
    isCrypto: () => false, editApply: () => {}, save: () => {}, render: () => {},
    log: (d, message) => d.log.push(message), go: (d, step) => { d.step = step; },
    // после прихода — сразу конвертация, реквизиты менеджер вносит параллельно
    afterPayin: d => { d.step = 's18'; d.reqTask = 'open'; },
    toast: message => events.push(message), money: (n) => String(n),
    now: () => '24.09, 12:00', val: id => (ctx.inputs || {})[id] || '',
    need: () => false, Number, Math, String, Set};
  vm.createContext(ctx);
  vm.runInContext(source, ctx);
  return {ctx, deal, S, events};
}

{
  const {ctx, deal, S} = fixture();
  ctx.incomeExact(1);
  assert.equal(S.incomes.length, 1);
  assert.equal(S.incomes[0].demo, true);
  assert.equal(S.incomes[0].dealId, 1);
  assert.equal(deal.payinParts[0].incId, S.incomes[0].id);
  assert.equal(deal.incomeAmount, 100000);
  assert.equal(deal.step, 's18');
  assert.equal(deal.reqTask, 'open');
  ctx.sberTake(1, S.incomes[0].id);
  assert.equal(deal.payinParts.length, 1, 'повторный захват не дублирует приход');
}
{
  const {ctx, deal, S} = fixture();
  ctx.incomeOff(1);
  assert.equal(S.incomes.length, 1);
  assert.equal(S.incomes[0].rub, 98999);
  assert.equal(deal.incomeAmount, undefined, 'недоплата не принимается до причины');
  assert.equal(deal.step, 's14m');
  assert.ok(deal.incomeReview.some(x => x.includes('Недоплата')));
}
{
  const {ctx, deal, S} = fixture();
  S.incomes.push({id: 4, rub: 60000, kind: 'банк', acc: '…0286 · Сбер',
    purpose: 'Договор СД-1', dealId: null, excluded: false});
  S.incomes.push({id: 5, rub: 40000, kind: 'банк', acc: '…0286 · Сбер',
    purpose: 'Договор СД-1', dealId: null, excluded: false});
  ctx.sberTake(1, 4); ctx.sberTake(1, 5); ctx.payinDone(1);
  assert.equal(deal.step, 's18');
  assert.equal(deal.reqTask, 'open');
  assert.equal(deal.incomeAmount, 100000);
}
{
  const {ctx, deal, S} = fixture();
  S.incomes.push({id: 9, rub: 100000, kind: 'банк', acc: '…5510 · Т-Банк',
    purpose: 'Другое назначение', dealId: null, excluded: false});
  ctx.sberTake(1, 9); ctx.payinDone(1);
  assert.equal(deal.step, 's14m');
  assert.equal(deal.incomeAmount, undefined);
  assert.ok(deal.incomeReview.some(x => x.includes('Счёт')));
  assert.ok(deal.incomeReview.some(x => x.includes('Назначение')));
}
{
  const {ctx, deal, S} = fixture();
  S.incomes.push({id: 10, rub: 100000, kind: 'банк', dealId: null, excluded: false});
  ctx.sberTake(1, 10); ctx.payinDone(1);
  assert.equal(deal.step, 's14m');
  assert.ok(deal.incomeReview.some(x => x.includes('не указан')));
}
{
  const {ctx, deal, S} = fixture();
  ctx.inputs = {e_sbamt: '100000', e_sbnote: 'Другой плательщик',
    e_sbacc: '…0286 · Сбер', e_sbpurp: 'Договор СД-1'};
  ctx.sberManual(1);
  assert.equal(S.incomes[0].demo, true);
  assert.equal(S.incomes[0].acc, '…0286 · Сбер');
  assert.equal(S.incomes[0].purpose, 'Договор СД-1');
  assert.equal(deal.payinParts[0].incId, S.incomes[0].id);
  ctx.expectSet(1, 'tol', '-1');
  assert.equal(deal.expect.tol, 1000);
}
console.log('stand incoming: 6 сценариев PASS');
