// Менеджер передаёт сверку, операционист выбирает фактический счёт.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const html = fs.readFileSync('static/stand/tasks.html', 'utf8');
const fn = name => {
  const match = html.match(new RegExp(`^(?:async )?function ${name}\\([^]*?^}`, 'm'));
  assert.ok(match, name);
  return match[0];
};
const state = {deals: [{id: 1485, step: 's14', docVersion: 3,
  rubReceivingAccount: null,
  issuedDocPayTo: 'ООО «ЭМ ЭФ КОРПОРЕЙШН» · ПАО Сбербанк · р/с 40807810938720000286 · к/с 30101810400000000225 · БИК 044525225',
  docFields: {payTo: 'Сбер', purpose: 'Оплата по договору'},
  expect: {acc: '…0286 · Сбер', amount: 10000, purpose: 'Оплата по договору'},
  manualBankReceipt: null}]};
const d = state.deals[0], calls = [], elements = {
  mbr_verify_1485: {checked: true}, mbr_deviation_1485: {checked: true}
};
const values = {mbr_actual_mode_1485: 'flowsole', mbr_amount_1485: '9987.50',
  mbr_payer_1485: 'Иван Клиент', mbr_purpose_1485: 'Оплата по договору',
  mbr_date_1485: '2026-10-01', mbr_ref_1485: 'строка 7788'};
const ctx = vm.createContext({S: {...state, role: 'manager'}, deal: () => d,
  MF: {bank: 'ПАО Сбербанк', acc: '40807810938720000286', ks: '30101810400000000225', bik: '044525225'},
  FLOWSOLE: {bank: 'Московский филиал "БАНК СГБ" г. Москва', acc: '40807810819000000261',
    ks: '30101810245250000094', bik: '044525094'},
  approx: () => ({pay: 10000}), docFields: () => d.docFields,
  sberText: value => String(value || ''), money: value => String(value),
  val: id => values[id] || '', document: {getElementById: id => elements[id] || null},
  standVer: 7, standAction: async (...args) => calls.push(args), toast: () => {}, Date});
vm.runInContext(['expectOf', 'manualBankActualAccount', 'manualBankActualFields',
  'manualBankActualWarning', 'manualBankActualChange', 'manualBankOperatorForm',
  'manualBankReceiptBlock', 'manualBankReceiptRequest', 'manualBankReceiptConfirm']
  .map(fn).join('\n'), ctx);
const run = source => vm.runInContext(source, ctx);

assert.equal(run('expectOf(S.deals[0]).acc'), '…0286 · Сбер');
assert.match(run('manualBankReceiptBlock(S.deals[0])'), /Передать оператору на сверку/);
assert.doesNotMatch(run('manualBankReceiptBlock(S.deals[0])'), /Выпущенные документы содержат другие реквизиты/);
assert.match(html, /Ожидаемый счёт зачисления/);
assert.doesNotMatch(html, /id="w_acc"/);

d.manualBankReceipt = {status: 'pending', handoff: true,
  documentPayToAtRequest: d.issuedDocPayTo};
ctx.S.role = 'operator';
const operator = run('manualBankReceiptBlock(S.deals[0])');
for(const label of ['…0286 · Сбер', '…2118 · Сбер · эквайринг',
  '…5510 · Т-Банк', '…0261 · СГБ (Flow Sole)', 'Другой счёт']) assert.ok(operator.includes(label));
assert.match(run("manualBankActualWarning(S.deals[0], 'flowsole')"), /Выпущенные документы содержат другие реквизиты/);
assert.equal(run("manualBankActualWarning(S.deals[0], 'sber')"), '');
assert.match(operator, /mbr_deviation_1485/);
assert.match(run("manualBankActualFields(1485, 'custom')"), /Корреспондентский счёт/);

(async () => {
  await run('manualBankReceiptRequest(1485)');
  assert.equal(calls[0][1].handoff, true);
  await run('manualBankReceiptConfirm(1485)');
  assert.equal(calls[1][0], '/api/stand/manual-bank-receipt/1485/confirm');
  assert.equal(calls[1][1].actualMode, 'flowsole');
  assert.equal(calls[1][1].deviationAcknowledged, true);
  console.log('rub s14 role flow: PASS');
})().catch(error => {console.error(error); process.exitCode = 1;});
