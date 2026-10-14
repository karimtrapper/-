const assert=require('node:assert/strict'), fs=require('node:fs'), vm=require('node:vm');
const html=fs.readFileSync('static/stand/tasks.html','utf8');
function fn(name){return html.match(new RegExp(`^(?:async )?function ${name}\\([^]*?^}`,'m'))?.[0] || '';}
const values={w2:'a'.repeat(64),w_net:'TRC-20',w_share:'100'};
const calls=[],messages=[];
const ctx={S:{convs:[]},deal:()=>({id:1}),convOf:()=>({id:7}),val:k=>values[k],
  demoAllowed:()=>false,toast:t=>messages.push(t),render:()=>{},usd:x=>'$'+x,
  esc:String,document:{getElementById:()=>null},
  standAction:async (url,p)=>{calls.push(p);return p.preview?{hash:p.hash,network:'trc20',ledger:{amount_usdt:200,used_usdt:100,free_usdt:100,deal_ids:[1487]}}:{tx:{amount:100}};}};
vm.createContext(ctx);
for(const name of ['cnvTxHint','cnvTxShareBlock','cnvTxManual','cnvTxAllocate']){
  assert.ok(fn(name),name+' exists');vm.runInContext(fn(name),ctx);
}
(async()=>{
  await ctx.cnvTxManual(1);
  assert.equal(calls[0].preview,true);
  assert.equal(ctx.S.incomingShare.amount,100);
  const block=ctx.cnvTxShareBlock({id:1});
  assert.match(block,/Сумма на эту сделку/);assert.match(block,/max="100"/);
  assert.match(block,/♻️ свободно \$100.00 из \$200.00/);
  assert.match(block,/по переводу уже разнесено \$100.00 \(#1487\), свободно \$100.00/);
  values.w_share='101';await ctx.cnvTxAllocate(1);assert.equal(calls.length,1);
  values.w_share='50';await ctx.cnvTxAllocate(1);assert.equal(calls[1].amount,50);
  assert.equal(ctx.S.incomingShare,null);
  console.log('hash split UI: preview, remainder, hint, excess and allocation PASS');
})().catch(e=>{console.error(e);process.exit(1)});
