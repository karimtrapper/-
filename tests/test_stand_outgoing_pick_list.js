// Настоящие функции списка: разделение получателей, сумма, подтверждения и POST.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const html=fs.readFileSync(require('node:path').join(__dirname,'../static/stand/tasks.html'),'utf8');
function fn(n){return html.match(new RegExp(`^(?:async )?function ${n}\\([^]*?^}`,'m'))[0];}
(async()=>{
  const ref='81f87ac971'.padEnd(64,'0'), to='TXFqZbXCqoq5QVxRpp9EGLSzkeLMz8iG5D', fee='TLntW9Z59LYY5KEi9cmwk3PKjQga828ird';
  const d={id:1487,prepay:{startedAt:'now'},transfer:{amount:2234.76,addr:to,sends:[]},outgoingReview:{scanStatus:'complete',candidates:[
    {hash:ref,from:'TFrom',to,amount:2234.76,timestamp_ms:Date.parse('2026-10-13T12:15:00+03:00'),beforeOrder:true,selectable:true},
    {hash:ref,from:'TFrom',to:fee,amount:1.5,timestamp_ms:Date.parse('2026-10-13T12:15:00+03:00'),networkFee:true,selectable:false},
    {hash:'b'.repeat(64),to,amount:10,timestamp_ms:Date.now(),claimedBy:'СД-999',selectable:false}
  ]}};
  const sent=[],checks={};
  const ctx={S:{role:'operator'},deal:()=>d,sendList:d=>d.transfer.sends,htmlText:String,usd:String,
    moneyKop:(n,s)=>`${Number(n)} ${s}`,render:()=>{},toast:()=>{},
    standVer:42,document:{getElementById:id=>({checked:!!checks[id]})},
    standAction:async(path,payload)=>{sent.push({path,payload});return {success:true};}};
  vm.createContext(ctx);
  for(const n of ['txShort','jsLiteralAttr','outgoingPickState','outgoingPickSet','outgoingCommissionSet','outgoingPickSubmit','outgoingPickList','outgoingReviewAction','outgoingReviewBlock'])vm.runInContext(fn(n),ctx);
  let view=ctx.outgoingReviewBlock(d);
  assert.match(view,/reimburse-tx-select/);assert.match(view,/Комиссия сети/);
  assert.match(view,/Ввести хеш вручную/);
  assert.match(view,/Все остальные переводы/);assert.match(view,/СД-999/);
  assert.match(view,new RegExp('>('+ 'b'.repeat(64) +')</span>'),
    'expanded other transfer shows its full hash');
  assert.match(view,/https:\/\/tronscan.org\/#\/transaction\/bbbbbbbb/);
  assert.match(view,/13.10.2026, 12:15:00/);
  assert.equal((view.match(/<option value="81f87/g)||[]).length,1,'Платёж доступен в списке');
  ctx.outgoingPickSet(1487,ref,true);view=ctx.outgoingReviewBlock(d);
  assert.match(view,new RegExp('https://tronscan.org/#/transaction/'+ref));
  assert.match(view,/Перевод сделан до поручения — подтверждаю/);
  assert.match(view,/В IPPS 2234.76 USDT из 2234.76 USDT/);
  assert.match(view,/себестоимость с комиссиями 2236.26 USDT/);
  ctx.outgoingCommissionSet(1487,ref,false);view=ctx.outgoingReviewBlock(d);
  assert.match(view,/себестоимость с комиссиями 2234.76 USDT/);
  ctx.outgoingCommissionSet(1487,ref,true);
  checks.pick_before_1487=true;
  await ctx.outgoingPickSubmit(1487);
  const p=sent.pop().payload;
  assert.equal(p.action,'select');assert.equal(p.version,42);assert.equal(p.confirmBeforeOrder,true);
  assert.deepEqual(Array.from(p.hashes),[ref]);assert.deepEqual(Array.from(p.commissionHashes),[ref]);assert.equal(p.confirmOverpay,false);
  ctx.S.role='teodor';assert.equal(ctx.outgoingReviewBlock(d),'');
  ctx.S.role='admin';assert.match(ctx.outgoingReviewBlock(d),/Засчитать выбранные/);
  d.outgoingReview.error='fetch_error';view=ctx.outgoingReviewBlock(d);
  assert.match(view,/TronScan недоступен/);assert.doesNotMatch(view,/fetch_error/);
  d.outgoingReview.candidates[0].amount=2300;ctx.outgoingPickSet(1487,ref,true);
  assert.match(ctx.outgoingReviewBlock(d),/Переплата 65.24 USDT — засчитать/);
  d.outgoingReview.candidates[0].amount=1;
  assert.match(ctx.outgoingReviewBlock(d),/Недоплата 2233.76/);
  console.log('Outgoing pick list UI PASS');
})().catch(e=>{console.error(e);process.exitCode=1;});
