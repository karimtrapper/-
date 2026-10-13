// Слияние независимых действий; конфликт денег не должен продвигать шаг частично.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const html=fs.readFileSync('static/stand/tasks.html','utf8');
const source=n=>html.match(new RegExp('^function '+n+'\\([^]*?^}','m'))[0];
const ctx={STAND_SHARED:['deals','seq','notes']};vm.createContext(ctx);
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
console.log('board merge: independent edits, append-only log, atomic conflicts PASS');
