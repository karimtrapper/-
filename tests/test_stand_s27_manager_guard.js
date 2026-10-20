const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const taskSource = fs.readFileSync('static/stand/tasks.html', 'utf8');
const adapterSource = fs.readFileSync('static/stand/crm-draft-adapter.js', 'utf8');
const pick = (source, name) => {
  const found = source.match(new RegExp(`^(?:async )?function ${name}\\([^]*?^}`, 'm'));
  assert.ok(found, name);
  return found[0];
};
const source = [
  pick(taskSource, 'standManagerIdForTransfer'),
  pick(taskSource, 'editOpen'),
  pick(taskSource, 'crmPushClose'),
  pick(adapterSource, 'crmDraftManagerCommit'),
].join('\n');

const card = {
  id: 9034, step: 's27', type: 'Обмен валюты', manual: false,
  sentToClient: true, pay: {invoicePaid: true}, manager: 'Старое имя',
  managerUserId: null, _managerDraft: {files: {}},
};
const toasts = [];
const requests = [];
const S = {edit: null};
const ctx = {
  STAND: true, STAND_EMPLOYEES: [
    {id: 11, role: 'manager', display_name: 'Елизавета', login_disabled: false},
    {id: 22, role: 'manager', display_name: 'Тёзка', login_disabled: false},
  ],
  S, standClosing: false, standVer: 7, standBase: null,
  deal: id => id === card.id ? card : null,
  save: () => {}, render: () => {}, toast: message => toasts.push(message),
  standClone: value => structuredClone(value), standRequireSaved: async () => true,
  crmPayloadFinal: d => ({manager_name: d.manager,
    manager_user_id: vm.runInContext('standManagerIdForTransfer(deal(9034))', ctx)}),
  crmGaps: () => [],
  fetch: async (url, options) => {
    requests.push({url, body: JSON.parse(options.body)});
    return {status: 200, json: async () => ({success: true, version: 8,
      deal: {id: 77}, data: {deals: [{id: card.id, closed: true, crmDealId: 77}]}})};
  },
  AbortController, setTimeout, clearTimeout,
  standApply: () => {}, crmFactsMismatchMessage: () => null,
};
vm.createContext(ctx);
vm.runInContext(source, ctx);

(async () => {
  await vm.runInContext('crmPushClose(9034, 7)', ctx);
  assert.equal(requests.length, 0, 'missing uploader must not submit CRM close');
  assert.equal(S.edit, card.id, 'missing identity opens the existing editor');
  assert.match(toasts.at(-1), /Выберите учётную запись менеджера задачника/);

  S.edit = null;
  card._managerDraft.files = {inv: [{uploadedById: 11}],
    ipds: [{uploadedById: 22}]};
  await vm.runInContext('crmPushClose(9034, 7)', ctx);
  assert.equal(requests.length, 0, 'conflicting uploaders must not submit CRM close');
  assert.equal(S.edit, card.id, 'conflicting identity opens the editor');

  const active = {root: {getElementById: id => id === 'managerSelect'
    ? {selectedOptions: [{dataset: {userId: '22', name: 'Тёзка'}}]} : null}};
  ctx.active = active;
  assert.equal(vm.runInContext('crmDraftManagerCommit(active, deal(9034))', ctx), true);
  assert.equal(card.managerUserId, 22);
  assert.equal(card.manager, 'Тёзка');
  await vm.runInContext('crmPushClose(9034, 7)', ctx);
  assert.equal(requests.length, 1, 'explicit choice allows ordinary s27 close');
  assert.equal(requests[0].url, '/api/stand/deals/9034/crm-close');
  assert.equal(requests[0].body.crm.manager_user_id, 22);
  assert.equal(requests[0].body.crm.manager_name, 'Тёзка');
  console.log('s27 manager account guard: missing/conflicting/explicit choice PASS');
})().catch(error => {console.error(error); process.exitCode = 1;});
