const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../static/stand/tasks.html'), 'utf8');
function source(name) {
  const start = html.indexOf('\nfunction '+name+'(')+1;
  assert.ok(start);
  const end = html.indexOf('\n}', start);
  const lineEnd = html.indexOf('\n', start);
  return html.slice(start, html[lineEnd-1]==='}' ? lineEnd : html.indexOf('\n', end+1));
}

const deals = [
  {id: 201, code: 'ArchivedTask', step: 's18w', isTask: true, taskArchived: true, cnvId: 8},
  {id: 202, code: 'VisibleTask', step: 's18w', isTask: true},
  {id: 203, code: 'ArchivedReady', step: 'ready', taskArchived: true, manualNew: true},
  {id: 204, code: 'VisibleReady', step: 'ready'},
  {id: 205, code: 'VisibleDeal', step: 'done', closed: true},
];
const notes = [{id: 'archived', dealId: '201', role: 'operator'},
  {id: 'active', dealId: 202, role: 'operator'}, {id: 'general', role: 'operator'}];
const context = vm.createContext({
  S: {deals, notes, role: 'operator', convs: [{id: 8, status: 'sent'}]},
  STAND_SHARED: ['deals','convs','notes'], STEPS: {s18w: {}}, ROLES: {operator: {n: 'Operator'}},
  usd: String, money: String, plural: () => '', exSum: () => 0, exMargin: () => 0, since: () => '',
  STAND: true, canSwitchRole: () => false, standLoadError: false, taskListSection: null,
  URLSearchParams, location: {search: '?deal=201', pathname: '/tasks'},
  history: {replaceState() {}}, render() {},
  stepWho: d => d.step==='s18w'?'operator':null,
  taskBranchesForRole: (d, role) => d.step==='s18w'&&role==='operator'?[null]:[],
  isCrypto: () => false, hasPolicy: () => false, dealWallet: () => null,
  approx: () => ({}), apMoney: () => 'Amount', refs: () => [], econ: () => ({}),
  htmlText: String, stepTitle: () => 'Step', dealDisplayKind: () => 'Flow',
  dealTaskPath: () => ({index: 0, steps: [1]}), policyStepAssignee: () => 'Operator',
  taskListEntries: [{id: 202}, {id: 201}, {id: 204}], taskListCursor: 0,
  taskDealFilter: 'all',
});
vm.runInContext(['standSnapshot', 'deal', 'notes', 'notesFor', 'notesUnread', 'myTasks',
  'myTaskCount', 'waitingOn', 'pendingEx', 'taskDealsHtml', 'viewDeals',
  'dealStatusLabel', 'dealProfit', 'nextTaskIndex', 'viewTasks', 'standOpenFromLink'].map(source).join('\n'), context);

assert.deepEqual(Array.from(context.myTasks('operator'), d => d.id), [202]);
assert.equal(context.myTaskCount('operator'), 1);
assert.deepEqual(Array.from(context.waitingOn('manager'), d => d.id), [202]);
assert.deepEqual(Array.from(context.pendingEx(null), d => d.id), [204]);
assert.deepEqual(Array.from(context.notesFor('operator'), n => n.id), ['active', 'general']);
assert.equal(context.notesUnread('operator'), 2);
assert.equal(context.nextTaskIndex(), 2);
assert.match(context.taskDealsHtml('operator'), /VisibleTask/);
assert.doesNotMatch(context.taskDealsHtml('operator'), /Archived/);
assert.match(context.viewDeals(), /VisibleDeal/);
assert.match(context.viewDeals(), /2 из 3/);
assert.doesNotMatch(context.viewDeals(), /Archived/);
for (const role of ['admin', 'operator', 'manager']) {
  context.S.role = role;
  const board = context.viewTasks();
  assert.match(board, /VisibleTask/);
  assert.doesNotMatch(board, /Archived/);
  assert.match(board, /task-list-count mine">1<\/span>|task-list-count">1<\/span>/);
}
context.standOpenFromLink();
assert.equal(context.S.open, undefined);
assert.equal(context.deal(201).cnvId, 8);
for (const key of ['deals','notes','convs'])
  assert.equal(JSON.stringify(context.standSnapshot()[key]), JSON.stringify(context.S[key]));
