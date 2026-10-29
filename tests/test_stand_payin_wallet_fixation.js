// Кошелёк прихода фиксируется на s11 даже без касания select, а payinSettle не пишет его вместе с переходом шага.
const assert=require('node:assert/strict'), fs=require('node:fs'), vm=require('node:vm');
const html=fs.readFileSync('static/stand/tasks.html','utf8');
function fn(name){
  const one=html.match(new RegExp(`^(?:async )?function ${name}\\([^\\n]*\\)\\{[^\\n]*\\}$`,'m'));
  return (one||html.match(new RegExp(`^(?:async )?function ${name}\\([^]*?^}`,'m')))[0];
}
const calls=[];
const ctx={S:{role:'operator',convs:[],deals:[]},DRAFTS:{},STAND:true,SCREEN:false,SNAP:false,
  document:{getElementById:()=>null},saveNote:()=>{},toast:()=>{},render:()=>{},
  save:()=>calls.push('save'),
  deal:id=>ctx.S.deals.find(d=>d.id===id),val:()=>'',log:()=>{},
  isCrypto:d=>d.payType==='Крипта',docFieldSave:id=>{ctx.deal(id).docFields={};return [];},
  docReq:()=>[],DOC_LABEL:{},
  docIssue:async(id)=>{calls.push('docIssue');},
  PAYIN_TOL:.005,approx:()=>({pay:100}),payinGot:()=>100,payinForeign:()=>false,
  payinDefaultWallet:(net,d)=>({id:d.type==='Обмен валюты'?'6':'5'}),
  walletPurpose:d=>d.type==='Обмен валюты'?'exchange':'realty',
  go:(d,step)=>{d.step=step;calls.push('go:'+step);},afterPayin:d=>{d.step='s22';calls.push('go:s22');},
  money:String,rnd2:n=>n,standPayinCommit:async()=>true,
};
vm.createContext(ctx);
for(const name of ['walletPurpose','act','payinSettle'])vm.runInContext(fn(name),ctx);

(async()=>{
  // 1. s11: select не трогали -> walletId по умолчанию записан и сохранён ДО выпуска документов
  for(const type of ['Оплата недвижимости','Обмен валюты']){
    const d={id:1,step:'s11',payType:'Крипта',type,kind:'Лизхолд',rates:{}};
    ctx.S.deals=[d];calls.length=0;
    await ctx.act(1,'s11');
    assert.equal(d.walletId,type==='Обмен валюты'?'6':'5');
    assert.deepEqual(calls,['save','docIssue'],'сначала сохранение кошелька, потом выпуск документов');
  }
  // 2. s11: явный выбор оператора не перезаписывается
  const chosen={id:2,step:'s11',payType:'Крипта',type:'Оплата недвижимости',kind:'Лизхолд',rates:{},walletId:'9'};
  ctx.S.deals=[chosen];calls.length=0;await ctx.act(2,'s11');
  assert.equal(chosen.walletId,'9');
  // 3. s11: рублёвая сделка кошелька не получает
  const rub={id:3,step:'s11',payType:'Банк',type:'Оплата недвижимости',kind:'Лизхолд',rates:{}};
  ctx.S.deals=[rub];await ctx.act(3,'s11');
  assert.equal(rub.walletId,undefined);
  // 4. payinSettle с уже записанным walletId: переход шага без изменения кошелька
  const hs=[{hash:'a'.repeat(64),amount:100}];
  const fixed={id:4,step:'s14',type:'Оплата недвижимости',walletId:'5',pay:{},payinHashes:hs};
  ctx.S.deals=[fixed];await ctx.payinSettle(4,true);
  assert.equal(fixed.step,'s22');assert.equal(fixed.walletId,'5');
  // 5. повторный запуск payinSettle по уже записанным payinHashes (хеш привязан, шаг не сдвинулся)
  const stuck={id:5,step:'s14',type:'Оплата недвижимости',pay:{},payinHashes:hs};
  ctx.S.deals=[stuck];await ctx.payinSettle(5,true);
  assert.equal(stuck.step,'s22');
  assert.equal(stuck.walletId,'5','зависшая сделка без walletId: только дефолт сервера, первичная фиксация');
  // 6. недобор: ничего не пишем, шаг на месте
  ctx.payinGot=()=>40;
  const short={id:6,step:'s14',type:'Оплата недвижимости',pay:{},payinHashes:hs};
  ctx.S.deals=[short];await ctx.payinSettle(6,true);
  assert.equal(short.step,'s14');assert.equal(short.walletId,undefined);
  console.log('payin wallet fixation: PASS');
})().catch(e=>{console.error(e);process.exitCode=1;});
