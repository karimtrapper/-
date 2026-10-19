// Настоящий HTTP, отдельные cookie и VM вкладок; барьеры задают порядок ответов.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const html=fs.readFileSync('static/stand/tasks.html','utf8');
const started=Date.now(),trace=(what,x)=>console.log(JSON.stringify({ms:Date.now()-started,what,...x}));
const cookies=JSON.parse(process.env.BOARD_RACE_COOKIES),base=process.env.BOARD_RACE_URL;
// marina создаёт новую сделку с комбинацией, несущественной для гонки/мерджа
// (предмет этого теста), поэтому её сессия — admin, чтобы не упереться в
// гейт непроверенных флоу (тип сделки + способ Pay-In); newDeal() ниже также
// несёт unverified_confirmed:true.
const adminCookie=process.env.BOARD_RACE_ADMIN_COOKIE||cookies[0];
function source(name,async=false){const m=html.match(new RegExp('^'+(async?'async ':'')+'function '+name+'\\([^]*?^}','m'));assert.ok(m,name);return m[0];}
function barrier(){let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};}
function tab(role,cookie){
 const ctx={S:{role,deals:[],notes:[],seq:1471},STAND_SHARED:['deals','notes','seq'],
  standBusy:false,standPush:false,standSaveScheduled:false,standClosing:false,standLastSaveResult:{ok:true},
  standVer:null,standBase:null,lastPointer:0,brokerSentSubmitPointer:false,location:{},Date,setTimeout,clearTimeout,
  load:()=>({deals:[],notes:[],seq:1471}),migrate:s=>s,standTyping:()=>false,render:()=>{},
  toast:message=>trace(role+':toast',{message}),hold:null,
  fetch:async(url,options={})=>{
   const response=await fetch(base+url,{...options,headers:{...options.headers,Cookie:cookie}});
   const data=await response.json();
   trace(role+':'+(options.method||'GET'),{status:response.status,version:data.version,ids:(data.data?.deals||[]).map(d=>d.id),error:data.error});
   if(ctx.hold&&(!options.method||options.method==='GET')){ctx.hold.ready.resolve();await ctx.hold.release.promise;}
   return {status:response.status,json:async()=>data};
  }};
 vm.createContext(ctx);
 vm.runInContext(['standClone','jeq','standMerge','standSnapshot','standApply'].map(n=>source(n)).concat(['standPull','standSave','standWaitSaved'].map(n=>source(n,true))).join('\n'),ctx);
 return ctx;
}
const newDeal=()=>({id:1472,code:'СД-1472',client:'Concurrency synthetic',type:'Обмен валюты',
 payType:'По реквизитам',amountRub:100000,step:'s5',closed:false,log:[],quotes:[{dir:'rub',cpId:'broker',name:'Broker',rate:85}],
 unverified_confirmed:true});
(async()=>{
 const marina=tab('manager',adminCookie),artem=tab('operator',cookies[1]);
 await Promise.all([marina.standPull(true),artem.standPull(true)]);
 if(process.argv[2]==='late_poll'){
  marina.hold={ready:barrier(),release:barrier()};
  const poll=marina.standPull(false);await marina.hold.ready.promise;
  // Другая роль сохраняет свою доску, первая создаёт сделку со старой версией.
  await artem.standSave();
  marina.S.deals.push(newDeal());marina.S.seq=1472;
  await marina.standSave();await marina.standWaitSaved();
  assert.equal(marina.S.deals.length,1);
  marina.hold.release.resolve();await poll;marina.hold=null;
  const response=await fetch(base+'/api/stand/state',{headers:{Cookie:cookies[0]}}),persisted=await response.json();
  trace('after late GET',{uiIds:marina.S.deals.map(d=>d.id),serverIds:persisted.data.deals.map(d=>d.id)});
  assert.equal(persisted.data.deals.length,1,'сервер хранит созданную сделку');
  assert.equal(marina.S.deals.length,1,'поздний поллинг не должен удалять сделку из UI');
 }else{
  marina.S.deals.push(newDeal());marina.S.seq=1472;await marina.standSave();
  await artem.standPull(true);
  // Менеджер публикует независимую заметку, оператор отправляет курс и шаг.
  marina.S.deals[0].log.push({text:'Manager note',role:'manager'});await marina.standSave();
  assert.equal(marina.standLastSaveResult.ok,true);
  artem.S.deals[0].quotes.push({dir:'thb',cpId:'coins',name:'Coins',rate:33});
  // Saving a quote draft is separate from the server quote handoff.
  artem.S.deals[0].step='s5';artem.S.deals[0].log.push({text:'Курсы отданы менеджеру',role:'operator'});
  await artem.standSave();await artem.standWaitSaved();
  const response=await fetch(base+'/api/stand/state',{headers:{Cookie:cookies[0]}}),persisted=await response.json();
  trace('after conflict',{deal:persisted.data.deals[0]});
  assert.equal(persisted.data.deals[0].quotes.find(q=>q.dir==='thb')?.rate,33,'независимая правка курса не должна пропадать');
  assert.ok(persisted.data.deals[0].log.some(e=>e.text.endsWith('Manager note')));
 }
})().catch(e=>{console.error(e);process.exitCode=1;});
