const fs=require('fs'),vm=require('vm');
const html=fs.readFileSync('static/stand/tasks.html','utf8');
const src=['freeholdFee','freeholdSend'].map(name=>{
 const m=html.match(new RegExp('^function '+name+'\\([^\\n]*\\}\\s*$','m'))||html.match(new RegExp('^function '+name+'\\([^]*?^}','m'));
 if(!m)throw Error(name);return m[0];
}).join('\n');
const c={};vm.createContext(c);vm.runInContext(src,c);
for(const [percent,numerator] of [[0.8,8n],[1.5,15n]]){
 let count=0;const examples=[];
 for(let cents=10000000;cents<=100000000;cents+=100){
  const invoiceUsd=cents/100;
  const ui=c.freeholdSend(invoiceUsd,{percent,fixed:50});
  const exact=Number(BigInt(cents)+(BigInt(cents)*numerator+500n)/1000n+5000n)/100;
  if(ui!==exact){count++;if(examples.length<5)examples.push({invoiceUsd,ui,server:exact});}
 }
 console.log(JSON.stringify({tariffPercent:percent,range:'$100000–$1000000, whole dollars',mismatchCount:count,examples}));
}
