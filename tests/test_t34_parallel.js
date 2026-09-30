const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../static/stand/tasks.html'), 'utf8');
function source(names) {
  return names.map(name => {
    const match = html.match(new RegExp(`^function ${name}\\([^]*?^}`, 'm'));
    assert.ok(match, name);
    return match[0];
  }).join('\n');
}
function run(names, context) {
  vm.createContext(context);
  vm.runInContext(source(names), context);
  return context;
}

// An early click saves only the manager's private draft. It does not open a
// task, notify anyone, publish payTo, or advance the operator's step.
{
  const d = {id: 34, step: 's5', pay: {}, log: [], reqTask: null};
  let saves = 0, notifications = 0, advances = 0;
  const ctx = run(['reqSave', 'reqOpen', 'managerDraft'], {
    d, deal: () => d, S: {open: 34},
    payToFromForm: () => ({dev: 'Early Dev', acc: 'PRIVATE_ACCOUNT'}),
    draftsClear: () => {}, save: () => saves++, render: () => {}, toast: () => {},
    noteAdd: () => notifications++, go: () => advances++,
  });
  ctx.reqSave(34);
  assert.equal(d.step, 's5');
  assert.equal(d.reqTask, null);
  assert.equal(d.payTo, undefined);
  assert.equal(d._managerDraft.payTo.acc, 'PRIVATE_ACCOUNT');
  assert.equal(saves, 1);
  assert.equal(notifications, 0);
  assert.equal(advances, 0);
}

// The existing post-payin manager task needs one explicit click. Only that
// click publishes payTo and sends the operator's ordinary notification.
{
  const d = {id: 34, step: 's22', pay: {}, log: [], reqTask: 'open',
    _managerDraft: {payTo: {acc: 'PRIVATE_ACCOUNT'}}};
  let saves = 0, notifications = 0, advances = 0;
  const ctx = run(['reqSave', 'reqOpen'], {
    d, deal: () => d, S: {open: 34},
    payToRequired: () => ({}), need: () => false,
    payToFromForm: () => ({dev: 'Developer', bank: 'Bank', acc: '123',
      purpose: 'INV-1', amount: 100}),
    saveNote: () => {}, draftsClear: () => {}, log: (x, value) => x.log.push(value),
    payToLogLine: () => 'Developer', stepWho: () => 'operator',
    noteAdd: () => notifications++, go: () => advances++,
    save: () => saves++, render: () => {}, toast: () => {},
  });
  ctx.reqSave(34);
  assert.equal(d.step, 's22');
  assert.equal(d.reqTask, 'done');
  assert.equal(d.payTo.acc, '123');
  assert.equal(d._managerDraft.payTo, undefined);
  assert.equal(notifications, 1);
  assert.equal(saves, 1);
  assert.equal(advances, 0);
}

// Client uploads and comment remain in the draft until manager confirms s8.
{
  const d = {id: 34, step: 's5', docs: {}, files: {}, docMeta: {}};
  const ctx = run(['managerDraft', 'managerDraftDocTarget', 'filesOf', 'fileSync',
                   'managerDraftPublishDocs'], {
    d, S: {role: 'manager'}, MANAGER_DRAFT_DOCS: ['pass', 'inv', 'spa', 'ipds'],
    fileValid: () => true,
  });
  ctx.filesOf(d, 'pass').push({file: 'PRIVATE_PASS.pdf'});
  ctx.fileSync(d, 'pass');
  d._managerDraft.comment = 'PRIVATE_COMMENT';
  assert.equal(d.docs.pass, undefined);
  assert.equal(d.files.pass, undefined);
  assert.equal(d._managerDraft.docs.pass, true);
  d.step = 's8';
  assert.equal(ctx.filesOf(d, 'pass')[0].file, 'PRIVATE_PASS.pdf');
  ctx.managerDraftPublishDocs(d);
  assert.equal(d.files.pass[0].file, 'PRIVATE_PASS.pdf');
  assert.equal(d.docs.pass, true);
  assert.equal(d.docComment, 'PRIVATE_COMMENT');
  assert.equal(d._managerDraft.files, undefined);
}

// When another role owns the step, the task tab leads with the real owner.
// A role without parallel work sees only that status; manager sees own forms.
{
  const d = {id: 34, code: 'СД-34', client: 'Synthetic', source: 'test',
    type: 'Оплата недвижимости', kind: 'Лизхолд', step: 's11',
    docs: {}, log: [], pay: {}, closed: false};
  const S = {role: 'manager', view: 'task'};
  const ctx = run(['viewDeal'], {
    S, STEPS: {s11: {title: 'Подготовить договор', n: 11, who: 'operator'}},
    ROLES: {manager: {t: 'Менеджер'}, operator: {t: 'Операционист'}},
    SOURCES: {test: 'Тест'}, stepWho: () => 'operator',
    stepTitle: () => 'Подготовить договор', progress: () => ({i: 4, n: 12}),
    stepCard: () => 'REQ_FORM', managerEarlyDocsBlock: () => 'DOC_FORM',
    docSide: () => '', pathCard: () => '', overview: () => '', quotesCard: () => '',
  });
  const manager = ctx.viewDeal(d);
  assert.match(manager, /Сейчас: Операционист — Подготовить договор/);
  assert.match(manager, /Ваши задачи по этой сделке — можно заполнить заранее/);
  assert.match(manager, /REQ_FORM/);
  S.role = 'operator';
  ctx.stepWho = () => 'manager';
  const operator = ctx.viewDeal(d);
  assert.match(operator, /Сейчас: Менеджер — Подготовить договор/);
  assert.doesNotMatch(operator, /Ваши задачи по этой сделке|Переключите роль/);
}

// IPPS application cannot be marked sent with an incomplete manager handoff.
{
  const ctx = run(['payToReady'], {});
  const d = {kind: 'Фрихолд', ippsTariff: 'bank', payTo: {dev: 'Developer',
    bank: 'Bank', acc: '123', purpose: 'INV-1'}};
  assert.equal(ctx.payToReady(d), false);
  d.payTo.swift = 'TESTTHBK';
  assert.equal(ctx.payToReady(d), true);
  d.ippsTariff = 'soft';
  assert.equal(ctx.payToReady(d), false);
  d.payTo.pobo = 'TEST CLIENT';
  assert.equal(ctx.payToReady(d), true);
}

console.log('test_t34_parallel.js: OK');
