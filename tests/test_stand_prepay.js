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
const ctx={demoAllowed:()=>false,walletBlock:()=>'',S:{role:'operator',deals:[]},STAND:false,
  convOf:d=>d.cnvId?ctx.batch:null,isCrypto:d=>d.payType==='Крипта',
  walletById:id=>ctx.walletList.find(w=>w.id===id),wallets:()=>ctx.walletList,
  addrValid:()=>true,htmlText:String,usd:x=>'$'+x,moneyKop:(n,s)=>`${n} ${s}`,
  ippsTariff:()=>({label:'Банк 0,8% + 50$',percent:.8,fixed:50}),
  needsPayConfirm:()=>false,expectOf:()=>({}),save:()=>{},render:()=>{},
  log:(d,text)=>d.log.push({text}),stepWho:d=>d.step==='s22'?'manager':d.step==='s23'?'teodor':'operator',
  deal:id=>ctx.S.deals.find(d=>d.id===id),num:Number,cleanNum:String,
  document:{getElementById:()=>null},saveNote:()=>{},toast:()=>{},
  now:()=> '12.10, 12:00',money:String,avgUsdt:()=>1,exSum:()=>0,exMargin:()=>0,
  esc:String,
};
ctx.walletList=[{id:'company',name:'Компания',addr:'company',owner:'компания',multisig:true,role:'findir'},
             {id:'founder',name:'Андрей',addr:'founder',owner:'Андрей',multisig:false,role:'teodor'}];
vm.createContext(ctx);
for(const name of ['STEPS','FLOW_RUB','FLOW_USDT','FLOW_ALIAS','SOURCES_PAY','POLICY_ROLE_ORDER','POLICY_ROLE_NAMES','POLICY_ROLE_DATIVE']){
  vm.runInContext(html.match(new RegExp(`^const ${name}\\s*=[^]*?;`,'m'))[0].replace(/^const /,'var '),ctx);
}
for(const name of ['hasPolicy','policyInitiators','policyInitiateTargets','policyInitiateRole','policySignRole','policySignTargets','policyCanClaim','policyRoleNames','policyReleasedByMe','policyLocked','policyOwnsSend','policyOwnsSign','policyNeedsApproval','policyApprovalActor','walletPolicyLine','uniqueWallets','walletOptionText','prepayCanStart','prepayStepDone','prepayRefundRole','prepayPanel','flowOf','progress',
  'stepTitle','taskBranchesForRole','myTasks','reqOpen','go','sendList','freeholdFee','freeholdSend','dealWallet','hashSum','econ','act','cnvTxTime','cnvTxHint','cnvTxShareBlock','txShort','jsLiteralAttr','addressDisclosure']){
  vm.runInContext(fn(name),ctx);
}
assert.match(ctx.cnvTxTime(Date.UTC(2026,9,16,9,47)), /16\.10.*12:47/);
ctx.S.incomingShare={dealId:1484,amount:80,ledger:{amount_usdt:200,free_usdt:80,used_usdt:120,allocations:[]}};
const shareBlock=ctx.cnvTxShareBlock({id:1484});
assert.match(shareBlock, /id="w_share"/);
assert.match(shareBlock, /style="min-height:44px;height:44px"[^>]*>Засчитать долю<\/button>/);
assert.doesNotMatch(shareBlock, /[♻✅]/);
delete ctx.S.incomingShare;
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
  delete d.payout.reimbursement;
  const partial=ctx.econ(d);
  assert.equal(partial.payin,10000);
  assert.equal(partial.payinDiff,-1000,'Недобор брокера виден относительно расчёта');
  assert.equal(partial.cost,10130);
  assert.equal(partial.net,-130,'Убыток не прячется в возмещении');
  d.payout.reimbursement={usdt:10130,hash:'refund'};
  assert.deepEqual(ctx.econ(d),partial,'Полное возмещение не меняет экономику частичного прихода');
  d.payout.usdt=10200;
  assert.equal(ctx.econ(d).cost,10200,'Принятая переплата включается в себестоимость');
  assert.equal(ctx.econ(d).net,-200);
}
// Настоящие карточки отправки и подписи объясняют источник предоплаты.
{
  const view={...ctx,SOURCES:{},POST_CONV:[{k:'ipps_swift',t:'IPPS SWIFT'}],
    convOf:d=>d.batch,approx:()=>({}),fake:()=>({}),econ:()=>({ready:false}),
    cnvMembers:d=>[d],pcOut:d=>Number(d.transfer.amount),pcSends:()=>true,
    sendDone:()=>false,sendTo:()=> 'IPPS',sendBlock:()=>'',pcNet:()=> 'TRC-20',
    sendHead:()=> 'Отправка в IPPS',walletSigner:()=> 'Фин дир',
    transferModeBlock:()=>'',stepNote:()=>'',
  };
  vm.createContext(view);
  for(const name of ['personalSend','outgoingPickState','outgoingPickList','outgoingReviewBlock','sendBlock','sendSum','sendDeclared','sendLeft','pcAmount','prepayFundingText','taskFacts','packTasks','signSummary','canRerate','rerateBalance','stepCard']){
    vm.runInContext(fn(name),view);
  }
  // Тип кошелька определяет подпись даже без source или при старом неверном source.
  const wallets=[...ctx.walletList,{...ctx.walletList[1],id:'teodor',owner:'Теодор'}];
  for(const wallet of wallets) for(const step of ['s23','s24']) for(const status of ['no_batch','s18w','done']) for(const source of [undefined,'founder','multisig']){
    const d={...old,step,rates:{},postConv:'ipps_swift',transfer:{amount:10130,addr:'ipps'},
      prepay:{source,wallet,amount:10130,
        brokerStep:status==='no_batch'?'s18':status}};
    if(status!=='no_batch') d.batch={sources:[{dealId:d.id,usdt:11000}],
      txs:status==='done'?[{amount:11000,status:'confirmed'}]:[],broker:'Брокер'};
    const card=view.stepCard(d);
    assert.ok(card.includes(wallet.multisig?'с мультисига компании':'с кошелька '+wallet.owner));
    assert.match(card,/Источник оплаты/);
    assert.ok(card.includes(status==='done'?'USDT брокера уже получены.':'Рубли конвертируются параллельно.'));
    assert.doesNotMatch(card,/клиент платил криптой|конвертации не было|Пачки конвертации нет|проверьте, откуда берутся деньги|брокер Брокер выдал|из пришедших/);
  }
  const personal={...old,step:'s23',rates:{},walletId:'founder',postConv:'ipps_swift',
    transfer:{amount:10130,addr:'ipps',sends:[]}};
  view.S.role='teodor';
  assert.match(view.stepCard(personal),/>Отправил<\/button>/);
  assert.doesNotMatch(view.stepCard(personal),/id="sh_|id="sa_/);
  personal.outgoingReview={requestedAt:'now',scanStatus:'complete',candidates:[]};
  view.S.role='operator';
  assert.match(view.stepCard(personal),/Проверить отправку/);
  assert.match(view.stepCard(personal),/id="sh_/);
  assert.match(view.stepCard(personal),/id="sa_/);
  const crypto={...old,payType:'Крипта',step:'s23',rates:{},transfer:{},pay:{usdt:11000}};
  assert.match(view.stepCard(crypto),/Клиент платил криптой — USDT пришли напрямую/);
}
// Реальное act(s18w): приход распределяется, а этап оплаты остаётся на месте.
(async()=>{
  ctx.demoAllowed=()=>true; // Явный автотестовый режим для синтетического прихода.
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
