// Both ordinary CRM deal forms select Flow Sole without opening Sber's API pool.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const html = fs.readFileSync('static/crm/crm.html', 'utf8');
const fn = name => {
  const match = html.match(new RegExp(`^        (?:async )?function ${name}\\([^]*?^        }`, 'm'));
  assert.ok(match, `missing ${name}`);
  return match[0];
};
const elements = new Map();
const el = id => {
  if (!elements.has(id)) elements.set(id, {style: {}, value: '', files: [], innerHTML: '', textContent: '',
    replaceChildren() {}, append() {}});
  return elements.get(id);
};
const calls = [];
const ctx = {document: {getElementById: el, createElement: () => ({style: {}, append() {}, setAttribute() {}})}, Date,
  editingDealId: null, payoutRegistryWallets: [],
  sberSetKindFilter: (...args) => calls.push(['kind', ...args]),
  sberLoadIncomes: () => calls.push(['load']),
  loadCustomWlTransactions: () => calls.push(['wl']),
  loadCustomCryptoTransactions: () => calls.push(['crypto'])};
vm.createContext(ctx);
vm.runInContext(['methodUsesSberPool', 'flowToday', 'flowShow',
  'walletPolicyText', 'renderCrmWalletAddress', 'refreshPayinWalletPolicy', 'applyPayinMethodFields', 'onCustomPayinMethodChange'].map(fn).join('\n'), ctx);

el('payinMethod').value = 'flow_sole_reqs';
vm.runInContext('applyPayinMethodFields()', ctx);
assert.equal(el('flowManualGroup').style.display, 'block');
assert.equal(el('sberReqsGroup').style.display, 'none');
assert.match(el('flowDate').value, /^\d{4}-\d\d-\d\d$/);
assert.deepEqual(calls, []);
el('customPayinMethod').value = 'flow_sole_reqs';
vm.runInContext('onCustomPayinMethodChange()', ctx).then(() => {
  assert.equal(el('flowManualGroupC').style.display, 'block');
  assert.equal(el('sberReqsGroupC').style.display, 'none');
  assert.equal(el('customPayinPicker').style.display, 'none');
  assert.deepEqual(calls, []);
  assert.match(html, /id="flowAmount"[^>]*type="number"/);
  assert.match(html, /id="flowFile"[^>]*type="file"/);
  assert.doesNotMatch(html.match(/<div id="flowManualGroup"[^]*?<\/div>\s*<div class="form-row">/)[0], /Плательщик|Номер строки|Сверила/);
  el('payinMethod').value = 'sber_reqs';
  vm.runInContext('applyPayinMethodFields()', ctx);
  assert.equal(el('sberReqsGroup').style.display, 'block');
  assert.equal(el('flowManualGroup').style.display, 'none');
  assert.deepEqual(calls, [['kind', 'transfer'], ['load']]);
  console.log('Flow Sole CRM UI: PASS');
}).catch(error => { console.error(error); process.exitCode = 1; });
