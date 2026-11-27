// Слияние независимых действий; конфликт денег не должен продвигать шаг частично.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const html=fs.readFileSync('static/stand/tasks.html','utf8');
const source=n=>html.match(new RegExp('^function '+n+'\\([^]*?^}','m'))[0];
const ctx={STAND_SHARED:['deals','seq','notes','incomes']};vm.createContext(ctx);
vm.runInContext(source('jeq')+'\n'+source('standMerge'),ctx);
const clone=structuredClone,base={deals:[{id:1,step:'s5',quotes:[{rate:85}],log:[]}],seq:1};
function merge(changeMine,changeTheirs){const mine=clone(base),theirs=clone(base);changeMine(mine.deals[0]);changeTheirs(theirs.deals[0]);return JSON.parse(JSON.stringify(ctx.standMerge(base,mine,theirs)));}
let r=merge(d=>{d.quotes=[{rate:86}];d.step='s6';d.log.push({text:'sent'});},d=>d.log.push({text:'requisites'}));
assert.equal(r.data.deals[0].quotes[0].rate,86);assert.equal(r.data.deals[0].step,'s6');
assert.deepEqual(r.data.deals[0].log,[{text:'requisites'},{text:'sent'}]);assert.deepEqual(r.conflicts,[]);
r=merge(d=>{d.quotes=[{rate:86}];d.step='s6';},d=>{d.quotes=[{rate:87}];});
assert.equal(r.data.deals[0].step,'s5','конфликт курса отменяет также переход');
assert.equal(r.data.deals[0].quotes[0].rate,87);assert.equal(r.conflicts.length,1);
r=merge(d=>{d.transfer={addr:'A',amount:100};},d=>{d.transfer={addr:'B',amount:200};});
assert.deepEqual(r.data.deals[0].transfer,{addr:'B',amount:200});assert.equal(r.conflicts.length,1);
r=merge(d=>{d.quotes=[{rate:86}];},d=>{d.quotes=[{rate:86}];});assert.deepEqual(r.conflicts,[]);
const b=clone(base),mine=clone(base),theirs=clone(base);
mine.deals[0].quotes=[{rate:86}];theirs.deals.push({id:2,step:'s5',client:'New'});
r=ctx.standMerge(b,mine,theirs);assert.equal(r.data.deals.length,2);assert.equal(r.data.deals[0].quotes[0].rate,86);
// Удаление против редактирования не воскрешает серверную запись автоматически.
r=ctx.standMerge(b,mine,{deals:[],seq:1});assert.equal(r.data.deals.length,0);assert.equal(r.conflicts.length,1);
// Локальное удаление одного поля не удаляет независимую серверную правку.
r=merge(d=>delete d.quotes,d=>d.comment='server');assert.equal(r.data.deals[0].quotes,undefined);assert.equal(r.data.deals[0].comment,'server');
r=merge(d=>{d.rates={rubUsdt:'82,45'};d.quotes=[{rate:'82,45'}];},
  d=>{d.rates={client:'91'};d.step='s8';});
assert.equal(r.data.deals[0].rates.rubUsdt,'82,45');
assert.equal(r.data.deals[0].rates.client,'91');
assert.equal(r.data.deals[0].step,'s8');
assert.deepEqual(r.conflicts,[]);
{
  const base={deals:[],seq:1,incomes:[{id:'first',dealId:null},{id:'second',dealId:null}]};
  const local={id:2,code:'СД-2',client:'Same',amountRub:35000,creationKey:'first',
    payinParts:[{incId:'first'}]};
  const server={...local,id:3,code:'СД-3'};
  const mine={deals:[local],seq:2,incomes:[{id:'first',dealId:2},{id:'second',dealId:null}]};
  const theirs={deals:[server],seq:3,incomes:[{id:'first',dealId:3},{id:'second',dealId:null}]};
  const replay=ctx.standMerge(base,mine,theirs);
  assert.deepEqual(JSON.parse(JSON.stringify(replay.data)),theirs,
    'a replay keeps the accepted card and income even if its card number was reassigned');
  const distinct={deals:[{...local,creationKey:'second',payinParts:[{incId:'second'}]}],seq:2,
    incomes:[{id:'first',dealId:null},{id:'second',dealId:2}]};
  const collision={deals:[{...server,id:2,code:'СД-2'}],seq:2,
    incomes:[{id:'first',dealId:2},{id:'second',dealId:null}]};
  const savedBoth=ctx.standMerge(base,distinct,collision);
  assert.equal(savedBoth.data.deals[0].creationKey,'first');
  assert.equal(savedBoth.data.deals[1].creationKey,'second');
  assert.equal(savedBoth.data.deals[1].id,3);
  assert.equal(savedBoth.data.incomes[0].dealId,2);
  assert.equal(savedBoth.data.incomes[1].dealId,3);
}
console.log('board merge: independent edits, append-only log, atomic conflicts PASS');

vm.runInContext(source('standApply'), ctx);
ctx.load = () => ({deals:[], seq:0, notes:[], incomes:[]});
ctx.migrate = data => data;
ctx.crmDraftActive = null;
ctx.crmDraftLive = new Map([[7, {values:{mfInvoiceThb:'16000'}}]]);
const localDraft = {id:7, code:'СД-7', manualNew:true, creationKey:'draft-key'};
ctx.S = {edit:7, deals:[localDraft], seq:7};
ctx.standApply({deals:[{id:7, creationKey:'other-key'}], seq:8, notes:[{text:'server note'}]});
assert.equal(ctx.S.edit, 9);
assert.equal(ctx.S.deals[0], localDraft);
assert.equal(ctx.S.deals[1].creationKey, 'other-key');
assert.equal(ctx.S.notes[0].text, 'server note');
assert.deepEqual(ctx.crmDraftLive.get(9), {values:{mfInvoiceThb:'16000'}});
ctx.standApply({deals:[{id:10, creationKey:'draft-key', originMode:'manual'}], seq:10});
assert.equal(ctx.S.edit, 10);
assert.equal(ctx.S.deals.length, 1);
assert.equal(ctx.S.deals[0].originMode, 'manual');
assert.deepEqual(ctx.crmDraftLive.get(10), {values:{mfInvoiceThb:'16000'}});
