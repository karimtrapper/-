const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('static/stand/crm-draft-adapter.js', 'utf8');
const pick = name => {
  const found = source.match(new RegExp(`^(?:async )?function ${name}\\([^]*?^}`, 'm'));
  assert.ok(found, name);
  return found[0];
};
class Option {
  constructor(text, value) { this.text = text; this.value = value; this.dataset = {}; }
}
const options = [];
const manager = {
  value: '', options,
  replaceChildren(...items) { options.splice(0, options.length, ...items); },
  get selectedOptions() { return options.filter(item => item.value === this.value); },
};
const taskSource = fs.readFileSync('static/stand/tasks.html', 'utf8');
const inferred = taskSource.match(/^function standManagerIdForTransfer\(d\)\{[\s\S]*?^\}/m);
assert.ok(inferred);
let legacy = {id: 1483, manager: 'Имя до переименования', _managerDraft: {files: {
  inv: [{uploadedById: 22}], ipds: [{uploadedById: 22}], pass: [{uploadedById: 22}],
}}};
const active = {id: 1483, root: {getElementById: () => manager}, core: {}};
let saved = false;
const ctx = {Option, active, crmDraftActive: active,
  STAND_EMPLOYEES: [
    {id: 11, role: 'manager', display_name: 'Общее имя', account: 'first'},
    {id: 22, role: 'manager', display_name: 'Общее имя', account: 'second'},
    {id: 33, role: 'manager', display_name: 'Другой', account: 'disabled', login_disabled: true},
  ],
  deal: () => legacy, toast: () => {},
  crmDraftSafeFetch: async path => ({ok: true, json: async () => ({
    managers: path === '/api/managers?include_staff=1' ? [
      {name: 'Общее имя', account: 'first', user_id: 11, active: true},
      {name: 'Общее имя', account: 'second', user_id: 22, active: true},
      {name: 'Другой', account: 'disabled', user_id: 33, active: false},
    ] : [], clients: [], referrers: [],
  })})};
vm.createContext(ctx);
vm.runInContext([inferred[0], pick('crmDraftLoadLists'), pick('crmDraftManagerCommit')].join('\n'), ctx);
vm.runInContext('crmDraftLoadLists(active)', ctx).then(() => {
  assert.equal(manager.value, 'user:22', 'unique upload account resolves renamed legacy deal');
  assert.equal(options.length, 3, 'only two active account choices and placeholder');
  assert.equal(options[1].text, 'Общее имя · @first');
  assert.equal(options[2].text, 'Общее имя · @second');
  legacy = {id: 1483, manager: 'Общее имя', _managerDraft: {files: {
    inv: [{uploadedById: 11}], ipds: [{uploadedById: 22}],
  }}};
  assert.equal(vm.runInContext('standManagerIdForTransfer(deal(active.id))', ctx), null,
    'conflicting uploaders need explicit selection');
  legacy = {id: 1483, manager: 'Общее имя', _managerDraft: {files: {}}};
  assert.equal(vm.runInContext('standManagerIdForTransfer(deal(active.id))', ctx), null,
    'no uploaded account remains unresolved');
  legacy = {id: 1483, manager: 'Общее имя', managerUserId: 11,
    _managerDraft: {files: {inv: [{uploadedById: 22}]}}};
  assert.equal(vm.runInContext('standManagerIdForTransfer(deal(active.id))', ctx), 11,
    'explicit manager account wins over upload history');
  legacy = {id: 1483, manager: 'Общее имя'};
  manager.value = '';
  assert.equal(vm.runInContext('crmDraftManagerCommit(active, deal(active.id))', ctx), false);
  manager.value = 'user:22';
  saved = vm.runInContext('crmDraftManagerCommit(active, deal(active.id))', ctx);
  assert.equal(saved, true);
  assert.equal(legacy.managerUserId, 22);
  assert.equal(legacy.manager, 'Общее имя');
  const crmHtml = fs.readFileSync('static/crm/crm.html', 'utf8');
  const crmPick = name => {
    const found = crmHtml.match(new RegExp(`^        (?:async )?function ${name}\\([^]*?^        }`, 'm'));
    assert.ok(found, name); return found[0];
  };
  const crmSelect = {options: [], value: '',
    replaceChildren(...items) { this.options = items; },
    appendChild(item) { this.options.push(item); },
    get selectedOptions() { return this.options.filter(item => item.value === this.value); }};
  const crmCtx = {Option, API_URL: '',
    document: {getElementById: () => crmSelect, createElement: () => new Option('', '')},
    fetch: async () => ({json: async () => ({success: true, managers: [
      {name: 'Общее имя', account: 'first', user_id: 11, active: true},
      {name: 'Общее имя', account: 'second', user_id: 22, active: true},
    ]})}), console};
  vm.createContext(crmCtx);
  vm.runInContext(['loadManagersForSelect', 'selectedManagerIdentity', 'setManagerSelectValue']
    .map(crmPick).join('\n'), crmCtx);
  return vm.runInContext('loadManagersForSelect()', crmCtx).then(() => {
    vm.runInContext("setManagerSelectValue('Старое имя', 22)", crmCtx);
    assert.equal(crmSelect.value, 'user:22');
    assert.equal(vm.runInContext('selectedManagerIdentity().userId', crmCtx), 22);
    vm.runInContext("setManagerSelectValue('Архивный', 44)", crmCtx);
    assert.equal(crmSelect.value, 'user:44');
    assert.equal(vm.runInContext('selectedManagerIdentity().userId', crmCtx), 44);
  });
}).then(() => {
  console.log('stand draft manager account identity: PASS');
}).catch(error => { console.error(error); process.exitCode = 1; });
