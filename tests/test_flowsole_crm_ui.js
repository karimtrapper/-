// Flow Sole CRM keeps the bank account hint and old receipt visible.
// New entries use RUB + USDT and derive a read-only rate.
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
  if (!elements.has(id)) elements.set(id, {style: {}, dataset: {}, value: '', files: [], innerHTML: '', textContent: '',
    replaceChildren() {}, append() {}});
  return elements.get(id);
};
el('createDealForm').payin_rate_rub_usdt = {readOnly: false};
const calls = [];
const ctx = {document: {getElementById: el, createElement: () => ({style: {}, append() {}, setAttribute() {}}),
    createTextNode: text => ({text})}, Date,
  editingDealId: null, flowExistingReceipt: false, flowExistingParts: [],
  payinMode: 'rate', customUsdtMode: {payin: 'rate', payout: 'rate'},
  payoutRegistryWallets: [],
  sberSetKindFilter: (...args) => calls.push(['kind', ...args]),
  sberLoadIncomes: () => calls.push(['load']),
  loadCustomWlTransactions: () => calls.push(['wl']),
  loadCustomCryptoTransactions: () => calls.push(['crypto']),
  autoCalcUsdt: () => calls.push(['calc']),
  calcCustomProfit: () => calls.push(['custom-calc']),
  escapeHtml: x => String(x)};
vm.createContext(ctx);
vm.runInContext(['methodUsesSberPool', 'flowShow',
  'crmWalletLimitText', 'walletPolicyText', 'renderCrmWalletPolicy', 'renderCrmWalletAddress',
  'refreshPayinWalletPolicy', 'applyPayinMethodFields', 'onCustomPayinMethodChange',
  'selectCustomPayinTx'].map(fn).join('\n'), ctx);

el('payinMethod').value = 'flow_sole_reqs';
vm.runInContext('applyPayinMethodFields()', ctx);
assert.equal(el('flowManualGroup').style.display, 'none');
assert.equal(el('flowAccountHint').style.display, 'block');
assert.equal(el('flowPayinProof').textContent, 'Не подтверждено в сети');
assert.equal(el('sberReqsGroup').style.display, 'none');
assert.equal(el('createDealForm').payin_rate_rub_usdt.readOnly, true);
assert.equal(ctx.payinMode, 'usdt');
assert.deepEqual(calls, [['calc']]);

el('customPayinMethod').value = 'flow_sole_reqs';
vm.runInContext('onCustomPayinMethodChange()', ctx).then(() => {
  assert.equal(el('flowManualGroupC').style.display, 'none');
  assert.equal(el('flowAccountHintC').style.display, 'block');
  assert.equal(el('sberReqsGroupC').style.display, 'none');
  assert.equal(el('customPayinPicker').style.display, 'flex');
  assert.equal(el('customPayinCurrency').value, 'RUB');
  assert.equal(el('customPayinRate').readOnly, true);
  assert.equal(ctx.customUsdtMode.payin, 'usdt');
  assert.deepEqual(calls, [['calc'], ['custom-calc'], ['crypto']]);
  el('customPayinAmount').value = '10000';
  vm.runInContext("selectCustomPayinTx({value: JSON.stringify({kind:'crypto',amount_usdt:100,tx_hash:'verified-hash'})})", ctx);
  assert.equal(el('customPayinCurrency').value, 'RUB');
  assert.equal(el('customPayinAmount').value, '10000');
  assert.equal(el('customPayinUsdt').value, '100.00');
  assert.equal(el('customPayinTxHash').value, 'verified-hash');
  el('customPayinUsdt').value = '700';
  el('customPayinUsdt').dataset.flowDraftTyped = '1';
  vm.runInContext("selectCustomPayinTx({value: JSON.stringify({kind:'crypto',amount_usdt:250,tx_hash:'second-hash'})})", ctx);
  assert.equal(el('customPayinUsdt').value, '700', 'picked hash must keep manually entered draft USDT');
  assert.doesNotMatch(html, /id="flow(?:Amount|Date|File)"/);
  assert.match(html, /id="payinRubHint"[^>]*>после комиссии банка/);
  vm.runInContext("flowExistingReceipt = true; flowExistingParts = [{amount_rub: 10000, date: '2026-10-19'}, {amount_rub: 20000, date: '2026-10-20'}]; editingDealId = 42; flowShow('', true)", ctx);
  assert.match(el('flowManualGroup').innerHTML, /10\s000,00 ₽/);
  assert.match(el('flowManualGroup').innerHTML, /20\s000,00 ₽/);
  assert.match(el('flowManualGroup').innerHTML, /2026-10-19/);
  assert.match(el('flowManualGroup').innerHTML, /manual-rub-income\/statement/);
  el('payinMethod').value = 'sber_reqs';
  vm.runInContext('applyPayinMethodFields()', ctx);
  assert.equal(el('sberReqsGroup').style.display, 'block');
  assert.equal(el('flowManualGroup').style.display, 'none');
  assert.equal(el('createDealForm').payin_rate_rub_usdt.readOnly, false);
  assert.deepEqual(calls.slice(-2), [['kind', 'transfer'], ['load']]);
  console.log('Flow Sole CRM UI: PASS');
}).catch(error => { console.error(error); process.exitCode = 1; });
