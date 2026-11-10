// Приход Сбера выбирается из API; тестовые записи и другие счета не выбираются.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const html = fs.readFileSync('static/stand/tasks.html', 'utf8');
const names = ['incomeRubBasis', 'partRubBasis', 'sberFree', 'payinSum', 'payinIssues', 'payinDone', 'sberTake',
  'rubApiAccount', 'expectOf', 'expectSet', 'payinPool'];
const source = names.map(name => {
  const match = html.match(new RegExp(`^function ${name}\\([^]*?^}`, 'm'));
  assert.ok(match, name);
  return match[0];
}).join('\n');

function fixture(overrides = {}) {
  const deal = {id: 1, code: 'СД-1', client: 'Клиент', step: 's14',
    amountRub: 100000, payinParts: [], log: [], rubReceivingAccount: {mode: 'sber'},
    expect: {amount: 100000, tol: 1000, acc: '…0286 · Сбер',
      account: '40807810938720000286', purpose: 'Договор СД-1'}, ...overrides};
  const S = {deals: [deal], incomes: [], role: 'operator'};
  const events = [];
  const ctx = {S, deal: () => deal, incomes: () => S.incomes,
    MF: {bank: 'ПАО Сбербанк', acc: '40807810938720000286'},
    FLOWSOLE: {bank: 'БАНК СГБ', acc: '40807810819000000261'},
    approx: d => ({pay: d.amountRub, cur: 'rub'}),
    docFields: () => ({purpose: 'Договор СД-1'}), isCrypto: () => false,
    editApply: () => {}, save: () => {}, render: () => {},
    log: (d, message) => d.log.push(message), go: (d, step) => {d.step = step;},
    afterPayin: d => {d.step = 's18'; d.reqTask = 'open';},
    toast: message => events.push(message), money: n => String(n),
    sberText: String, Number, Math, String, Set};
  vm.createContext(ctx); vm.runInContext(source, ctx);
  return {ctx, deal, S, events};
}

function income(id, rub, extra = {}) {
  return {id, rub, source: 'sber', kind: 'банк', acc: '…0286 · Сбер',
    purpose: 'Договор СД-1', payer: 'Клиент', date: '12.10',
    dealId: null, excluded: false, ...extra};
}

{
  const {ctx, deal, S} = fixture();
  S.incomes.push(income('sber:1', 60000), income('sber:2', 40000));
  ctx.sberTake(1, 'sber:1'); ctx.sberTake(1, 'sber:2'); ctx.payinDone(1);
  assert.equal(deal.step, 's18');
  assert.equal(deal.incomeAmount, 100000);
  assert.equal(deal.payinParts.length, 2);
}
{
  const {ctx, deal, S, events} = fixture();
  S.role = 'manager'; S.incomes.push(income('sber:manager', 100000));
  ctx.sberTake(1, 'sber:manager'); ctx.payinDone(1);
  assert.equal(deal.payinParts.length, 0);
  assert.equal(deal.step, 's14');
  assert.match(events.at(-1), /операционист/);
}
{
  const {ctx, deal, S, events} = fixture();
  S.incomes.push(income('sber:3', 100000, {demo: true}));
  assert.doesNotMatch(ctx.payinPool(deal), /Забрать<\/button>/);
  ctx.sberTake(1, 'sber:3');
  assert.equal(deal.payinParts.length, 0);
  assert.match(events.at(-1), /операционист/);
}
{
  const {ctx, deal, S, events} = fixture({rubReceivingAccount: {mode: 'flowsole'}});
  S.incomes.push(income('sber:4', 100000));
  ctx.sberTake(1, 'sber:4');
  assert.equal(deal.payinParts.length, 0);
  assert.match(events.at(-1), /операционист/);
}
{
  const {ctx, deal, S} = fixture();
  S.incomes.push(income('sber:5', 98999));
  ctx.sberTake(1, 'sber:5'); ctx.payinDone(1);
  assert.equal(deal.step, 's14m');
  assert.ok(deal.incomeReview.some(x => x.includes('Недоплата')));
}
assert.doesNotMatch(html, /Зарегистрировать тестовый приход|Создать тестовый приход|DEMO · тестовый приход|Вебхук банка · DEMO/);
assert.doesNotMatch(html, /function (?:incomeExact|incomeOff|sberManual|payinDemo)\(/);
console.log('stand incoming API: 4 сценария PASS');

// Асинхронный список брокера: промежуточный реестр, пустой ответ, retry и смена кошелька.
function deferred(){let resolve;const promise=new Promise(r=>{resolve=r;});return {promise,resolve};}
function incomingFixture(){
  const d={id:1,demoTransfers:false},c={id:7,walletId:'a',txs:[]};
  const S={open:1,role:'operator',convs:[c]},pending=[],renders=[];
  const ctx={S,STAND:true,deal:()=>d,convOf:()=>c,walletById:id=>({addr:id==='a'?'TWalletA':'TWalletB'}),
    txPool:()=>[],txUsed:()=>false,demoAllowed:()=>false,htmlText:String,render:()=>renders.push(ctx.cnvIncomingStatus(ctx.cnvIncomingChoices(d,c))),
    toast:()=>{},fetch:url=>{const next=deferred();pending.push({url,...next});return next.promise;},encodeURIComponent};
  vm.createContext(ctx);
  for(const name of ['cnvIncomingKey','cnvIncomingChoices','cnvIncomingStatus','cnvTxLoad']){
    const match=html.match(new RegExp(`^(?:async )?function ${name}\\([^]*?^}`,'m'));
    assert.ok(match,name);vm.runInContext(match[0],ctx);
  }
  vm.runInContext('let incomingRequest=null, incomingRequestSeq=0;',ctx);
  const finish=(index,data,ok=true)=>pending[index].resolve({ok,json:async()=>data});
  return {ctx,S,c,d,pending,renders,finish};
}
(async()=>{
  const f=incomingFixture(),{ctx,S,c,d,pending,renders,finish}=f;
  assert.equal(ctx.cnvIncomingChoices(d,null).chain.length,0,'без пачки список безопасно пуст');
  assert.equal(ctx.cnvIncomingStatus(ctx.cnvIncomingChoices(d,null),d),'');
  const first=ctx.cnvTxLoad(1);
  assert.match(renders.at(-1),/Обновляем/);
  assert.equal(ctx.cnvTxLoad(1),first,'повторный запрос объединён с текущим');
  assert.equal(pending.length,2);
  finish(0,{success:true,txs:[{id:9,tx_hash:'a'.repeat(64),amount_usdt:100,free_usdt:100}]});
  await new Promise(setImmediate);
  assert.equal(ctx.cnvIncomingChoices({id:1},c).ledger.length,1,'реестр виден до ответа TronScan');
  assert.match(renders.at(-1),/Обновляем/);
  finish(1,{success:true,txs:[],complete:true});await first;
  assert.equal(S.incomingLoadState.status,'ready');
  const refresh=ctx.cnvTxLoad(1);
  assert.equal(ctx.cnvIncomingChoices({id:1},c).ledger.length,1,'список сохранён при обновлении');
  finish(2,{success:true,txs:[]});finish(3,{success:true,txs:[],complete:true});await refresh;
  assert.match(ctx.cnvIncomingStatus(ctx.cnvIncomingChoices({id:1},c)),/не найдено/);
  const failed=ctx.cnvTxLoad(1);
  finish(4,{success:true,txs:[]});finish(5,{success:false,error:'TronScan не ответил'});await failed;
  assert.equal(S.incomingLoadState.status,'error');
  assert.match(ctx.cnvIncomingStatus(ctx.cnvIncomingChoices({id:1},c)),/Повторить загрузку/);
  const retry=ctx.cnvTxLoad(1);
  finish(6,{success:true,txs:[]});finish(7,{success:true,txs:[{hash:'b'.repeat(64),free_usdt:5}],complete:true});await retry;
  assert.equal(S.incomingLoadState.status,'ready');assert.equal(ctx.cnvIncomingChoices({id:1},c).chain.length,1);
  const old=ctx.cnvTxLoad(1);c.walletId='b';
  const fresh=ctx.cnvTxLoad(1);
  finish(10,{success:true,txs:[]});finish(11,{success:true,txs:[],complete:true});await fresh;
  finish(8,{success:true,txs:[{id:99,free_usdt:10}]});finish(9,{success:true,txs:[{hash:'c'.repeat(64),free_usdt:10}],complete:true});await old;
  assert.equal(ctx.cnvIncomingChoices({id:1},c).chain.length,0,'старый ответ не заменил новый кошелёк');
  assert.equal(S.incomingLoadState.key,ctx.cnvIncomingKey(c));
  const partial=ctx.cnvTxLoad(1);
  finish(12,{success:true,txs:[]});finish(13,{success:true,txs:[],complete:false});await partial;
  assert.match(ctx.cnvIncomingStatus(ctx.cnvIncomingChoices({id:1},c)),/неполный/);
  assert.doesNotMatch(ctx.cnvIncomingStatus(ctx.cnvIncomingChoices({id:1},c)),/не найдено/);
  const closed=ctx.cnvTxLoad(1);S.open=null;
  finish(14,{success:true,txs:[]});finish(15,{success:true,txs:[],complete:true});await closed;
  assert.equal(S.incomingLoadFor,null,'после закрытия карточки разрешён новый запрос');
  S.open=1;
  const reopened=ctx.cnvTxLoad(1);
  finish(16,{success:true,txs:[]});finish(17,{success:true,txs:[],complete:true});await reopened;
  assert.equal(S.incomingLoadState.status,'ready');
  const httpError=ctx.cnvTxLoad(1);
  finish(18,{success:true,txs:[]});finish(19,{success:true,txs:[]},false);await httpError;
  assert.equal(S.incomingLoadState.status,'error','HTTP error даже с success=true');
  S.incomingLoadState=null;d.demoTransfers=true;ctx.demoAllowed=()=>true;
  assert.equal(ctx.cnvIncomingStatus(ctx.cnvIncomingChoices(d,c),d),'','demo не ждёт отключённую автозагрузку');
  d.demoTransfers=false;S.role='manager';
  assert.equal(ctx.cnvIncomingStatus(ctx.cnvIncomingChoices(d,c),d),'','другая роль не ждёт отключённую автозагрузку');
  console.log('stand incoming async states PASS');
})().catch(e=>{console.error(e);process.exitCode=1;});
