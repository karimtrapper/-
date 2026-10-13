// Кнопка подтверждения отправляет сверку серверу; шаг меняется только ответом сервера.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const html = fs.readFileSync('static/stand/tasks.html', 'utf8');
const match = html.match(/^async function manualBankReceiptConfirm\([^]*?^}/m);
assert.ok(match, 'Нет обработчика подтверждения ручного прихода');
const deal = {id: 1485, step: 's14', manualBankReceipt: {handoff: true}};
const calls = [];
const ctx = {
  document: {getElementById: id => ({checked: id === 'mbr_verify_1485'})},
  deal: id => id === 1485 ? deal : null,
  filesOf: () => [{file: 'statement.pdf'}],
  val: id => ({mbr_actual_mode_1485: 'flowsole', mbr_amount_1485: '9987.50',
    mbr_payer_1485: 'Иван Клиент', mbr_purpose_1485: 'Оплата по договору',
    mbr_date_1485: '2026-10-01', mbr_ref_1485: 'строка 7788'})[id] || '',
  standVer: 8, toast: () => { throw Error('Неожиданная ошибка формы'); },
  standAction: async (path, body) => {
    assert.equal(deal.step, 's14', 'Клиент сдвинул шаг до ответа сервера');
    calls.push({path, body});
    deal.step = 's18';
    return {success: true};
  },
};
vm.createContext(ctx);
vm.runInContext(match[0], ctx);
ctx.manualBankReceiptConfirm(1485).then(() => {
  assert.equal(calls.length, 1);
  assert.equal(calls[0].path, '/api/stand/manual-bank-receipt/1485/confirm');
  assert.equal(calls[0].body.actualMode, 'flowsole');
  assert.equal(calls[0].body.statementVerified, true);
  assert.equal(deal.step, 's18');
  console.log('manual receipt confirm UI: PASS');
}).catch(error => { console.error(error); process.exitCode = 1; });
