// Executes named functions extracted from the unchanged stage tasks.html.
const fs=require('fs'),vm=require('vm');
const html=fs.readFileSync('static/stand/tasks.html','utf8');
function source(name){
 const m=new RegExp('^function '+name+'\\(','m').exec(html);if(!m)throw Error(name);
 const start=m.index,first=html.indexOf('{',start);let depth=0;
 for(let i=first;i<html.length;i++){
  if(html[i]==='{')depth++; else if(html[i]==='}'&&--depth===0)return html.slice(start,i+1);
 }
 throw Error('unclosed '+name);
}
const dRub={id:1,type:'Обмен валюты',pair:'RUB → USDT',payType:'По реквизитам',curBase:'rub',
  amountRub:100000,amountThb:null,amountUsdt:null,rates:{rubUsdt:'81.7',usdtThb:'31.2'}};
const dThb={id:2,type:'Обмен валюты',pair:'THB → USDT',payType:'По реквизитам',curBase:'thb',
  amountRub:null,amountThb:50000,amountUsdt:null,rates:{usdtThb:'31.2'}};
const dRubThb={...dRub,id:3,pair:'RUB → THB',rates:{...dRub.rates}};
const dThbRub={...dThb,id:4,pair:'THB → RUB',rates:{...dThb.rates}};
const deals={1:dRub,2:dThb,3:dRubThb,4:dThbRub};const values={r3:'85',r4:'100000',r5:''};
const ctx={S:{avg:{v:2.85},avgU:{v:31.2}},MARKET:{rubThb:null,usdt:null},SIGN:{rub:'₽',usdt:'USDT',thb:'฿'},
 deal:id=>deals[id],val:k=>values[k]||'',save:()=>{},render:()=>{},
 freeholdApprox:()=>{throw Error('unexpected freehold')},
 num:v=>v==null||v===''?null:parseFloat(String(v).replace(',','.'))};
vm.createContext(ctx);
for(const name of ['exchangeSpec','amountField','exchangeSync','avgRate','avgUsdt','payCur','isCrypto','approx','rateUnit','cleanNum','syncClient']) vm.runInContext(source(name),ctx);
const clean=d=>JSON.parse(JSON.stringify(d));
console.log('RUB_USDT_before',JSON.stringify({pair:dRub.pair,amountRub:dRub.amountRub,approx:ctx.approx(dRub),rateUnit:ctx.rateUnit(dRub)}));
ctx.syncClient(1,'rate');
console.log('RUB_USDT_after_pair_rate',JSON.stringify(clean(dRub)));
console.log('RUB_USDT_expected_if_client_rate_85_RUB_per_USDT',JSON.stringify({usdt:Math.round(100000/85*100)/100}));
values.r3='31.2';values.r4='';
console.log('THB_USDT_before',JSON.stringify({pair:dThb.pair,amountThb:dThb.amountThb,approx:ctx.approx(dThb),rateUnit:ctx.rateUnit(dThb)}));
ctx.syncClient(2,'rate');
console.log('THB_USDT_after_pair_rate',JSON.stringify(clean(dThb)));
console.log('THB_USDT_expected_at_31.2_THB_per_USDT',JSON.stringify({usdt:Math.round(50000/31.2*100)/100}));

values.r3='2.7';ctx.syncClient(3,'rate');ctx.syncClient(4,'rate');
console.log('PAIR_CONTROL_RUB_USDT_vs_RUB_THB',JSON.stringify({target:dRub.amountThb,control:dRubThb.amountThb,identical:dRub.amountThb===dRubThb.amountThb}));
console.log('PAIR_CONTROL_THB_USDT_vs_THB_RUB',JSON.stringify({target:dThb.amountRub,control:dThbRub.amountRub,identical:dThb.amountRub===dThbRub.amountRub}));
