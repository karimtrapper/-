const assert=require('node:assert/strict'), fs=require('node:fs'), vm=require('node:vm');
const html=fs.readFileSync('static/stand/tasks.html','utf8');
function fn(name){return html.match(new RegExp(`^(?:async )?function ${name}\\([^]*?^}`,'m'))?.[0] || '';}
const values={w2:'a'.repeat(64),w_net:'TRC-20',w_share:'100'};
const calls=[],messages=[],DRAFTS={};
let waitForPreview;
const ctx={S:{open:1,convs:[]},DRAFTS,deal:()=>({id:1}),convOf:()=>({id:7,walletId:'a'}),
  walletById:()=>({addr:'test-wallet'}),val:k=>values[k],
  demoAllowed:()=>false,toast:t=>messages.push(t),usd:x=>'$'+x,esc:String,
  render:()=>{for(const name of ['w2','w_net'])values[name]=DRAFTS['1|'+name]??values[name];},
  document:{getElementById:name=>name in values?{set value(value){values[name]=value;}}:null},
  standAction:async (url,p)=>{
    calls.push(p);
    if(p.preview){
      await waitForPreview;
      const hash=p.hash.split('/').at(-1);
      return {hash,network:'trc20',ledger:{amount_usdt:200,used_usdt:100,free_usdt:100,deal_ids:[1487]}};
    }
    return {tx:{amount:100}};
  }};
vm.createContext(ctx);
vm.runInContext('let incomingRequest=null, incomingRequestSeq=0;',ctx);
ctx.htmlText=String;
for(const name of ['cnvIncomingKey','cnvTxNetworkLabel','cnvTxHint','cnvTxShareBlock','cnvTxManual','cnvTxAllocate','txShort','jsLiteralAttr','addressDisclosure']){
  assert.ok(fn(name),name+' exists');vm.runInContext(fn(name),ctx);
}
(async()=>{
  await ctx.cnvTxManual(1);
  assert.equal(calls[0].preview,true);
  assert.equal(ctx.S.incomingShare.amount,100);
  const block=ctx.cnvTxShareBlock({id:1});
  assert.match(block,/Сумма на эту сделку/);assert.match(block,/max="100"/);
  // The remaining balance is now the card heading, without a decorative emoji.
  assert.match(block,/<b>Свободно \$100.00 из \$200.00<\/b>/);
  assert.match(block,/по переводу уже разнесено \$100.00 \(#1487\), свободно \$100.00/);
  ctx.S.incomingShare.early=true;
  const earlyBlock=ctx.cnvTxShareBlock({id:1});
  assert.match(earlyBlock,/Перевод поступил до отправки рублей брокеру\./);
  assert.match(earlyBlock,/<label class="task-check task-check--confirm"><input type="checkbox" id="w_confirm_early"/);
  assert.match(earlyBlock,/Подтверждаю, что этот перевод брокера относится к этой пачке/);
  assert.doesNotMatch(earlyBlock,/id="w_confirm_early" checked/,'согласие по умолчанию не отмечено');
  ctx.S.incomingShare.early=false;
  values.w_share='101';await ctx.cnvTxAllocate(1);assert.equal(calls.length,1);
  values.w_share='50';await ctx.cnvTxAllocate(1);assert.equal(calls[1].amount,50);
  assert.equal(ctx.S.incomingShare,null);
  const selected='b'.repeat(64);
  DRAFTS['1|w2']=values.w2;
  DRAFTS['1|w_net']=values.w_net='ERC-20';
  await ctx.cnvTxManual(1,selected,'trc20');
  assert.equal(values.w2,selected);
  assert.equal(values.w_net,'TRC-20');
  assert.equal(calls[2].hash,selected);
  await ctx.cnvTxAllocate(1);
  assert.equal(calls[3].hash,selected);
  assert.equal(DRAFTS['1|w2'],undefined);

  let finishPreview;
  waitForPreview=new Promise(resolve=>{finishPreview=resolve;});
  const pending=ctx.cnvTxManual(1,selected,'trc20');
  DRAFTS['1|w2']=values.w2='c'.repeat(64);
  finishPreview();
  await pending;
  assert.equal(ctx.S.incomingShare,null,'поздний ответ не заменяет новый ввод');
  DRAFTS['1|w2']=values.w2='https://tronscan.org/#/transaction/'+selected;
  await ctx.cnvTxManual(1);
  assert.equal(values.w2,selected,'проверенная ссылка заменяется каноническим хешем');
  DRAFTS['1|w_net']=values.w_net='ERC-20';
  const checkedCalls=calls.length;
  await ctx.cnvTxAllocate(1);
  assert.equal(calls.length,checkedCalls,'доля не отправляется после смены сети');
  console.log('hash split UI: preview, remainder, hint, excess and allocation PASS');
})().catch(e=>{console.error(e);process.exit(1)});
