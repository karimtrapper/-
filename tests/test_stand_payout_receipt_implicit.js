// Чек выплаты из обоих путей загрузки и не-крипто выплата без хеша (фронт задачника).
const assert=require('node:assert/strict'), fs=require('node:fs'), vm=require('node:vm');
const html=fs.readFileSync('static/stand/tasks.html','utf8');
function source(name){const m=html.match(new RegExp('^function '+name+'\\([^]*?^}','m'));assert.ok(m,name);return m[0];}
const ctx={atob};
vm.createContext(ctx);
vm.runInContext("function managerDraftDocTarget(){return null}function num(v){const n=parseFloat(String(v).replace(',','.'));return Number.isFinite(n)?n:null}",ctx);
for(const name of ['fileValid','filesOf','receiptDocs','hasReceipt','mfList','noncryptoPayout'])vm.runInContext(source(name),ctx);
const pdf={file:'slip.pdf',mime:'application/pdf',data:'data:application/pdf;base64,JVBERi0='};
const deal=(files,extra)=>({id:1489,type:'Оплата недвижимости',kind:'Аренда',docs:{},files,mfPayout:[],...extra});

// Слот «Чек» и «+ Загрузить ещё» с типом «чек» — один и тот же факт.
let d=deal({receipt:[pdf]});
assert.ok(ctx.hasReceipt(d));assert.equal(JSON.stringify(ctx.receiptDocs(d).map(x=>[x.kind,x.i])),JSON.stringify([['receipt',0]]));
d=deal({additional:[{...pdf,documentType:'receipt'}]});
assert.ok(ctx.hasReceipt(d));assert.equal(JSON.stringify(ctx.receiptDocs(d).map(x=>[x.kind,x.i])),JSON.stringify([['additional',0]]));
assert.equal(d.docs.receipt,true,'docs.receipt выводится и из «+ Загрузить ещё»');
// Другой тип документа или пустой файл чеком не считаются; галочка docs.receipt без файла тоже.
assert.ok(!ctx.hasReceipt(deal({additional:[{...pdf,documentType:'inv'}]})));
assert.ok(!ctx.hasReceipt(deal({additional:[{file:'x.pdf',documentType:'receipt'}]})));
assert.ok(!ctx.hasReceipt(deal({},{docs:{}})),'без файла и флага чека нет');
// Индексы для docOpen: чек из additional открывается по индексу в additional.
d=deal({additional:[{...pdf,documentType:'other'},{...pdf,file:'b.pdf',documentType:'receipt'}]});
assert.equal(JSON.stringify(ctx.receiptDocs(d).map(x=>[x.kind,x.i])),JSON.stringify([['additional',1]]));

// Не-крипто выплата недвижимости: сумма и получатель есть, хеша нет.
const bank={amountThb:455000,payTo:{bank:'BBL',acc:'123-4-56789-0'}};
assert.equal(ctx.noncryptoPayout(deal({receipt:[pdf]},bank)),true);
assert.equal(ctx.noncryptoPayout(deal({},{...bank,mfPayout:[{hash:'b'.repeat(64),net:'TRC20',amount:1}]})),false,'хеш перевода в MF Corp — отдельный крипто-факт');
for(const crypto of [{postConv:'coins'},{postConv:'ipps_swift'},{postConv:'client'},{paySrc:'coins'},{transfer:{sends:[{}]}}])
  assert.equal(ctx.noncryptoPayout(deal({},{...bank,...crypto})),false,JSON.stringify(crypto));
assert.equal(ctx.noncryptoPayout(deal({},{...bank,payTo:{bank:'BBL'}})),false,'без счёта получателя');
assert.equal(ctx.noncryptoPayout(deal({},{...bank,amountThb:0})),false);
assert.equal(ctx.noncryptoPayout(deal({},{...bank,kind:'Фрихолд'})),false);
console.log('payout receipt implicit (front) OK');
