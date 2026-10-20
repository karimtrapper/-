// Отображение API и ручной сверки, выписки и старой DEMO-сделки.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const html = fs.readFileSync('static/stand/tasks.html', 'utf8');
const names = ['rubApiAccount', 'bankEvidenceCanEdit', 'bankEvidenceBlock',
  'manualBankReceiptBlock', 'docListRows'];
const source = names.map(name => {
  const match = html.match(new RegExp(`^function ${name}\\([^]*?^}`, 'm'));
  assert.ok(match, name);
  return match[0];
}).join('\n');
const file = {file: 'bank-statement.pdf', size: '1 КБ', at: '12.10', uploadedBy: 'Настя'};
const deal = {id: 1485, step: 's14', docs: {}, files: {bankCreditEvidence: [file]},
  manualBankReceipt: {status: 'pending', handoff: true}, rubReceivingAccount: {mode: 'flowsole'}};
const ctx = {S: {role: 'manager'}, standMe: 'manager',
  filesOf: (d, k) => d.files[k] || [], htmlText: String, sberText: String,
  money: String, manualBankOperatorForm: () => '<input id="mbr_amount_1485">',
  docFileOf: () => null, doctOf: () => 'Документ', docIssuedTitle: () => '',
  docExt: () => '', docFileNameHtml: String};
vm.createContext(ctx); vm.runInContext(source, ctx);

assert.equal(ctx.rubApiAccount({rubReceivingAccount: {mode: 'sber'}}), true);
assert.equal(ctx.rubApiAccount(deal), false);
assert.match(ctx.manualBankReceiptBlock(deal), /bank-statement.pdf/);
assert.doesNotMatch(ctx.manualBankReceiptBlock(deal), /mbr_amount_1485/);
assert.match(ctx.docListRows(deal).client.join(''), /Выписка \/ подтверждение зачисления/);
ctx.S.role = 'operator'; ctx.standMe = 'operator';
assert.match(ctx.manualBankReceiptBlock(deal), /mbr_amount_1485/);
assert.match(ctx.bankEvidenceBlock(deal), /Загрузить/);
deal.manualBankReceipt.status = 'confirmed';
assert.doesNotMatch(ctx.bankEvidenceBlock(deal), /Загрузить/);

deal.manualBankReceipt = null;
ctx.S.role = 'manager';
assert.doesNotMatch(ctx.manualBankReceiptBlock(deal), /manualBankReceiptRequest/);
deal.rubReceivingAccount = {mode: 'sber'};
assert.match(ctx.manualBankReceiptBlock(deal), /API Сбера/);
deal.demoTransfers = true;
assert.match(ctx.manualBankReceiptBlock(deal), /API Сбера/);
assert.doesNotMatch(html, /DEMO · тестовый приход|Вебхук банка · DEMO|Создать тестовый приход|Зарегистрировать тестовый приход/);
console.log('payin API/manual UI: PASS');
