// Исполняем функции настоящего интерфейса: доступность, обе задачи, история и приход.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync(require('node:path').join(__dirname,'../static/stand/tasks.html'),'utf8');
for (const script of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g)) new vm.Script(script[1]);
function fn(name) {
  const one=html.match(new RegExp(`^(?:async )?function ${name}\\([^\\n]*\\)\\{[^\\n]*\\}$`,'m'));
  return (one||html.match(new RegExp(`^(?:async )?function ${name}\\([^]*?^}`,'m')))[0];
}
const ctx={S:{role:'operator',deals:[]},STAND:false,
  convOf:d=>d.cnvId?ctx.batch:null,isCrypto:d=>d.payType==='Крипта',
  walletById:id=>ctx.walletList.find(w=>w.id===id),wallets:()=>ctx.walletList,
  addrValid:()=>true,htmlText:String,usd:x=>'$'+x,
  ippsTariff:()=>({label:'Банк 0,8% + 50$',percent:.8,fixed:50}),
  needsPayConfirm:()=>false,expectOf:()=>({}),save:()=>{},render:()=>{},
  log:(d,text)=>d.log.push({text}),stepWho:d=>d.step==='s22'?'manager':d.step==='s23'?'teodor':'operator',
  deal:id=>ctx.S.deals.find(d=>d.id===id),num:Number,cleanNum:String,
  document:{getElementById:()=>null},saveNote:()=>{},toast:()=>{},
  now:()=> '12.10, 12:00',money:String,avgUsdt:()=>1,exSum:()=>0,exMargin:()=>0,
};
ctx.walletList=[{id:'company',name:'Компания',addr:'company',owner:'компания',multisig:true,role:'findir'},
             {id:'founder',name:'Андрей',addr:'founder',owner:'Андрей',multisig:false,role:'teodor'}];
vm.createContext(ctx);
for(const name of ['STEPS','FLOW_RUB','FLOW_USDT','FLOW_ALIAS','SOURCES_PAY']){
  vm.runInContext(html.match(new RegExp(`^const ${name}\\s*=[^]*?;`,'m'))[0].replace(/^const /,'var '),ctx);
}
for(const name of ['prepayCanStart','prepayStepDone','prepayRefundRole','prepayPanel','flowOf','progress',
  'stepTitle','myTasks','reqOpen','go','sendList','freeholdFee','freeholdSend','dealWallet','hashSum','econ','act']){
  vm.runInContext(fn(name),ctx);
}
const old={id:1484,type:'Оплата недвижимости',kind:'Фрихолд',payType:'По реквизитам',
  step:'s18',invoiceUsd:10000,payinParts:[{amountRub:900000}],pay:{},log:[],walletId:'company'};
assert.equal(ctx.prepayCanStart(old),true);
assert.match(ctx.prepayPanel(old),/Оплатить наперёд/);
for(const variant of [{step:'s14'},{step:'s22'},{payType:'Крипта'},{kind:'Лизхолд'},
  {payinParts:[]},{pay:{usdt:11000}}]){
  assert.equal(ctx.prepayCanStart({...old,...variant}),false);
}
ctx.batch={walletId:'company',txs:[{status:'confirmed',amount:11000}]};
assert.equal(ctx.prepayCanStart({...old,cnvId:1,step:'s18w'}),false);
ctx.S.prepayForm=1484;
assert.match(ctx.prepayPanel(old),/readonly value="10130"/);
assert.match(ctx.prepayPanel(old),/Фаундер · Андрей/);
assert.match(ctx.prepayPanel(old),/Мультисиг компании/);
for(const source of ['founder','multisig']){
  const d=structuredClone(old);
  d.step='s22'; d.cnvId=1;
  d.prepay={source,brokerStep:'s18',wallet:ctx.walletList[source==='founder'?1:0],amount:10130};
  ctx.S.deals=[d];
  assert.equal(ctx.myTasks('operator').length,1);
  assert.equal(ctx.myTasks('manager').length,1);
  const flow=Array.from(ctx.flowOf(d));
  ctx.go(d,'s18w','Брокеру отправлено');
  assert.equal(d.step,'s22'); assert.equal(d.prepay.brokerStep,'s18w');
  assert.match(ctx.stepTitle(d),/Параллельно/);
  const progress=ctx.progress(d);
  d.step='s23';
  assert.deepEqual(Array.from(ctx.flowOf(d)),flow,'История не меняет номера после выбора источника');
  assert.ok(ctx.progress(d).i>=progress.i);
  assert.equal(ctx.dealWallet(d).id,d.prepay.wallet.id);
  assert.equal(ctx.dealWallet({...d,_prepayBroker:true}).id,'company','Карточка брокера показывает кошелёк приёма');
  ctx.go(d,'s22','USDT получены');
  assert.equal(d.step,'s23'); assert.equal(d.prepay.brokerStep,'done');
  assert.match(d.log.at(-1).text,/сервер сверит кошельки/);
  d.serverTransferComplete=true;d.payout={usdt:10130};
  assert.equal(ctx.prepayRefundRole(d),source==='founder'?'findir':null);
  if(source==='founder'){
    assert.equal(ctx.myTasks('findir').length,1);
    d.payout.reimbursement={hash:'abc',usdt:10130};
    assert.equal(ctx.prepayRefundRole(d),null);
  }
}
// Возмещение зависит от адресов, включая личный кошелёк → мультисиг.
{
  const d={...old,step:'s26',cnvId:1,serverTransferComplete:true,
    prepay:{source:'multisig',brokerStep:'done',wallet:ctx.walletList[0],amount:10130},
    payout:{usdt:10130},pay:{usdt:11000},rates:{}};
  ctx.batch={walletId:'founder'};
  assert.equal(ctx.prepayRefundRole(d),'teodor');
  ctx.S.role='teodor';
  assert.match(ctx.prepayPanel(d),/Хеш возмещения/);
  ctx.payinParts=()=>[{usdt:11000,fact:11000,calc:11000}];
  ctx.refAgents=()=>[];
  const before=ctx.econ(d);
  d.payout.reimbursement={usdt:10130,hash:'refund'};
  assert.equal(ctx.prepayRefundRole(d),null);
  assert.equal(ctx.econ(d).net,before.net);
  assert.equal(before.cost,10130);assert.equal(before.net,870);
  ctx.payinParts=()=>[{usdt:10000,fact:10000,calc:11000}];
  assert.equal(ctx.econ(d).net,-130,'Убыток не прячется в возмещении');
}
// Реальное act(s18w): приход распределяется, а этап оплаты остаётся на месте.
(async()=>{
  const d=structuredClone(old);
  d.step='s26';d.cnvId=1;d.conv=[];d.rates={};d.demoTransfers=true;
  d.prepay={source:'founder',brokerStep:'s18w',wallet:ctx.walletList[1],amount:10130};
  ctx.batch={walletId:'company',sources:[{dealId:1484,rub:900000,usdt:11000}],
    txs:[{hash:'demo:incoming:1:1',amount:11000,status:'confirmed',demo:true}]};
  ctx.S.deals=[d];ctx.S.role='operator';
  await ctx.act(1484,'s18w');
  assert.equal(d.step,'s26');assert.equal(d.prepay.brokerStep,'done');
  assert.equal(d.pay.usdt,11000);assert.equal(d.payinHashes[0].amount,11000);
  assert.equal(ctx.batch.sources[0].usdtFact,11000);
  console.log('test_stand_prepay.js: OK');
})().catch(e=>{console.error(e);process.exitCode=1;});
