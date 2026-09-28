const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../static/stand/tasks.html'), 'utf8');
function source(name) {
  const match = html.match(new RegExp('^function ' + name + '\\([^]*?^}', 'm'));
  assert.ok(match, name + ' missing');
  return match[0];
}
const ctx = {
  isCrypto: () => false,
  num: value => value == null ? null : Number(value),
  crmPayload: () => ({invoice_amount_usd: 45000, transfer_fee_percent: .8,
    payin_amount_usdt: 46000, payin_rate_rub_usdt: 92,
    payout_tx_hashes: [{hash: 'confirmed', amount_usdt: 45410}],
    notes: 'original', agents: [{name: 'A', percent: 10}]}),
};
vm.createContext(ctx);
vm.runInContext(source('crmLockedKeys') + '\n' + source('crmPayloadFinal'), ctx);
const board = {type: 'Оплата недвижимости', kind: 'Фрихолд', amountUsdt: 46000,
  rates: {broker: 92},
  crmEdit: {invoice_amount_usd: 1, transfer_fee_percent: 7,
    payout_tx_hashes: [], payin_amount_usdt: 1, payin_rate_rub_usdt: 1,
    notes: 'allowed descriptive change', agents: {0: {percent: 12}}}};
const final = ctx.crmPayloadFinal(board);
assert.equal(final.invoice_amount_usd, 45000);
assert.equal(final.transfer_fee_percent, .8);
assert.equal(final.payout_tx_hashes.length, 1);
assert.equal(final.payin_amount_usdt, 46000);
assert.equal(final.payin_rate_rub_usdt, 92);
assert.equal(final.notes, 'allowed descriptive change');
assert.equal(final.agents[0].percent, 12);
const rubDerived = {type:'Обмен валюты',payType:'Наличные',incomeAmount:100000,
  rates:{broker:100,usdtThb:30},payout:{thb:3000},paySrc:'cash',
  crmEdit:{payin_amount_usdt:999,payout_amount_usdt:999,notes:'still editable'}};
ctx.crmPayload = () => ({payin_amount_usdt:996.60,payout_amount_usdt:100,
  notes:'original',agents:[]});
const derivedFinal = ctx.crmPayloadFinal(rubDerived);
assert.equal(derivedFinal.payin_amount_usdt,996.60);
assert.equal(derivedFinal.payout_amount_usdt,100);
assert.equal(derivedFinal.notes,'still editable');
console.log('T24 stale locked crmEdit ignored, descriptive/agent edit retained PASS');
