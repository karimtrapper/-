const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync('static/stand/tasks.html','utf8');
const start=html.indexOf('const DOC_PARSE_STARTED=new Map();');
const end=html.indexOf('function filesOf(d,k)',start);
assert(start>0 && end>start,'docparse UI helpers present');
const ctx={PARSE_SLOT:{pass:'passport',inv:'invoice',spa:'spa'},STAND:true,
 DOC_PARSE_AVAILABLE:true,filesOf:()=>[{}],esc:s=>s};
vm.runInNewContext(html.slice(start,end),ctx);
const timeout=ctx.docParseErrorText('timeout');
assert.match(timeout,/90 секунд/);
assert.match(timeout,/попробуйте ещё раз или заполните поля вручную/);
const partial={id:1,docParseState:'частично',docParse:{fields:{client_name_ru:'Тестов Иван'},
 ok:['passport'],failed:[{slot:'invoice',error:'timeout'}]}};
const line=ctx.docParseLine(partial);
assert.match(line,/Паспорт — распознан/);
assert.match(line,/Инвойс —/);
assert.match(line,/90 секунд/);
assert.match(line,/Тестов Иван/);
const running=ctx.docParseLine({id:1,docParseState:'идёт'});
assert.match(running,/docParseTimer-1/);
console.log('docparse timeout and partial result UI: PASS');

// Exercise the response handler as well as its rendered state.
const parse=html.match(/^async function docParse\([^]*?^}/m)[0];
const dataUrl=html.match(/^function dataUrlBlob\([^]*?^}/m)[0];
const png='data:image/png;base64,'+Buffer.from('\x89PNG\r\n\x1a\nmock').toString('base64');
const deal={id:7,kind:'Фрихолд',files:{pass:[{data:png,file:'p.png'}],inv:[{data:png,file:'i.png'}]}};
const handler={PARSE_SLOT:{pass:'passport',inv:'invoice',spa:'spa'},DOC_PARSE_STARTED:new Map(),
 deal:()=>deal,filesOf:(d,k)=>d.files[k]||[],dataUrlBlob:null,FormData,Blob,Uint8Array,
 atob:s=>Buffer.from(s,'base64').toString('binary'),Date,now:()=>123,
 fetch:async()=>({ok:true,json:async()=>({success:true,fields:{client_name_ru:'Тестов Иван'},
   warnings:[],parsed_slots:['passport'],failed:[{slot:'invoice',error:'timeout'}]})}),
 setInterval:()=>1,clearInterval:()=>{},document:{getElementById:()=>null},
 save:()=>{},render:()=>{},toast:()=>{},log:()=>{},DRAFTS:{},DOC_PARSE_AVAILABLE:true};
vm.runInNewContext(dataUrl+'\n'+parse,handler);
handler.docParse(7,true).then(()=>{
 assert.equal(deal.docParseState,'частично');
 assert.deepEqual(Array.from(deal.docParse.ok),['passport']);
 assert.equal(deal.docParse.failed[0].slot,'invoice');
 assert.equal(deal.docParse.fields.client_name_ru,'Тестов Иван');
 console.log('docparse response partial success: PASS');
}).catch(e=>{console.error(e);process.exitCode=1});
