// Рендер s18: поступления Сбера доступны только при отправке с того же счёта.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const html = fs.readFileSync('static/stand/tasks.html', 'utf8');
const fn = name => {
  const match = html.match(new RegExp(`^function ${name}\\([^]*?^}`, 'm'));
  assert.ok(match, name);
  return match[0];
};
const step = html.match(/  s18:\(\)=>\{[^]*?\n  s18w:\(\)=>\{/);
assert.ok(step);
const stepCode = `const stepS18=({${step[0].slice(0, -'  s18w:()=>{'.length)}}).s18;`;
const main = {id: 100, code: 'СД-100', client: 'Клиент', step: 's18',
  payinParts: [{incId: 'sber:main', amountRub: 10000}], incomeAmount: 10000,
  amountRub: 10000, amountThb: 10000, rates: {broker: 100}, conv: []};
const incomes = [{id: 'sber:main', source: 'sber', dealId: 100, rub: 10000,
  grossRub: 10000}];
const ctx = {DRAFTS:{}, S: {deals: [main], incomes}, d: main, ap: {rub: 10000},
  s18Candidates: [{id: 2, uuid: 'crm2', rub: 20000, dealId: 42,
    client: 'Обмен', payer: 'Иванов', date: '2026-10-13T17:31:00',
    dealRub: 20000, payoutUsdt: 150},
  {id: 3, uuid: 'crm3', rub: 5000, dealId: null, payer: 'Петров', date: '2026-10-12T12:00:00'}],
  s18Selected: new Set([2, 3]),
  incomes: () => incomes, deal: id => ctx.S.deals.find(d => d.id === id),
  isCrypto: () => false, exSum: () => 0, exMargin: () => 0,
  rubBatchReady: () => true, brokerPicked: () => '', brokerQuote: () => null,
  quoteUsed: () => null, brokerOpts: () => [], brokerRate: () => '100',
  brokerSend: rub => ({sent: rub - rub * .003 - 40, held: rub * .003 + 40,
    ctrl: rub * .001 + 40, ours: rub * .002, ctrlPct: .1, oursPct: .2, fix: 40}),
  walletById: () => null, walletCards: () => '', transferModeBlock: () => '',
  money: String, moneyKop: (v,c) => Number(v).toLocaleString('ru-RU',
    {minimumFractionDigits:2,maximumFractionDigits:2})+(c?' '+c:''), usd: String,
  htmlText: String, num: Number, pct: String,
  avgUsdt: () => 33, approx: () => ({thb: 0}), econ: () => ({sentUsd: 0})};
vm.createContext(ctx);
vm.runInContext(['MF','FLOWSOLE'].map(name=>html.match(new RegExp('^const '+name+'=[^]*?};', 'm'))[0]).join('\n'),ctx);
vm.runInContext(['pendingEx', 's18Sber', 's18AccountIdentity', 's18AccountKey', 's18AccountLabel', 's18Rub', 's18CrmUnavailable', 's18CrmRows',
  's18DateKey', 's18DateLabel', 's18FilteredRows', 's18CrmSection',
  's18ClientRub', 's18ClientTotal', 'brokerSentAmount', 'brokerPlanShares', 'brokerSentParse',
  'brokerSentTimeValue', 'brokerSentTimeParse', 'brokerSentTimeDraft', 'convMargin', 'convMarginBlock'].map(fn).join('\n')+
  '\nlet s18Candidates=[], s18Selected=new Set(), s18SelectedDealId=null;'+
  "let s18Filters={query:'',from:'',to:''},s18Expanded={crm:false,unlinked:false};\n"+stepCode, ctx);
// Глобальные let заполняем внутри контекста: браузер хранит выбор локально.
vm.runInContext(`s18Candidates=${JSON.stringify(ctx.s18Candidates)};s18Selected=new Set([2,3]);s18SelectedDealId=100;`, ctx);
let rendered = vm.runInContext('stepS18()', ctx);
assert.match(rendered, /Сделка #42 · Обмен/);
assert.match(rendered, /Поступление без сделки/);
assert.match(rendered, /Состав пачки · 3 поступл\./);
assert.match(rendered, /Отметьте поступления для этого перевода/);
assert.match(rendered, /Сделки CRM/);
assert.match(rendered, /12\.10, 12:00/);
assert.match(rendered, /Ориентировочная прибыль по сделкам с известными обязательствами/);
assert.match(rendered, /Фикс 40 ₽ за поручение делится по долям/);
assert.match(rendered, /<details class="deal-detail s18-detail"><summary>Расчёт отправки/);
assert.doesNotMatch(rendered, /Объём обмена<\/label><input/);
assert.match(rendered, /Период с <span class="sub2">дд\.мм\.гггг<\/span>/);
assert.match(html, /\.s18-batch-summary\{[^}]*background:#fff/);
assert.match(rendered, /прибыль не считаем — сделки нет/);
const withUnknown = vm.runInContext('convMargin(d,35000,100,s18Candidates)', ctx);
const withoutUnknown = vm.runInContext('convMargin(d,30000,100,[s18Candidates[0]])', ctx);
assert.equal(withUnknown.unlinkedRub, 5000);
assert.equal(withUnknown.crmCost, 150);
assert.ok(Math.abs(withUnknown.profit-withoutUnknown.profit)<1);
assert.ok(withUnknown.profit<100);
// Московский ввод одинаково разбирается в браузере Москвы, Таиланда и UTC.
for(const zone of ['UTC','Europe/Moscow','Asia/Bangkok']){
  process.env.TZ=zone;
  assert.equal(ctx.brokerSentTimeParse('2026-10-13T12:34'),Date.parse('2026-10-13T09:34:00Z'));
  assert.equal(ctx.brokerSentTimeValue(Date.parse('2026-10-13T09:34:56Z')),'2026-10-13T12:34:56');
}
for(const value of ['', '2026-02-30T12:00', '2026-10-13T25:00', '2026-10-13T12:00Z', '1970-01-01T00:00']){
  assert.equal(ctx.brokerSentTimeParse(value),null);
}
const splitCrm = vm.runInContext(`convMargin(d,30000,100,[
  {dealId:42,rub:10000,dealRub:20000,payoutUsdt:150},
  {dealId:42,rub:10000,dealRub:20000,payoutUsdt:150}])`, ctx);
assert.equal(splitCrm.crmCost, 150); // две части одной сделки — одно обязательство
const missingCost = vm.runInContext('convMargin(d,15000,100,[{dealId:43,rub:5000}])', ctx);
assert.equal(missingCost.missingCrm, 1);
assert.ok(missingCost.usdtIn<150); // неизвестная себестоимость не становится прибылью
vm.runInContext("s18Filters.query='Иванов'", ctx);
assert.equal(vm.runInContext('s18FilteredRows(s18Candidates).length', ctx), 1);
vm.runInContext("s18Filters.query='#42'", ctx);
assert.equal(vm.runInContext('s18FilteredRows(s18Candidates).length', ctx), 1);
vm.runInContext("s18Filters.query='';s18Filters.from='2026-10-13'", ctx);
assert.equal(vm.runInContext('s18FilteredRows(s18Candidates).length', ctx), 1);
vm.runInContext("s18Filters.from='';s18Filters.to='2026-10-12'", ctx);
assert.equal(vm.runInContext('s18FilteredRows(s18Candidates).length', ctx), 1);
vm.runInContext("s18Filters.to=''", ctx);
const many = Array.from({length: 25}, (_, i) => ({id: i+10, rub: 100,
  payer: 'Плательщик '+i, date: '2026-10-12T17:31:00'}));
ctx.many = many;
let section = vm.runInContext("s18CrmSection(many,'unlinked','Поступления без сделки',v=>v)", ctx);
assert.match(section, /Показать все \(25\)/);
assert.equal((section.match(/s18ToggleCrm\(/g)||[]).length, 10);
vm.runInContext('s18Expanded.unlinked=true', ctx);
section = vm.runInContext("s18CrmSection(many,'unlinked','Поступления без сделки',v=>v)", ctx);
assert.equal((section.match(/s18ToggleCrm\(/g)||[]).length, 25);
assert.match(section, /Свернуть до 10/);
main.payinParts = [{incId: 'manual:1', amountRub: 10000}];
main.manualBankReceipt = {bank: 'БАНК СГБ', account: '40807810819000000261'};
incomes[0] = {id: 'manual:1', source: 'manual_confirmed', dealId: 100,
  accountKey: 'flow_sole', rub: 10000, grossRub: 10000};
vm.runInContext(`s18Candidates.push({id:4,uuid:'flow4',accountKey:'flow_sole',
  rub:20000,dealId:44,client:'Flow CRM',date:'2026-10-14T12:00:00',
  dealRub:20000,payoutUsdt:150});s18Selected=new Set([4])`, ctx);
rendered = vm.runInContext('stepS18()', ctx);
assert.match(rendered, /СД-100 · Клиент/);
assert.match(rendered, /Подготовка пачки · Flow Sole/);
assert.match(rendered, /Сделка #44 · Flow CRM/);
assert.match(rendered, /Состав пачки · 2 поступл\./);
assert.doesNotMatch(rendered, /Сделка #42|Поступление без сделки/);
main.manualBankReceipt = {bank: 'Банк клиента', account: '40702810123456789012'};
incomes[0].accountKey = 'other:40702810123456789012';
rendered = vm.runInContext('stepS18()', ctx);
assert.match(rendered, /Подготовка пачки · Другой счёт · 40702810123456789012/);
assert.doesNotMatch(rendered, /Сделка #42|Сделка #44|Поступление без сделки/);
incomes[0] = {id: 'sber:main', source: 'sber', dealId: 100, rub: 9930,
  grossRub: 10000};
main.payinParts = [{incId: 'sber:main', amountRub: 10000}];
assert.equal(vm.runInContext('s18Rub(d)', ctx), 9930);
// M13: старый приход без ключа и SQL alias одного физического счёта совместимы.
main.manualBankReceipt = {status:'confirmed',confirmedAt:'2026-10-16',confirmedBy:12,
  actualMode:'flowsole',bankBik:'044525094',account:'40807810819000000261'};
main.rubReceivingAccount={mode:'custom',bik:'044525094',account:'40807810819000000261'};
incomes[0]={id:'manual:1',source:'manual_confirmed',dealId:100,rub:10000,grossRub:10000};
main.payinParts=[{incId:'manual:1',amountRub:10000,crmIncomeId:1}];
assert.equal(vm.runInContext('s18AccountKey(d)',ctx),'flow_sole');
assert.equal(vm.runInContext('s18CrmRows(d).map(x=>x.id).join()',ctx),'4');
// Реальный legacy-приход без связи: объяснение видно, выбрать CRM нельзя.
delete main.payinParts[0].crmIncomeId;
assert.equal(vm.runInContext('s18CrmRows(d).length',ctx),0);
const orphanView=vm.runInContext('stepS18()',ctx);
assert.match(orphanView,/Ручной приход ещё не связан с общим реестром/);
assert.match(orphanView,/Эти рубли можно отправить отдельной пачкой/);
assert.doesNotMatch(orphanView,/Сделка #44|s18ToggleCrm\(4\)/);
main.payinParts[0].crmIncomeId=1;

incomes[0].accountKey='flow_sole';
assert.equal(vm.runInContext('s18CrmRows(d).map(x=>x.id).join()',ctx),'4');
incomes[0].accountKey='bank:044525094:40807810819000000261';
assert.equal(vm.runInContext('s18CrmRows(d).map(x=>x.id).join()',ctx),'4');
main.manualBankReceipt.account='40807810819000000999';
assert.equal(vm.runInContext('s18AccountKey(d)',ctx),null);
delete incomes[0].accountKey;
assert.equal(vm.runInContext('s18CrmRows(d).length',ctx),0);
main.manualBankReceipt.account='40807810819000000261';
incomes[0].accountKey='sber';
assert.equal(vm.runInContext('s18AccountKey(d)',ctx),null);
console.log('s18 CRM income UI: PASS');

// Реальное act(s18): найденная QA смешанная пачка сохраняет ровно 2245,86 USDT.
(async()=>{
  Object.assign(ctx,{STAND:false,document:{getElementById:()=>null},saveNote:()=>{},
    need:()=>false,val:id=>({b0:'Broker',b1:'84.6',b2:'company',b_sent_time:'2026-10-13T12:00:00'}[id]),cleanNum:String,
    now:()=> '16.10, 12:00',demoAllowed:()=>false,log:()=>{},toast:()=>{},
    go:(d,step)=>{d.step=step;}});
  vm.runInContext(html.match(/^async function act\([^]*?^}/m)[0],ctx);
  main.amountRub=192666.30;main.incomeAmount=192666.31;main.brokerSentOverride=190000;
  main.payinParts[0].amountRub=192666.31;
  main.rates.broker=84.6;main.manualBankReceipt.actualAmount=192666.31;
  incomes[0].rub=incomes[0].grossRub=192666.31;
  incomes[0].accountKey='flow_sole';ctx.S.convs=[];
  vm.runInContext("s18Candidates=[{id:4,uuid:'flow4',accountKey:'flow_sole',rub:10000,dealId:null}];s18Selected=new Set([4])",ctx);
  const preview=vm.runInContext('convMargin(d,202666.31,84.6,s18Candidates)',ctx);
  assert.equal(preview.usdtIn,2135.04);
  assert.equal(preview.unlinkedUsdt,110.82);
  ctx.brokerRate=()=>84.6;
  assert.match(vm.runInContext('convMarginBlock(d,202666.31,s18Candidates)',ctx),/110,82 USDT/);
  main.brokerSentOverride=192048.31;
  vm.runInContext("DRAFTS['100|b_sent']='202666,32'",ctx);
  await ctx.act(100,'s18');
  assert.equal(ctx.S.convs.length,0);
  assert.equal(main.brokerSentOverride,192048.31);
  vm.runInContext("DRAFTS['100|b_sent']='190000,00'",ctx);
  assert.doesNotMatch(vm.runInContext('stepS18()',ctx),/id="b_sent_submit"[^>]*disabled/);
  const validFields=ctx.val;
  for(const invalidTime of ['', '2026-02-30T12:00', '2099-01-01T12:00']){
    ctx.val=id=>id==='b_sent_time'?invalidTime:validFields(id);
    await ctx.act(100,'s18');
    assert.equal(ctx.S.convs.length,0);
    assert.equal(vm.runInContext("DRAFTS['100|b_sent_time']",ctx),invalidTime);
    assert.equal(vm.runInContext("DRAFTS['100|b_sent']",ctx),'190000,00');
  }
  ctx.val=validFields;
  await ctx.act(100,'s18');
  const cn=ctx.S.convs[0];
  assert.equal(cn.sentTs,Date.parse('2026-10-13T09:00:00Z'));
  assert.match(cn.at,/13\.10\.2026.*12:00:00.*МСК/);
  assert.equal(vm.runInContext("DRAFTS['100|b_sent_time']",ctx),'2026-10-13T12:00:00');
  assert.equal(main.step,'s18w');assert.equal(cn.sent,190000);
  assert.equal(main.brokerSentOverride,190000);
  assert.equal(vm.runInContext("DRAFTS['100|b_sent']",ctx),undefined);
  assert.deepEqual(Array.from(cn.sources,x=>x.usdt),[2135.04,110.82]);
  assert.equal(cn.sources.reduce((sum,x)=>sum+Math.round(x.usdt*100),0),224586);
  assert.equal(cn.sources[0].usdt,preview.usdtIn);
  assert.equal(cn.sources[1].usdt,preview.unlinkedUsdt);
  const thirds=vm.runInContext('brokerPlanShares([1,1,1],1,1)',ctx);
  assert.deepEqual(Array.from(thirds),[.33,.33,.34]);
  console.log('s18 mixed broker plan conservation: PASS');
})().catch(e=>{console.error(e);process.exitCode=1;});
