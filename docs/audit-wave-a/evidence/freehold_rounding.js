const fs = require('fs');
const vm = require('vm');
const html = fs.readFileSync('static/stand/tasks.html','utf8');
const names = ['freeholdFee','freeholdSend'];
const src = names.map(name => {
  const m = html.match(new RegExp('^function '+name+'\\([^\\n]*\\}\\s*$','m'))||html.match(new RegExp('^function '+name+'\\([^]*?^}','m'));
  if(!m) throw new Error('missing '+name);
  return m[0];
}).join('\n');
const ctx={};vm.createContext(ctx);vm.runInContext(src,ctx);
for(const invoiceUsd of [941,10000,10000.005]){
  const tariff={percent:1.5,fixed:50};
  console.log(JSON.stringify({invoiceUsd,tariff:'soft',uiFee:ctx.freeholdFee(invoiceUsd,tariff),uiSend:ctx.freeholdSend(invoiceUsd,tariff)}));
}
