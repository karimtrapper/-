// Менеджер видит владельца шага и останавливает отправку только после подтверждения.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const html=fs.readFileSync('static/stand/tasks.html','utf8');
const source=name=>{
  const match=html.match(new RegExp('^(?:async )?function '+name+'\\([^]*?^}','m'));
  assert.ok(match,'Нет функции '+name);return match[0];
};
const calls=[];
const deal={id:1484,step:'s23',kind:'Фрихолд',reqTask:'done',ippsPayoutOrder:{confirmedAt:'now'},pay:{}};
let accepted=false;
const ctx={STAND:true,SCREEN:null,SNAP:null,standVer:5,S:{role:'manager'},
  STAND_EMPLOYEES:[{id:17,display_name:'Артём',role:'operator'}],
  deal:id=>id===1484?deal:null,
  confirm:()=>accepted,
  standAction:async (path,body)=>{calls.push({path,body});deal.step='s22';return {success:true};},
  render:()=>{},toast:()=>{},save:()=>{throw Error('Обычный PUT недопустим')},
};
vm.createContext(ctx);
vm.runInContext(['employeeName','reqReopen','logWhen','quoteSet'].map(source).join('\n'),ctx);
assert.equal(ctx.employeeName('17'),'Артём');
assert.match(html,/Сейчас отправка с кошелька — от вас ничего не нужно/);
assert.match(html,/Ваша параллельная задача: реквизиты для оплаты/);
assert.ok(!html.includes("toast('В прототипе не реализовано — в жизни уходит запрос клиенту')"));
assert.equal(ctx.logWhen({ts:'2026-10-13T04:35:00Z',at:1791866100000}).includes('T'),false);
(async()=>{
  await ctx.reqReopen(1484,'правка менеджера');
  assert.equal(calls.length,0);
  assert.equal(deal.step,'s23');
  accepted=true;
  await ctx.reqReopen(1484,'правка менеджера');
  assert.equal(calls.length,1);
  assert.equal(calls[0].path,'/api/stand/payto/reopen');
  assert.equal(calls[0].body.version,5);
  const quoteDeal={id:1490,step:'s6',quotes:[],rates:{client:'91'}};
  ctx.deal=id=>id===1490?quoteDeal:deal;
  ctx.cpById=id=>id==='tradex'?{id,name:'Tradex'}:null;
  ctx.val=()=> '82,45';ctx.cleanNum=value=>value;
  ctx.standAction=async (path,body)=>{calls.push({path,body});return null;};
  await ctx.quoteSet(1490,'tradex','rub');
  assert.equal(calls[1].path,'/api/stand/quote');
  assert.equal(calls[1].body.rate,'82,45');
  assert.equal(quoteDeal.rates.client,'91');
  assert.deepEqual(quoteDeal.quotes,[],'При отказе поле остаётся, локальная сделка не переписана');
  console.log('release minor UI: PASS');
})().catch(error=>{console.error(error);process.exitCode=1;});
