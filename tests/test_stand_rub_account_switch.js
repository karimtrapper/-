// Переключение рублёвого счёта на копии уже сохранённой сделки.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const html = fs.readFileSync('static/stand/tasks.html', 'utf8');
const fn = name => {
  const match = html.match(new RegExp(`^function ${name}\\([^]*?^}`, 'm'));
  assert.ok(match, name);
  return match[0];
};
const constants = html.slice(html.indexOf('const MF='), html.indexOf('/* Паспорт знакомого клиента', html.indexOf('const MF=')));
const oldState = JSON.parse(JSON.stringify({deals: [{id: 1, code: 'SYN-1', step: 's11',
  rates: {client: 2.6}, rubReceivingAccount: {mode: 'flowsole'},
  docFields: {payTo: 'ООО «ЭМ ЭФ КОРПОРЕЙШН» · ПАО Сбербанк · р/с 40807810938720000286',
    purpose: 'Оплата по договору', fio: 'Ручная правка'},
  expect: {acc: '…0286 · Сбер', bank: 'ПАО Сбербанк', account: '40807810938720000286',
    amount: 100000, tol: 500, purpose: 'Назначение из выписки'}}]}));
const deal = oldState.deals[0];
const fields = {};
const ctx = vm.createContext({S: oldState, deal: () => deal,
  document: {getElementById: id => Object.hasOwn(fields, id) ? {value: fields[id]} : null},
  fake: () => ({}), approx: () => ({pay: 100000}), parsed: () => '',
  prevPassport: () => ({}), isCrypto: () => false, payinWallet: () => null,
  save: () => {}, render: () => {}});
vm.runInContext(constants + ['docFields', 'expectOf', 'rubReceivingAccountSave',
  'rubReceivingBankLabel', 'manualBankDocsMismatch'].map(fn).join('\n'), ctx);
const run = source => vm.runInContext(source, ctx);

// Старая сделка получает актуальные реквизиты без миграции JSON и потери ручных полей.
assert.match(run('docFields(S.deals[0]).payTo'), /ФЛОУ СОЛЕ КО., ЛТД.*40807810819000000261.*044525094/);
assert.equal(run('expectOf(S.deals[0]).acc'), 'Flow Sole (СГБ) …0261');
assert.equal(run('expectOf(S.deals[0]).account'), '40807810819000000261');
assert.equal(run('expectOf(S.deals[0]).bank'), 'Московский филиал "БАНК СГБ" г. Москва');
assert.equal(run('expectOf(S.deals[0]).purpose'), 'Назначение из выписки');
assert.equal(run('expectOf(S.deals[0]).amount'), 100000);
assert.equal(run('docFields(S.deals[0]).fio'), 'Ручная правка');

run("rubReceivingAccountSave(1, 'sber')");
assert.match(run('docFields(S.deals[0]).payTo'), /ЭМ ЭФ КОРПОРЕЙШН.*40807810938720000286/);
assert.equal(run('expectOf(S.deals[0]).acc'), '…0286 · Сбер');
run("rubReceivingAccountSave(1, 'flowsole')");
assert.match(deal.docFields.payTo, /ФЛОУ СОЛЕ.*40807810819000000261/);

Object.assign(fields, {rub_bank_1: 'Банк Тест', rub_account_1: '40702810900000012345',
  rub_corr_1: '30101810000000000000', rub_bik_1: '044525225',
  rub_recip_name_1: 'ООО ТЕСТ', rub_recip_inn_1: '7700000000', rub_recip_kpp_1: '770101001'});
run("rubReceivingAccountSave(1, 'custom')");
assert.match(run('docFields(S.deals[0]).payTo'), /ООО ТЕСТ.*Банк Тест.*40702810900000012345/);
assert.equal(run('expectOf(S.deals[0]).acc'), 'Банк Тест · 40702810900000012345');
assert.equal(run('expectOf(S.deals[0]).account'), '40702810900000012345');
assert.equal(run('expectOf(S.deals[0]).purpose'), 'Назначение из выписки');
assert.equal(run('docFields(S.deals[0]).fio'), 'Ручная правка');
fields.rub_bank_1 = '';
run("rubReceivingAccountSave(1, 'custom')");
assert.equal(deal.rubReceivingAccount.bank, '', 'очистка поля сохраняется');

assert.match(html, /fld\('purpose','Назначение перевода — клиент впишет его в платёжное поручение'/);
assert.doesNotMatch(html, /Назначение платежа в Сбер — клиент впишет его в перевод/);
console.log('rub account switch UI: PASS');
