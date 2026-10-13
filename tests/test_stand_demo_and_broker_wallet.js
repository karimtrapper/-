// Исполняем действия UI: обычные деньги не включают DEMO, кошелёк меняется через API.
const assert=require('node:assert/strict'), fs=require('node:fs'), vm=require('node:vm');
const html=fs.readFileSync('static/stand/tasks.html','utf8');
function fn(name){
  const one=html.match(new RegExp(`^(?:async )?function ${name}\\([^\\n]*\\)\\{[^\\n]*\\}$`,'m'));
  return (one||html.match(new RegExp(`^(?:async )?function ${name}\\([^]*?^}`,'m')))[0];
}
const ctx={S:{role:'operator',convs:[],deals:[]},STAND:true,standDemoEnabled:false,standVer:7,
  document:{getElementById:()=>null},saveNote:()=>{},toast:()=>{},save:()=>{},render:()=>{},
  deal:id=>ctx.S.deals.find(d=>d.id===id),need:()=>false,val:id=>({b0:'Broker',b1:'80',b2:'company'}[id]),
  cleanNum:String,num:Number,rubBatchReady:()=>true,now:()=> '13.10, 12:00',
  brokerSend:n=>({held:0,sent:n,ctrl:0,ours:0,pct:0,fix:0}),convMargin:()=>null,
  incomes:()=>[],walletById:id=>({id,name:'Wallet',owner:'Компания',addr:'FULL-ADDRESS-'+id}),
  moneyKop:String,money:String,log:()=>{},quoteUsed:()=>null,
  go:(d,step)=>{if(d.prepay)d.prepay.brokerStep=step;else d.step=step;},txPool:()=>ctx.pool,
  pool:[],approx:()=>({pay:100}),payinGot:()=>100,payinForeign:()=>false,PAYIN_TOL:.005,
  afterPayin:d=>{d.step='s22';},convOf:()=>ctx.S.convs[0],
  standAction:async(path,payload)=>{ctx.request={path,payload};return {success:true};},
};
vm.createContext(ctx);
for(const name of ['demoAllowed','act','payinSettle','cnvWalletFix','seedDemo','seedLeaseholdTest','transferMode'])vm.runInContext(fn(name),ctx);
(async()=>{
  for(const prepay of [false,true]){
    const d={id:1485,step:prepay?'s23':'s18',kind:'Фрихолд',rates:{},incomeAmount:900000};
    if(prepay)d.prepay={brokerStep:'s18'};
    const side={id:1486,step:'s18',incomeAmount:10000};d.conv=[1486];
    ctx.S.deals=[d,side];ctx.S.convs=[];
    await ctx.act(1485,'s18');
    assert.equal(prepay?d.prepay.brokerStep:d.step,'s18w');
    assert.equal(d.demoTransfers,undefined);assert.equal(side.demoTransfers,undefined);
    assert.equal(ctx.pool.length,0);
  }
  const crypto={id:1,step:'s14',pay:{},payinHashes:[{hash:'a'.repeat(64),amount:100}]};
  ctx.S.deals=[crypto];ctx.payinSettle(1);
  assert.equal(crypto.step,'s22');assert.equal(crypto.demoTransfers,undefined);
  // Даже старый клиент с флагом не создаёт синтетические переводы без разрешения сервера.
  const old={id:2,step:'s18',rates:{},demoTransfers:true,incomeAmount:900000};
  ctx.S.deals=[old];ctx.S.convs=[];await ctx.act(2,'s18');assert.equal(ctx.pool.length,0);
  const before=JSON.stringify(ctx.S);ctx.seedDemo();ctx.seedLeaseholdTest();ctx.transferMode(2,'demo');
  assert.equal(JSON.stringify(ctx.S),before);
  ctx.S.convs=[{walletId:'company',txs:[]}];old.prepay={wallet:{id:'teodor'}};
  await ctx.cnvWalletFix(2,'third');
  assert.equal(ctx.request.path,'/api/stand/incoming/wallet');
  assert.deepEqual(JSON.parse(JSON.stringify(ctx.request.payload)),{dealId:2,walletId:'third',version:7});
  assert.equal(ctx.S.convs[0].walletId,'company','UI ждёт атомарный ответ сервера');
  assert.equal(old.prepay.wallet.id,'teodor');
  const waiting=html.slice(html.indexOf('  s18w:()=>{'),html.indexOf('  s22:()=>{'));
  assert.doesNotMatch(waiting,/confirmed\|\|d.prepay/);
  assert.match(waiting,/walletOptionText\(w\)/);
  assert.match(waiting,/const w=c&&walletById\(c.walletId\)/);
  assert.match(html,/DEMO-приходы или переводы/);
  console.log('DEMO opt-in and actual broker wallet: PASS');
})().catch(e=>{console.error(e);process.exitCode=1;});
