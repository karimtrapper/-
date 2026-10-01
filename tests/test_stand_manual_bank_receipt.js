// Manual RUB receipt UI: request is explicit, demo remains labeled, operator
// confirmation is role-gated in the view and records the current server version.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const html = fs.readFileSync('static/stand/tasks.html', 'utf8');
const issuesStart = html.indexOf('function payinSum(d){');
const issuesEnd = html.indexOf('function payinPool(d){', issuesStart);
assert.ok(issuesStart >= 0 && issuesEnd > issuesStart);
const linkedDeal = {id: 8, incomeAmount: 9987.5,
  expect: {amount: 9987.5, tol: 1000, acc: 'custom', bank: 'Test Bank',
    account: '40702810900000012345', purpose: 'Оплата по договору'},
  manualBankReceipt: {id: 'receipt-1', status: 'confirmed', bank: 'Test Bank',
    account: '40702810900000012345', actualAmount: 9987.5,
    confirmedAt: '2026-10-01T10:00:00Z', confirmedBy: 4},
  payinParts: [{incId: 5, amountRub: 9987.5}]};
const linkedIncome = {id: 5, dealId: 8, rub: 9987.5, source: 'manual_confirmed',
  manualReceiptId: 'receipt-1', acc: 'Test Bank · 40702810900000012345',
  purpose: 'Оплата по договору'};
const issueCtx = vm.createContext({expectOf: d => d.expect, incomes: () => [linkedIncome]});
vm.runInContext(html.slice(issuesStart, issuesEnd), issueCtx);
assert.deepEqual(Array.from(vm.runInContext('payinIssues(' + JSON.stringify(linkedDeal) + ')', issueCtx)), []);

const start = html.indexOf('function manualBankReceiptBlock(d){');
const end = html.indexOf('/* Крипто-приход частями', start);
assert.ok(start >= 0 && end > start);
const deal = {id: 77, step: 's14', docVersion: 1,
  docFields: {payTo: 'Старый банк · р/с 40702'},
  manualBankReceipt: {id: 'r1', status: 'pending', bank: 'Новый банк',
    account: '40702810900000012345', actualAmount: 1050, payer: 'Клиент',
    statementDate: '2026-10-01', statementRef: 'оп. 8'}};
const elements = {mbr_verify_77: {checked: false}, mbr_docs_77: {checked: true}};
const values = {mbr_bank_77: 'Новый банк', mbr_account_77: '40702810900000012345',
  mbr_amount_77: '1 050,00', mbr_payer_77: 'Клиент', mbr_date_77: '2026-10-01',
  mbr_ref_77: 'операция 8'};
const calls = [];
const ctx = vm.createContext({S: {role: 'operator'}, deal: id => id === 77 ? deal : null,
  sberText: String, money: n => String(n), docFields: d => d.docFields,
  val: id => values[id], document: {getElementById: id => elements[id]},
  standAction: async (...args) => { calls.push(args); return {success: true}; },
  standVer: 12, toast: msg => calls.push(['toast', msg]), Date});
vm.runInContext(html.slice(start, end), ctx);
const run = code => vm.runInContext(code, ctx);

const card = run('manualBankReceiptBlock(S.deals ? S.deals[0] : ' + JSON.stringify(deal) + ')');
assert.match(card, /Ожидает сверки оператором/);
assert.match(card, /Сверил фактическое зачисление/);
assert.match(card, /не подтверждение Сбер API/);
assert.match(html, /Другой счёт/);
assert.match(html, /Корреспондентский счёт \(20 цифр\)/);
assert.match(html, /БИК банка \(9 цифр\)/);
assert.match(html, /d\.manualBankReceipt\?\.status==='pending'/);
assert.match(html, /d\.manualBankReceipt\?'':`<div class="sim"><div class="h">Вебхук банка · DEMO/);
assert.match(html, /Вебхук банка · DEMO/);

const fieldsStart = html.indexOf('function docFields(d){');
const fieldsEnd = html.indexOf('/* ФИО по паспорту', fieldsStart);
assert.ok(fieldsStart >= 0 && fieldsEnd > fieldsStart);
const fieldCtx = vm.createContext({fake:()=>({}), approx:()=>({pay:10000,thb:1000}),
  parsed:()=>'', isCrypto:()=>false, payinWallet:()=>null, prevPassport:()=>({}),
  MF:{rubName:'MF Corp',inn:'9909726886',kpp:'770387001',bank:'Sber',acc:'4080',ks:'3010',bik:'0445'},
  htmlText:String});
vm.runInContext(html.slice(fieldsStart, fieldsEnd), fieldCtx);
const customFields=vm.runInContext(`docFields({id:1,code:'X',rates:{client:10},rubReceivingAccount:{mode:'custom',bank:'Test Bank',account:'40702810900000012345',correspondent:'30101810000000000000',bik:'044525225'}})`,fieldCtx);
assert.match(customFields.payTo,/Test Bank · р\/с 40702810900000012345 · к\/с 30101810000000000000 · БИК 044525225/);

run('manualBankReceiptConfirm(77)');
assert.match(calls.at(-1)[1], /Сначала сверьте/);
elements.mbr_verify_77.checked = true;
run('manualBankReceiptConfirm(77)');
assert.equal(calls.at(-1)[0], '/api/stand/manual-bank-receipt/77/confirm');
assert.equal(calls.at(-1)[1].version, 12);
assert.equal(calls.at(-1)[1].statementVerified, true);

console.log('manual bank receipt UI tests: PASS');
