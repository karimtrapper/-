const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const html = fs.readFileSync('static/stand/tasks.html', 'utf8');
const pick = name => {
  const match = html.match(new RegExp(`^async function ${name}\\([^]*?^}`, 'm'));
  assert.ok(match, name);
  return match[0];
};
const helpers = html.slice(html.indexOf('const CRM_CLOSE_UI=new Map()'), html.indexOf('async function crmPushClose('));
assert.ok(helpers.startsWith('const CRM_CLOSE_UI='));
const code = `const MANUAL_CLOSE_ERRORS={};
function crmFactsMismatchMessage(){return null;}
function crmCloseReason(){return 'Проверьте факт';}
${helpers}
${pick('crmPushClose')}
${pick('manualCloseSubmit')}
${pick('standCloseLose')}`;

function deferred(){let resolve, reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};}
function fixture(opts={}){
  const items=new Map(), calls=[];
  const storage=opts.storage||{getItem:k=>items.get(k)||null,setItem:(k,v)=>items.set(k,v),removeItem:k=>items.delete(k),
    get length(){return items.size;},key:i=>Array.from(items.keys())[i]||null};
  const d={id:9,step:'s27',manual:false,closed:false,crmDealId:null,managerUserId:3};
  const S={deals:[d],manualCloseDraft:{},manualCloseForm:{}};
  const ctx={S,STAND:true,standClosing:false,standVer:4,standBase:null,standBusy:false,standSaveScheduled:false,
    localStorage:storage, crypto:{randomUUID:()=>`req-${calls.length}`}, Date, Math, JSON, Map,
    setTimeout,clearTimeout,AbortController,render:()=>{},toast:()=>{},htmlText:x=>String(x),
    standManagerIdForTransfer:()=>3,standClone:structuredClone,standWaitSaved:async()=>({ok:true}),
    standSaveError:()=> 'Изменения не сохранены',crmPayloadFinal:()=>({manager_user_id:3}),
    deal:id=>S.deals.find(x=>x.id===id),need:()=>false,manualClosePayload:()=>({crm:{manager_user_id:3},manualOverride:{reason:'test reason'}}),
    standApply:data=>{S.deals=data.deals;},confirm:()=>true,
    fetch:async(url,options)=>{calls.push({url,options});return opts.fetch(url,options,calls);},
  };
  vm.createContext(ctx);vm.runInContext(code,ctx);
  return {ctx,S,d,calls,storage};
}
const closed=(id=41)=>({success:true,closed:true,crmDealId:id,version:5,
  data:{deals:[{id:9,step:'done',closed:true,crmDealId:id}]},request_id:'status-ref'});

(async()=>{
  {
    const pending=deferred();
    const f=fixture({fetch:(url)=>url.endsWith('/check')?{json:async()=>({success:true,ready:true})}:
      url.endsWith('/crm-close')?pending.promise:{json:async()=>closed()}});
    const first=f.ctx.crmPushClose(9,4), second=f.ctx.crmPushClose(9,4);
    await second;
    await new Promise(resolve=>setImmediate(resolve));
    assert.equal(f.calls.filter(x=>x.url.endsWith('/crm-close')).length,1,'double click submits once');
    assert.ok(f.storage.getItem('stand-crm-close-pending:9'),'pending survives reload');
    pending.reject(new Error('timeout'));
    await first;
    assert.equal(f.S.deals[0].crmDealId,41,'server status resolves lost response');
    assert.equal(f.storage.getItem('stand-crm-close-pending:9'),null);
    assert.equal(f.ctx.standClosing,false);
  }
  {
    const shared=new Map();
    const storage={getItem:k=>shared.get(k)||null,setItem:(k,v)=>shared.set(k,v),removeItem:k=>shared.delete(k),
      get length(){return shared.size;},key:i=>Array.from(shared.keys())[i]||null};
    const f=fixture({storage,fetch:(url)=>url.endsWith('/check')?{json:async()=>({success:true,ready:true})}:
      url.endsWith('/crm-close')?Promise.reject(new Error('timeout')):Promise.reject(new Error('offline'))});
    await f.ctx.crmPushClose(9,4);
    assert.ok(storage.getItem('stand-crm-close-pending:9'),'unknown result retains marker');
    assert.match(vm.runInContext('CRM_CLOSE_UI.get(9).message',f.ctx),/пока не подтверждён/);
    const afterReload=fixture({storage,fetch:()=>({json:async()=>closed(52)})});
    await afterReload.ctx.crmCloseRecover(9);
    assert.equal(afterReload.S.deals[0].crmDealId,52,'reload applies authoritative closed board');
    assert.equal(storage.getItem('stand-crm-close-pending:9'),null);
  }
  {
    const f=fixture({fetch:url=>url.endsWith('/check')?{json:async()=>({success:true,ready:true})}:
      url.endsWith('/crm-close')?Promise.reject(new Error('timeout')):
      {json:async()=>({success:true,closed:false,version:4})}});
    await f.ctx.crmPushClose(9,4);
    assert.equal(f.S.deals[0].closed,false);
    assert.match(vm.runInContext('CRM_CLOSE_UI.get(9).message',f.ctx),/не подтверждено/);
    assert.equal(f.storage.getItem('stand-crm-close-pending:9'),null,'confirmed open can be retried');
  }
  {
    const f=fixture({fetch:url=>url.endsWith('/check')?{json:async()=>({success:true,ready:false,
      blockers:[{code:'receipt',message:'Приложите чек выплаты'}]})}:
      {json:async()=>closed()}});
    await f.ctx.manualCloseSubmit(9);
    assert.equal(f.calls.filter(x=>x.url.endsWith('/crm-close')).length,0,'manual blockers prevent submit');
    assert.match(vm.runInContext('CRM_CLOSE_UI.get(9).details[0].message',f.ctx),/чек выплаты/);
    assert.ok(f.calls[0].options.body.includes('manualOverride'),'manual check uses exact payload');
  }
  {
    const f=fixture({fetch:()=>new Promise(()=>{})});
    await assert.rejects(f.ctx.crmCloseFetch('/hung',{},20),/close_timeout/);
    const original=f.ctx.crmCloseFetch;
    f.ctx.crmCloseFetch=(...args)=>original(...args.slice(0,2),20);
    await f.ctx.crmPushClose(9,4);
    assert.equal(f.ctx.standClosing,false,'hung preflight releases close lock');
    assert.match(vm.runInContext('CRM_CLOSE_UI.get(9).message',f.ctx),/Не удалось проверить/);
    f.ctx.crmClosePendingSet(9,'first','generation-a');
    f.ctx.crmClosePendingSet(10,'second','generation-a');
    f.ctx.crmClosePendingClear(9,'first');
    assert.equal(f.ctx.crmClosePendingGet(9),null);
    assert.equal(f.ctx.crmClosePendingGet(10).requestId,'second','other deal marker survives');
  }
  {
    let online=false;
    const f=fixture({fetch:url=>url.endsWith('/check')
      ? online?{json:async()=>({success:true,ready:true,generation:'g1'})}:Promise.reject(new Error('offline'))
      :{json:async()=>({success:true,closed:false})}});
    f.ctx.crmCloseReadiness(f.d);
    await new Promise(resolve=>setImmediate(resolve));
    assert.equal(f.ctx.crmCloseReadiness(f.d).retry,true,'failed readiness is actionable');
    f.ctx.crmCloseUiSet(9,'error','Сохранение отклонено');
    online=true;
    f.ctx.crmCloseCheckRetry(9);
    f.ctx.crmCloseReadiness(f.d);
    await new Promise(resolve=>setImmediate(resolve));
    assert.equal(f.ctx.crmCloseReadiness(f.d).ready,true,'retry refreshes cached check');
    assert.equal(vm.runInContext('CRM_CLOSE_UI.get(9).message',f.ctx),'Сохранение отклонено',
      'poll and check do not erase button error');
  }
  {
    const f=fixture({fetch:()=>({status:409,json:async()=>({success:false,error:'generation_changed',request_id:'reset-ref'})})});
    f.ctx.crmClosePendingSet(9,'old','generation-old');
    await f.ctx.crmCloseRecover(9);
    assert.equal(f.ctx.crmClosePendingGet(9),null,'reset clears stale pending marker');
    assert.equal(f.S.deals[0].closed,false,'reset cannot apply reused deal ID');
  }
  {
    const f=fixture({fetch:()=>new Promise(()=>{})});
    const original=f.ctx.crmCloseFetch;
    f.ctx.crmCloseFetch=(...args)=>original(...args.slice(0,2),20);
    await f.ctx.standCloseLose(9,'Клиент отказался');
    assert.equal(f.ctx.standClosing,false,'hung lose preflight releases lock');
    assert.equal(f.calls.filter(x=>x.url.endsWith('/crm-close-lose')).length,0);
    assert.equal(f.ctx.crmClosePendingGet(9),null,'preflight does not leave pending close');
  }
  {
    const post=deferred();let reads=0;
    const f=fixture({fetch:url=>url.includes('/crm-close-status')
      ? {status:200,json:async()=>++reads===1?{success:true,closed:false,version:4,generation:'g1'}:
          {...closed(71),generation:'g1'}}
      : url.endsWith('/crm-close-lose')?post.promise:Promise.reject(new Error('unexpected route'))});
    f.ctx.crmClosePendingSet(10,'other','g1');
    const first=f.ctx.standCloseLose(9,'Клиент отказался');
    const second=f.ctx.standCloseLose(9,'Клиент отказался');
    await second;await new Promise(resolve=>setImmediate(resolve));
    assert.equal(f.calls.filter(x=>x.url.endsWith('/crm-close-lose')).length,1,'lose double click submits once');
    assert.equal(f.ctx.crmClosePendingGet(9).generation,'g1','lose marker has board generation');
    post.reject(new Error('timeout'));await first;
    assert.equal(f.S.deals[0].crmDealId,71,'lose timeout recovers confirmed close');
    assert.ok(f.calls.some(x=>x.url.includes('expected_generation=g1')),'recovery fences board reset');
    assert.equal(f.ctx.crmClosePendingGet(9),null);
    assert.equal(f.ctx.crmClosePendingGet(10).requestId,'other','other deal marker survives');
    assert.match(f.ctx.crmClosePanel(9),/href="\/crm\?deal=71"/,'success has CRM link');
  }
  {
    let reads=0;
    const f=fixture({fetch:url=>url.includes('/crm-close-status')
      ? ++reads===1?{status:200,json:async()=>({success:true,closed:false,version:4,generation:'g1'})}:
        {status:409,json:async()=>({success:false,error:'generation_changed',request_id:'reset-ref'})}
      : url.endsWith('/crm-close-lose')?Promise.reject(new Error('timeout')):Promise.reject(new Error('unexpected route'))});
    await f.ctx.standCloseLose(9,'Клиент отказался');
    assert.equal(f.S.deals[0].closed,false,'reset cannot claim refusal success');
    assert.equal(f.ctx.crmClosePendingGet(9),null,'reset clears stale refusal marker');
    assert.match(vm.runInContext('CRM_CLOSE_UI.get(9).message',f.ctx),/Доска была обновлена/);
  }
  {
    const f=fixture({fetch:()=>({status:200,json:async()=>({success:true,closed:false,version:5,generation:'g1'})})});
    await f.ctx.standCloseLose(9,'Клиент отказался');
    assert.equal(f.calls.filter(x=>x.url.endsWith('/crm-close-lose')).length,0,'stale reviewed version never submits refusal');
  }
  console.log('reliable CRM close: win/manual/lose timeout, reload, reset, double click, blockers PASS');
})().catch(error=>{console.error(error);process.exitCode=1;});
