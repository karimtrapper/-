// На s14 оператор выбирает API Сбера или банковскую выписку; менеджер видит статус.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync('static/stand/tasks.html', 'utf8');
assert.match(html, /s14\s*:\{n:14,who:'operator'/);
assert.match(html, /s14m:\{n:14,who:'manager'/);
assert.match(html, /Ждём деньги — сверяет операционист/);
assert.match(html, /d\.step==='s14'&&\(S\.role==='operator'\|\|S\.role==='manager'\)\?clientPayinBlock/);
const source = name => {
  const match = html.match(new RegExp('^function '+name+'\\([^]*?^}', 'm'));
  assert.ok(match, name); return match[0];
};
const ctx = {manualBankActualFields:()=>'', manualBankActualWarning:()=>'',
  S:{role:'operator'}, rubApiAccount:()=>true, bankEvidenceBlock:()=>'',
  sberText:String, money:String};
vm.createContext(ctx);
vm.runInContext(source('manualBankOperatorForm')+'\n'+source('manualBankReceiptBlock'),ctx);
const deal={id:1485,step:'s14',rubReceivingAccount:null,
  manualBankReceipt:{status:'pending',handoff:true}};
const form=ctx.manualBankOperatorForm(deal);
assert.match(form,/Flow Sole/);
assert.doesNotMatch(form,/Т-Банк|tbank|5510/);
assert.match(form,/Другой счёт/);
assert.doesNotMatch(form,/<option value="sber"|<option value="acquiring"/);
assert.match(ctx.manualBankReceiptBlock(deal),/mbr_actual_mode_1485/);
ctx.S.role='manager';
assert.doesNotMatch(ctx.manualBankReceiptBlock(deal),/mbr_actual_mode_1485/);
deal.manualBankReceipt=null;
assert.doesNotMatch(ctx.manualBankReceiptBlock(deal),/manualBankReceiptRequest\(1485\)/);
ctx.S.role='operator';
assert.match(ctx.manualBankReceiptBlock(deal),/manualBankReceiptRequest\(1485\)/);
console.log('s14 operator UI: PASS');
