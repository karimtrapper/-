const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync('static/stand/tasks.html', 'utf8');
function fn(name) {
  const one = html.match(new RegExp(`^function ${name}\\([^\\n]*\\)\\{[^\\n]*\\}$`, 'm'));
  if (one) return one[0];
  const hit = html.match(new RegExp(`^function ${name}\\([^]*?^}`, 'm'));
  assert.ok(hit, `missing ${name}`);
  return hit[0];
}
const tariff = html.match(/^const IPPS_TARIFFS\s*=\s*\{[^]*?^};/m);
assert.ok(tariff);
const notices = [];
const ctx = {
  save: () => {}, render: () => {}, toast: message => notices.push(message),
  deal: () => ctx.activeDeal,
  dealKind: () => 'mf_auto', exchangeSpec: () => null, isCrypto: () => false,
  URLSearchParams, S: {draft: null}, Math,
};
vm.createContext(ctx);
vm.runInContext(tariff[0].replace(/^const /, 'var ') + '\n' + html.match(/^const BROKER_FEE=.*;$/m)[0] + '\n' + [
  'num','brokerSend','freeholdFee','freeholdSend','autoSafeCents',
  'askModes','draftMode','draftAmounts','ippsTariff','autoMarginPct',
  'autoActualMarginPct','autoShownMarginPct','autoMarginTolerance','autoClientRubSet','autoMarginSet',
  'cleanNum','fmtAmount','autoClientRubForUsd','autoRecalc',
].map(fn).join('\n'), ctx);
vm.runInContext(html.match(/^const CALC_URL=.*;$/m)[0]+'\n'+fn('calcLink'),ctx);

const draft = {type:'Оплата авто', payType:'По реквизитам', invoiceCurrency:'usd',
  ippsTariff:'bank', mode:'need', cur:'fhusd', sum:'45000'};
const usdStart = ctx.draftAmounts(draft);
assert.equal(usdStart.requestedUsd, 45000);
assert.equal(usdStart.invoiceUsd, 45000);
assert.equal(usdStart.amountRub, null);
assert.equal(usdStart.autoRequestMode, 'usd');
ctx.S.draft = draft;
ctx.draftMode('have');
assert.equal(draft.cur, 'rub');
assert.equal(draft.sum, '');
draft.sum = '4 000 000';
const rubStart = ctx.draftAmounts(draft);
assert.equal(rubStart.requestedRub, 4000000);
assert.equal(rubStart.invoiceUsd, null);
assert.equal(rubStart.amountRub, 4000000);
assert.equal(rubStart.autoRequestMode, 'rub');

const rubDeal = {autoPayment:true, step:'s6', autoRequestMode:'rub', requestedRub:4000000,
  ippsTariff:'bank', rates:{rubUsdt:82}};
ctx.autoRecalc(rubDeal);
assert.equal(rubDeal.amountRub, 4000000);
assert.ok(rubDeal.invoiceUsd > 0);
assert.equal(rubDeal.invoiceUsd, Math.round(((Math.round((4000000/82/1.03-1)*100)/100-50)/1.008)*100)/100);
assert.equal(rubDeal.freeholdClientInput, 'sum');

const usdDeal = {autoPayment:true, step:'s6', autoRequestMode:'usd', requestedUsd:45000,
  ippsTariff:'soft', rates:{rubUsdt:82}};
ctx.autoRecalc(usdDeal);
assert.equal(usdDeal.invoiceUsd, 45000);
assert.ok(usdDeal.amountRub > 0);
assert.equal(usdDeal.amountRub, Math.round((Math.round((45000+1)*82*1.03*100)/100)*
  (45000*1.015+50)/45000*100)/100);
assert.equal(usdDeal.requestedUsd, 45000);
assert.equal(ctx.autoClientRubForUsd(1e12, 80, ctx.IPPS_TARIFFS.bank, 3), null,
  'unsafe cent precision must stop instead of looping');
const tiny = {autoPayment:true, step:'s6', autoRequestMode:'rub', requestedRub:4205.52,
  ippsTariff:'bank', autoMarkupPct:3, rates:{rubUsdt:80}};
ctx.autoRecalc(tiny);
assert.ok(tiny.invoiceUsd>0, 'reverse quote must keep a payable cent');
assert.equal(ctx.autoMarginPct({autoMarkupPct:.1,autoRequestMode:'rub'}, 4000000), 1.5,
  'hydrated margin cannot bypass the approved floor');
assert.equal(html.includes('autoDisplayMarkup'), false, 'HTML and log must not rewrite user data');

for(const mode of ['usd','rub']) {
  const d={autoPayment:true,step:'s6',autoRequestMode:mode,
    requestedUsd:mode==='usd'?45000:null,requestedRub:mode==='rub'?4000000:null,
    ippsTariff:'bank',rates:{rubUsdt:80},payins:[{amount:123}],transfers:[{amount:456}]};
  ctx.activeDeal=d;
  assert.equal(ctx.autoRecalc(d),true);
  const invoice=d.invoiceUsd,initialRub=d.amountRub,source=d[mode==='usd'?'requestedUsd':'requestedRub'];
  const manualRub=Math.round((initialRub+1000)*100)/100;
  ctx.autoClientRubSet(d.id,String(manualRub).replace('.',','));
  assert.equal(d.autoManualClientRub,true);
  assert.equal(d.amountRub,manualRub);
  assert.equal(d.invoiceUsd,invoice,'seller invoice stays fixed');
  assert.equal(d[mode==='usd'?'requestedUsd':'requestedRub'],source);
  assert.ok(ctx.autoShownMarginPct(d)>3);
  assert.equal(ctx.autoRecalc(d),true,'refresh must preserve manual sum');
  const reloaded=JSON.parse(JSON.stringify(d));
  assert.equal(ctx.autoRecalc(reloaded),true,'reload must preserve manual sum');
  assert.equal(reloaded.amountRub,manualRub);
  assert.equal(reloaded.invoiceUsd,invoice);
  ctx.activeDeal=reloaded;
  ctx.autoClientRubSet(d.id,String(Math.round(initialRub*1.15)));
  assert.equal(reloaded.amountRub,manualRub,'invalid margin must leave agreed amount');
  assert.match(notices.at(-1),/1,5–5/);
  ctx.autoClientRubSet(d.id,'недопустимо');
  assert.equal(reloaded.amountRub,manualRub);
  ctx.autoMarginSet(d.id,'4,5');
  assert.equal(reloaded.autoManualClientRub,false,'margin chip/input returns to auto quote');
  assert.ok(reloaded.amountRub>0);
  if(mode==='usd')assert.equal(reloaded.invoiceUsd,invoice,'USD request remains seller invoice');
  assert.equal(reloaded[mode==='usd'?'requestedUsd':'requestedRub'],source);
}


// Исполняем настоящие функции страницы: мок комиссии скрывал копеечные ошибки.
function fresh(mode) {
  return {autoPayment:true, step:'s6', autoRequestMode:mode,
    requestedUsd:45000, requestedRub:4000000, ippsTariff:'bank',
    rates:{rubUsdt:80}, payins:[{amount:123}], transfers:[{amount:456}]};
}
let invalidChecks=0;
for(const mode of ['usd','rub']) {
  const field=mode==='usd'?'requestedUsd':'requestedRub';
  const derived=mode==='usd'?'amountRub':'invoiceUsd';
  for(const value of [undefined,null,0,-1,NaN,Infinity,1e100]) {
    const d=fresh(mode);
    assert.equal(ctx.autoRecalc(d),true);
    d[field]=value;
    const facts=JSON.stringify([d.payins,d.transfers]);
    assert.equal(ctx.autoRecalc(d),false);
    assert.equal(d[derived],null,'invalid source must clear previous quote');
    assert.equal(d.rates.client,null);
    assert.ok(d.autoQuoteError);
    assert.ok(Object.is(d[field],value),'source must not be rewritten');
    assert.equal(d.autoRequestMode,mode);
    assert.equal(JSON.stringify([d.payins,d.transfers]),facts,'facts must not be changed');
    d[field]=mode==='usd'?45000:4000000;
    assert.equal(ctx.autoRecalc(d),true);
    assert.ok(d[derived]>0);
    assert.equal(d.autoQuoteError,undefined);
    invalidChecks++;
  }
  for(const value of [undefined,null,0,-1,NaN,Infinity,1e100,Number.MIN_VALUE]) {
    const d=fresh(mode);
    assert.equal(ctx.autoRecalc(d),true);
    d.rates.rubUsdt=value;
    assert.equal(ctx.autoRecalc(d),false,`mode=${mode} invalid rate=${value}`);
    assert.equal(d[derived],null,'invalid rate must clear previous quote');
    assert.equal(d.rates.client,null);
    d.rates.rubUsdt=80;
    assert.equal(ctx.autoRecalc(d),true);
    assert.equal(d.autoQuoteError,undefined);
    invalidChecks++;
  }
  const d=fresh(mode);
  d.rates=undefined;
  assert.equal(ctx.autoRecalc(d),false);
  assert.equal(d.rates.client,null);
  d.rates.rubUsdt=80;
  assert.equal(ctx.autoRecalc(d),true);
  d.ippsTariff='missing';
  assert.equal(ctx.autoRecalc(d),false);
  assert.equal(d[derived],null);
  d.ippsTariff='bank';
  assert.equal(ctx.autoRecalc(d),true);
}
for(const input of ['542000000000','1e12','1e14','1e16','1e100','Infinity','NaN']) {
  assert.equal(vm.runInContext(`autoClientRubForUsd(${input},80,IPPS_TARIFFS.bank,3)`,ctx,{timeout:300}),null,
    `unsafe money range must stop: ${input}`);
}
for(const key of ['usd','rub']) {
  const d=fresh(key);
  d.step='s11';d.rates.client='123';d.invoiceUsd=456;d.amountRub=789;
  const before=JSON.stringify(d);
  ctx.autoRecalc(d);
  assert.equal(JSON.stringify(d),before,'post-quote deal must not be recalculated');
  d.step='s6';d.autoPayment=false;
  const legacy=JSON.stringify(d);
  ctx.autoRecalc(d);
  assert.equal(JSON.stringify(d),legacy,'legacy freehold must not be recalculated');
}
// Эталон старого калькулятора: округление RUB до тарифа и 1 USDT за вывод.
function legacyTarget(usd,rate,margin,t) {
  const base=Math.round((usd+1)*rate*(1+margin/100)*100)/100;
  return Math.round(base*((usd*(1+t.percent/100)+t.fixed)/usd)*100)/100;
}
function legacyAmount(rub,rate,margin,t) {
  const received=Math.round((rub/(rate*(1+margin/100))-1)*100)/100;
  return Math.round((received-t.fixed)/(1+t.percent/100)*100)/100;
}
let seed=1234567;
const amounts=[.01,.02,.52,3.07,100,1000,6249.99,6250,6250.01,12499.99,12500,12500.01,1e6,1e8];
for(let i=0;i<300;i++) {
  seed=(1664525*seed+1013904223)>>>0;
  amounts.push(Math.round(seed/2**32*1e8)/100);
}
let moneyChecks=0;
for(const tariff of ['bank','soft'])for(const rate of [1,80,88,100,105.123456])
for(const margin of [1.5,3,4,5])for(const usd of amounts) {
  const d=fresh('usd');
  d.requestedUsd=usd;d.ippsTariff=tariff;d.rates.rubUsdt=rate;d.autoMarkupPct=margin;
  assert.equal(ctx.autoRecalc(d),true);
  const rub=d.amountRub,t=ctx.IPPS_TARIFFS[tariff];
  assert.equal(rub,legacyTarget(usd,rate,margin,t),'USD target matches old calculator');
  d.autoRequestMode='rub';d.requestedRub=rub;
  assert.equal(ctx.autoRecalc(d),true);
  assert.equal(d.invoiceUsd,legacyAmount(rub,rate,margin,t),'RUB budget matches old calculator');
  assert.equal(d.amountRub,rub,'RUB budget cannot be changed');
  moneyChecks++;
}
const exact={autoPayment:true,step:'s6',autoRequestMode:'usd',requestedUsd:79800,
  ippsTariff:'soft',autoMarkupPct:3,rates:{rubUsdt:83.498}};
assert.equal(ctx.autoRecalc(exact),true);
assert.equal(exact.amountRub,6970367.62);
assert.equal(exact.rates.client,'87,347965');
for(const tariff of ['bank','soft'])for(const requestedUsd of [1005.11,45000]){
  const edge={autoPayment:true,step:'s6',autoRequestMode:'usd',requestedUsd,
    ippsTariff:tariff,autoMarkupPct:1.5,rates:{rubUsdt:83.498}};
  assert.equal(ctx.autoRecalc(edge),true);
  edge.autoManualClientRub=true;
  assert.equal(ctx.autoRecalc(edge),true,'old quote at 1.5% must survive manual quote guard');
  const handoff=new URL(ctx.calcLink(edge),'https://example.invalid');
  const profit=Number(handoff.searchParams.get('profit'));
  assert.ok(profit>=1.5&&profit<=5,'accepted 1.5% quote must hand off an allowed margin');
  if(requestedUsd===45000&&tariff==='bank')assert.equal(profit,1.5);
}
for(const requestedUsd of [1005.11,45000]){
  const edge={autoPayment:true,step:'s6',autoRequestMode:'usd',requestedUsd,
    ippsTariff:'soft',autoMarkupPct:5,rates:{rubUsdt:83.498}};
  assert.equal(ctx.autoRecalc(edge),true);
  edge.autoManualClientRub=true;
  assert.equal(ctx.autoRecalc(edge),true);
  const profit=Number(new URL(ctx.calcLink(edge),'https://example.invalid').searchParams.get('profit'));
  assert.ok(profit>=1.5&&profit<=5,'accepted 5% quote must hand off an allowed margin');
}
for(const [base,want] of [[499999.99,5],[500000,4],[999999.99,4],[1000000,3]]) {
  for(const mode of ['usd','rub'])
    assert.equal(ctx.autoMarginPct({autoRequestMode:mode,requestedUsd:base/80,rates:{rubUsdt:80}},base),want);
}
console.log(`auto task draft and quote: PASS; ${moneyChecks} money cases, ${invalidChecks} invalid/recovery cases, 7 bounded extremes`);
