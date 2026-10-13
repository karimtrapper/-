// Реальные действия вкладки «Поступления» не сохраняют галочку выбора в приход.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const snapshotMode = process.argv.includes('--snapshot');
const supplied = snapshotMode ? JSON.parse(fs.readFileSync(0, 'utf8')) : null;

const html = fs.readFileSync('static/stand/tasks.html', 'utf8');
const names = ['standSnapshot', 'incomes', 'incSel', 'incToggle',
  'convertSelected', 'convFormSave'];
const code = names.map(name => {
  const match = html.match(new RegExp(`^function ${name}\\([^]*?^}`, 'm'));
  assert.ok(match, `Нет функции ${name}`);
  return match[0];
}).join('\n');

const sampleIncome = {id: 5, source: 'manual_confirmed', dealId: 1485, rub: 9987.5,
  payer: 'Иван', date: '13.10', cnvId: null, acc: 'СГБ · 40807810819000000261'};
const sampleDeal = {id: 1485, code: 'СД-1485', rates: {}, log: []};
const state = supplied || {incomes: [sampleIncome], deals: [sampleDeal], convs: [], cseq: 0};
const income = state.incomes[0], deal = state.deals[0];
const snapshots = [];
const ctx = {S: state,
  incomeSelected: new Set(),
  STAND_SHARED: Object.keys(state),
  val: id => ({cf_rate: '100', cf_broker: 'Tradex', cf_req: '41'})[id],
  need: () => false, num: Number, now: () => '13.10',
  brokerSend: () => ({held: 69.97, sent: 9917.53, pct: .3, fix: 40,
    ctrl: 49.99, ours: 19.98, ctrlPct: .1, oursPct: .2}),
  deal: id => state.deals.find(d => d.id === id),
  log: (d, message) => { d.log = d.log || []; d.log.push({text: message}); },
  render: () => {}, toast: () => {},
  save: () => snapshots.push(JSON.parse(JSON.stringify(ctx.standSnapshot())))};
vm.createContext(ctx);
vm.runInContext(code, ctx);

ctx.incToggle(income.id);
assert.equal(snapshots.length, 0, 'Выбор прихода не сохраняется на сервере');
ctx.convertSelected();
ctx.convFormSave();
assert.equal(deal.cnvId, 1);
assert.equal(income.cnvId, 1);
assert.equal(ctx.S.convs[0].sources[0].dealId, deal.id);
assert.ok(snapshots.length >= 2);
assert.ok(snapshots.every(s => !Object.hasOwn(s.incomes[0], 'sel')),
  'UI-галочка не должна попадать ни в один PUT');
if (snapshotMode) process.stdout.write(JSON.stringify(snapshots.at(-1)));
else console.log('income conversion form: PASS');
