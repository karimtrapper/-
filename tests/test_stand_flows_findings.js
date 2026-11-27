// Причины серверных отказов и ручное решение о переводе без времени.
const assert=require('node:assert/strict'), fs=require('node:fs'), vm=require('node:vm');
const html=fs.readFileSync(require('node:path').join(__dirname,'../static/stand/tasks.html'),'utf8');
function fn(name){return html.match(new RegExp(`^(?:async )?function ${name}\\([^]*?^}`,'m'))[0];}
(async()=>{
  const notices=[];
  const ctx={toast:s=>notices.push(s),standWaitSaved:async()=>({ok:false,error:'Причина от сервера'}),
    S:{role:'operator'},sendList:d=>d.transfer.sends,htmlText:String,usd:String,
    moneyKop:(n,s)=>`${Number(n)} ${s}`,
    dealWallet:()=>null,walletAddressPair:()=>''};
  vm.createContext(ctx);
  for(const n of ['standSaveError','standRequireSaved','outgoingPickState','outgoingPickList','outgoingReviewBlock'])vm.runInContext(fn(n),ctx);
  assert.equal(await ctx.standRequireSaved('Общая ошибка'),false);
  assert.equal(notices.pop(),'Причина от сервера');
  assert.equal(ctx.standSaveError({error:'code',detail:'Пояснение'},'Общая ошибка'),'Пояснение');
  assert.equal(ctx.standSaveError({ok:true},'Нет поручения'),'Нет поручения');
  ctx.standWaitSaved=async()=>{throw new Error('timeout');};
  assert.equal(await ctx.standRequireSaved(),false);
  assert.match(notices.pop(),/15 секунд/);
  ctx.standWaitSaved=async()=>({ok:true});
  assert.equal(await ctx.standRequireSaved(),true);
  const d={id:1,managerUserId:1,outgoingReview:{scanStatus:'complete'},transfer:{amount:100,sends:[{
    status:'confirmed',verifiedAmount:100,timeUnverified:true}]}};
  assert.match(ctx.outgoingReviewBlock(d),/Сеть подтвердила адреса и сумму, но не вернула время перевода/);
  assert.match(ctx.outgoingReviewBlock(d),/Ввести хеш вручную/);
  assert.match(ctx.outgoingReviewBlock(d),/автоматическое закрытие остановлено/);
  ctx.S.role='teodor';assert.equal(ctx.outgoingReviewBlock(d),'');
  // После отказа сохранения ни одно зависимое действие не вызывает API.
  ctx.S.role='operator';ctx.STAND=true;ctx.standClosing=false;ctx.standWaitSaved=async()=>({ok:false,error:'Конкретный отказ'});
  const requests=[];
  ctx.fetch=(...args)=>{requests.push(args);throw new Error('Нельзя вызывать API после отказа сохранения');};
  ctx.crmCloseFetch=ctx.fetch;
  ctx.deal=()=>d;ctx.standClone=structuredClone;ctx.crmPayloadFinal=()=>({});
  ctx.standManagerIdForTransfer=()=>1;
  ctx.standVer=1;
  ctx.standLastSaveResult=null;
  vm.runInContext(html.match(/^function docIssueVersion[^\n]+/m)[0],ctx);
  ctx.crmCloseRequestId=()=>'synthetic';
  const closeStates=[];
  ctx.crmCloseUiSet=(id,kind,message)=>closeStates.push({id,kind,message});
  for(const name of ['freeholdLossAck','prepayAction','docIssue','crmEvidence','crmPushClose','standCloseLose']){
    vm.runInContext(fn(name),ctx);
    await ctx[name](1,ctx.standVer);
    if(name==='crmPushClose'||name==='standCloseLose'){
      assert.deepEqual(closeStates.pop(),{id:1,kind:'error',message:'Конкретный отказ'},name);
      assert.equal(closeStates.pop()?.kind,'pending',name);
    }else{
      assert.equal(notices.pop(),'Конкретный отказ',name);
    }
    assert.equal(ctx.standClosing,false);
    assert.deepEqual(requests,[],name);
  }
  console.log('flows findings UI: PASS');
})().catch(e=>{console.error(e);process.exitCode=1;});
