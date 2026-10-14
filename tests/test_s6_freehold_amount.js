const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync('static/stand/tasks.html','utf8');
const d={id:1,step:'s6',invoiceUsd:97500,rates:{}}, inputs={r4:'8 123 456,78',r3:'83.3175'};
const ctx={deal:()=>d,val:k=>inputs[k],num:x=>Number(String(x??'').replace(',','.')),cleanNum:x=>String(x).replace(/[^\d.,]/g,''),save(){},render(){}};
vm.createContext(ctx);
vm.runInContext(html.match(/^function syncFreeholdRate\([^]*?^}/m)[0],ctx);
ctx.syncFreeholdRate(1,'sum');
assert.equal(d.amountRub,8123456.78);
assert.equal(d.rates.client,'83,317505');
assert.equal(d.freeholdClientInput,'sum');
assert.equal(Number(d.rates.client.replace(',','.')).toFixed(4),'83.3175');
ctx.syncFreeholdRate(1,'rate');
assert.equal(d.amountRub,8123456.25);
assert.equal(d.freeholdClientInput,'rate');
ctx.syncFreeholdRate(1,'sum');
d.step='s8'; const prior=JSON.stringify(d);ctx.syncFreeholdRate(1,'rate');
assert.equal(JSON.stringify(d),prior,'submitted s6 cannot be recalculated');
assert.match(html,/id="r4"[^]*?syncFreeholdRate\(\$\{d.id\},'sum'\)/);
console.log('s6 freehold amount OK');

// The consent action must preserve the principal even when six-digit rate × X differs.
d.step='s6'; d.kind='Фрихолд';
Object.assign(ctx,{isCrypto:()=>false,toast(){},go:(d,step)=>d.step=step,
  ippsTariff:()=>({label:'bank'}),freeholdSend:()=>98330,usd:String,moneyKop:String});
const start=html.indexOf("  if(step==='s6'){");
const end=html.indexOf("    if(d.type==='Обмен валюты'){",start);
vm.runInContext('function consent(d){const step="s6";'+html.slice(start,end)+'}}',ctx);
ctx.consent(d);
assert.equal(d.step,'s8');assert.equal(d.amountRub,8123456.78);assert.equal(d.rates.client,'83,317505');
vm.runInContext(html.match(/^function freeholdApprox\([^]*?^}/m)[0],ctx);
assert.equal(ctx.freeholdApprox(d).pay,8123456.78);
// Render the real s6 card: six-digit storage, four-digit display, editable principal.
const cardStart=html.indexOf('      const X=d.invoiceUsd||0;\n      const k=num(d.rates.client);');
const cardEnd=html.indexOf('\n    }\n    return `<div class="card">',cardStart);
assert.ok(cardStart>0&&cardEnd>cardStart);
Object.assign(ctx,{ago:()=>'',freeholdInvoiceInputs6:()=>'',freeholdSummary6:()=>'',calcBtn:()=>'',quotesSummary:()=>''});
vm.runInContext('function card(d){'+html.slice(cardStart,cardEnd)+'}',ctx);
const stored=JSON.stringify(d),card=ctx.card(d);
assert.match(card,/id="r3" value="83,3175"/);
assert.match(card,/id="r4" value="8123456,78"/);
assert.doesNotMatch(card,/<input[^>]*readonly[^>]*id="r4"/);
assert.equal(JSON.stringify(d),stored);
