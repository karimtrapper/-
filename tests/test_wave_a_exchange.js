const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const html=fs.readFileSync('static/stand/tasks.html','utf8');
for(const script of html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g))new vm.Script(script[1]);
function fn(name){return (html.match(new RegExp(`^function ${name}\\([^\\n]*\\}\\s*$`,'m'))||html.match(new RegExp(`^function ${name}\\([^]*?^}`,'m')))[0];}
const ctx={S:{},SIGN:{rub:'₽',thb:'฿',usdt:'USDT'},save(){},render(){},mfList:()=>[],refById:()=>null,
  brokerSend:r=>({sent:r,held:0,ours:0,ctrl:0}),refAgents:()=>[]};vm.createContext(ctx);
vm.runInContext(['exchangeSpec','amountField','quoteDirs','exchangeSync','payCur','isCrypto','num','cleanNum','approx','rateUnit','costRate','syncClient','hashSum','payinParts','econ','crmNet','crmPayload'].map(fn).join('\n'),ctx);
for(const n of ['PAYIN_CRM','PAYOUT_CRM'])vm.runInContext(html.match(new RegExp(`^const ${n}[^]*?;`,'m'))[0],ctx);
for(const [pair,input,output,amount,rate,expected,dirs] of [
 ['RUB → THB','rub','thb',100000,2.7,37037,['rub','thb']],
 ['THB → RUB','thb','rub',50000,2.7,135000,['thb','rub']],
 ['RUB → USDT','rub','usdt',100000,85,1176.47,['rub']],
 ['THB → USDT','thb','usdt',50000,31.2,1602.56,['thb']],
 ['USDT → THB','usdt','thb',1000,31.2,31200,['thb']],
]){
 const d={id:1,type:'Обмен валюты',pair,payType:input==='usdt'?'Крипта':'По реквизитам',curBase:input,
 rates:{rubUsdt:81.7,usdtThb:31.2,broker:81.7},agents:[]};d[ctx.amountField(input)]=amount;
 ctx.deal=()=>d;ctx.val=k=>({r3:String(rate),r4:String(amount)}[k]||'');
 ctx.syncClient(1,'rate');assert.equal(d[ctx.amountField(output)],expected,pair);
 assert.equal(ctx.approx(d).sign,ctx.SIGN[input]);assert.equal(ctx.approx(d).thbSign,ctx.SIGN[output]);
 assert.deepEqual(Array.from(ctx.quoteDirs(d)),dirs);
 const payload=ctx.crmPayload(d);
 if(output==='usdt'){assert.equal(payload.payout_amount_usdt,expected);assert.equal(payload.payout_amount_thb,null);}
 if(input==='thb'){assert.equal(payload.payin_amount_rub,null);assert.equal(payload.custom_payin_currency,'THB');assert.equal(payload.custom_payin_amount,amount);}
 if(output==='rub'){assert.equal(payload.custom_payout_currency,'RUB');assert.equal(payload.custom_payout_amount,expected);}
 if(pair==='RUB → THB'){assert.equal(payload.payin_amount_rub,amount);assert.equal(payload.payout_amount_thb,expected);}
 if(pair==='RUB → USDT')assert.notEqual(payload.payin_amount_usdt,expected,'outgoing USDT is not the incoming broker fact');
}
console.log('five exchange pairs: calculation, directions and CRM PASS');
