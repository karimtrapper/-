// Чек, принятый завершением s26: «проверено · операционист <имя> · <дата s26>», без кнопки.
const assert=require('node:assert/strict'), fs=require('node:fs'), vm=require('node:vm');
const html=fs.readFileSync('static/stand/tasks.html','utf8');
function source(name){const m=html.match(new RegExp('^function '+name+'\\([^]*?^}','m'));assert.ok(m,name);return m[0];}
const ctx={S:{role:'operator'},htmlText:s=>String(s).replace(/</g,'&lt;'),standVer:5,CRM_CLOSE_STATUS:new Map()};
vm.createContext(ctx);
for(const name of ['crmCloseReason','crmCloseBlockers','crmEvidenceParts'])vm.runInContext(source(name),ctx);
const d={id:1483,type:'Оплата недвижимости',transfer:{sends:[]}};
const at='2026-10-19T05:49:42Z';
const receipt={kind:'receipt',ready:true,system:true,implicit:true,confirmed_by:'Артём',confirmed_role:'operator',checked_at:at};
const facts=r=>({version:5,facts:[{kind:'payin',ready:true,system:true},{kind:'payout',ready:true,system:true},r,{kind:'sent',ready:true}]});

// Принят: имя и полная дата-время s26, кнопки нет ни у одной роли.
ctx.crmCloseStatus=()=>facts(receipt);
for(const role of ['operator','admin','manager']){
 ctx.S.role=role;const out=ctx.crmEvidenceParts(d).receiptBtn;
 assert.ok(out.includes('проверено · операционист Артём · '+new Date(at).toLocaleString('ru-RU')),out);
 assert.doesNotMatch(out,/<button|crmEvidence|Подтвердить/,role);
}
// Без имени в журнале — «операционист» без выдумки.
ctx.crmCloseStatus=()=>facts({...receipt,confirmed_by:null});
assert.ok(ctx.crmEvidenceParts(d).receiptBtn.includes('проверено · операционист · '));
// Имя экранируется.
ctx.crmCloseStatus=()=>facts({...receipt,confirmed_by:'<b>x</b>'});
assert.doesNotMatch(ctx.crmEvidenceParts(d).receiptBtn,/<b>x/);

// Не принят: понятная причина и никакой кнопки «Подтвердить».
for(const reason of ['operator_receipt_acceptance_missing','invoice_payment_or_receipt_missing']){
 ctx.crmCloseStatus=()=>facts({kind:'receipt',ready:false,reason});
 for(const role of ['operator','admin','manager']){
  ctx.S.role=role;const out=ctx.crmEvidenceParts(d).receiptBtn;
  assert.doesNotMatch(out,/<button|crmEvidence|Подтвердить/,reason+' '+role);
 }
}
assert.equal(ctx.crmCloseReason({kind:'receipt',reason:'operator_receipt_acceptance_missing'}),'Операционист должен завершить шаг «Оплатить инвойс» с чеком');
assert.equal(ctx.crmCloseReason({kind:'receipt',reason:'invoice_payment_or_receipt_missing'}),'Не хватает чека или завершённой оплаты инвойса');
// Ручные факты (приход/выдача) сохраняют кнопку оператора.
ctx.crmCloseStatus=()=>({version:5,facts:[{kind:'payin',ready:false,reason:'operator_confirmation_missing'},{kind:'payout',ready:true},{kind:'receipt',ready:true,implicit:true,checked_at:at},{kind:'sent',ready:true}]});
ctx.S.role='operator';assert.match(ctx.crmEvidenceParts(d).payinBtn,/crmEvidence\(1483,'payin'\)/);
console.log('s26 implicit receipt rendering OK');
