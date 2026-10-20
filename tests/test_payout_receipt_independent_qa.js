// Независимая QA: чек выплаты (слот «Чек» и «+ Загрузить ещё» с типом «чек»), не-крипто выплата, атрибуция.
const assert=require('node:assert/strict'), fs=require('node:fs'), vm=require('node:vm');
const html=fs.readFileSync('static/stand/tasks.html','utf8');
function source(name){const m=html.match(new RegExp('^function '+name+'\\([^]*?^}','m'));assert.ok(m,name);return m[0];}
function constSource(name){const m=html.match(new RegExp('^const '+name+'=.*?;','ms'));assert.ok(m,name);return m[0];}
const PDF=(n)=>({file:n,mime:'application/pdf',data:'data:application/pdf;base64,JVBERi0xLjQK',bytes:100});
const ctx={S:{role:'manager',deals:[],manualCloseForm:{}},htmlText:s=>String(s).replace(/</g,'&lt;'),standVer:5,
  CRM_CLOSE_STATUS:new Map(),MANAGER_DRAFT_DOCS:['pass','inv','spa','ipds'],managerDraft:()=>({}),
  crmPayloadFinal:()=>({deal_kind:'mf_realty'}),brokerSend:()=>0,BROKER_FEE:{},SOURCES_PAY:{},document:{getElementById:()=>null},Number,Math,atob};
vm.createContext(ctx);
for(const n of ['managerDraftDocTarget','fileValid','filesOf','receiptDocs','hasReceipt','mfList','noncryptoPayout','num',
  'crmCloseReason','crmCloseBlockers','crmEvidenceParts','val','isCrypto','payCur','hashSum','payinParts','clientRubPaid',
  'payoutHuman','manualCloseFormState','manualCloseMerge','manualClosePayload'])
  try{vm.runInContext(source(n),ctx);}catch(e){console.log('skip dep',n,e.message);}
const base=()=>({id:1489,type:'Оплата недвижимости',kind:'Аренда',amountThb:455000,docs:{},files:{},mfPayout:[],
  payTo:{bank:'BBL',acc:'123'},transfer:{sends:[]},payinHashes:[],payout:{}});

// 1. receipt в обоих путях загрузки + docs.receipt синхронизируется без перезагрузки
let d=base(); assert.equal(ctx.hasReceipt(d),false);
d.files.additional=[{...PDF('slip.pdf'),documentType:'receipt'}];
assert.equal(ctx.hasReceipt(d),true,'additional/receipt'); ctx.receiptDocs(d); assert.equal(d.docs.receipt,true,'docs.receipt синхронизирован через filesOf');
assert.equal(JSON.stringify(ctx.receiptDocs(d).map(x=>[x.kind,x.i])),'[["additional",0]]');
d=base(); d.files.receipt=[PDF('slip.pdf')]; d.files.additional=[{...PDF('o.pdf'),documentType:'receipt'}];
assert.equal(JSON.stringify(ctx.receiptDocs(d).map(x=>[x.kind,x.i])),'[["receipt",0],["additional",0]]','индексы для docOpen');
d=base(); d.files.additional=[{...PDF('o.pdf'),documentType:'other'}]; assert.equal(ctx.hasReceipt(d),false,'другой тип не чек');
d=base(); d.files.additional=[{file:'x.exe',mime:'application/x-msdownload',data:'data:x;base64,AA==',documentType:'receipt'}];
assert.equal(ctx.hasReceipt(d),false,'невалидный файл');
d=base(); d.files.additional=[{file:'x.pdf',documentType:'receipt'}]; assert.equal(ctx.hasReceipt(d),false,'без байтов');
d=base(); d.docs.receipt=true; assert.equal(ctx.hasReceipt(d),false,'булев docs.receipt не чек');

// 2. noncryptoPayout: зеркало backend
assert.equal(ctx.noncryptoPayout(base()),true);
for(const p of [{postConv:'coins'},{postConv:'ipps_swift'},{postConv:'client'},{paySrc:'coins'},{paySrc:'client'},
  {transfer:{sends:[{hash:'x'}]}},{kind:'Фрихолд'},{mfPayout:[{hash:'a'}]},{amountThb:0},{payTo:{bank:'BBL'}},{payTo:{acc:'1'}},{type:'Обмен валюты'}])
  assert.equal(ctx.noncryptoPayout({...base(),...p}),false,JSON.stringify(p));

// 3. Атрибуция «чек приложен · автор · дата»
const at='2026-10-20T08:00:00Z', dd={id:1,type:'Оплата недвижимости',transfer:{sends:[]}};
ctx.S.role='operator';
ctx.crmCloseStatus=()=>({version:5,facts:[{kind:'payin',ready:true,system:true},
  {kind:'payout',ready:true,system:true,implicit:true,confirmed_by:'Лиза',confirmed_role:'manager',checked_at:at},
  {kind:'receipt',ready:true,system:true,implicit:true,confirmed_by:'Лиза',confirmed_role:'manager',checked_at:at},
  {kind:'sent',ready:true}]});
const ev=ctx.crmEvidenceParts(dd), stamp=new Date(at).toLocaleString('ru-RU');
for(const k of ['payoutBtn','receiptBtn']){
  assert.ok(ev[k].includes('чек приложен · Лиза · '+stamp),ev[k]); assert.doesNotMatch(ev[k],/<button|Подтвердить/);}
assert.doesNotMatch(ev.payoutBtn,/операционист/);
ctx.crmCloseStatus=()=>({version:5,facts:[{kind:'payin',ready:true},{kind:'payout',ready:false,reason:'payout_receipt_missing'},
  {kind:'receipt',ready:true,implicit:true},{kind:'sent',ready:true}]});
assert.match(ctx.crmCloseReason({kind:'payout',reason:'payout_receipt_missing'}),/чек выплаты/);

// 4. manualClosePayload: не-крипто маршрут без хеша, с суммой ฿ и получателем; crypto по умолчанию
ctx.S.manualCloseForm={};
const deal=base(); deal.payType='Наличные'; deal.amountRub=1217600; ctx.S.deals=[deal];
ctx.deal=id=>deal;
try{
  const f=ctx.manualCloseFormState(deal.id);
  f.payout.route='bank'; f.payout.amountThb='455000'; f.payout.recipient={name:'Villa Co',bank:'BBL',acc:'123'};
  const out=ctx.manualClosePayload(deal).manualOverride.payout;
  assert.equal(out.route,'bank'); assert.equal(out.amountThb,455000); assert.equal(out.hashes.length,0);
  assert.equal(JSON.stringify(out.recipient),JSON.stringify({name:'Villa Co',bank:'BBL',acc:'123'}));
  f.payout.route='crypto'; assert.equal(ctx.manualClosePayload(deal).manualOverride.payout.route,undefined);
  const fh={...deal,kind:'Фрихолд'}; f.payout.route='bank';
  assert.equal(ctx.manualClosePayload(fh).manualOverride.payout.route,undefined,'фрихолд всегда crypto');
  const known={...deal,mfPayout:[{hash:'a'.repeat(64),net:'TRC20',amount:1}]};
  assert.equal(ctx.manualClosePayload(known).manualOverride.payout.route,undefined,'известный hash -> crypto');
}catch(e){console.log('manualClosePayload section needs crmPayloadFinal stub:',e.message); throw e;}
console.log('payout receipt independent QA JS PASS');
