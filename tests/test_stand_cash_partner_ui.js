const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../static/stand/tasks.html'), 'utf8');
const source = name => html.match(new RegExp(`^(?:async )?function ${name}\\([^\\n]*}\\s*$`, 'm'))?.[0]||
  html.match(new RegExp(`^(?:async )?function ${name}\\([^]*?^}`, 'm'))[0];
const constant = name => html.match(new RegExp(`^const ${name}\\s*=.*;$`, 'm'))[0];
const d = {id:42, type:'Оплата недвижимости', kind:'Лизхолд', payType:'Наличные', step:'s8'};
const inputs = {}, requests = [], closeRequests = [], transitions = [], notices = [];
const context = {
  STAND:true, SCREEN:null, SNAP:null, CLOSE_REASONS:['Клиент отказался'], prompt:()=> '1',
  standCloseLose:(id,reason)=>closeRequests.push([id,reason]),
  PAYIN_TOL:5, SOURCES_PAY:{}, S:{role:'manager'}, DRAFTS:{}, standVer:12,
  standBase:{deals:[structuredClone(d)]},
  CRM_WALLETS:[
    {id:1, address:'valid-a', blockchain:'TRON', accepts_payin:true, active:true},
    {id:2, address:'valid-b', blockchain:'TRON', accepts_payin:true, active:true, not_for_new_deals:true},
    {id:3, address:'valid-c', blockchain:'ETH', accepts_payin:true, active:true},
    {id:4, address:'valid-d', blockchain:'TRON', accepts_payin:true, active:false},
    {id:5, address:'valid-e', blockchain:'TRON', accepts_payin:false, active:true},
  ],
  isCrypto: () => false, addrValid: value => value.startsWith('valid-'),
  moneyKop: (value,currency)=>`${value} ${currency}`,
  money: (value,currency)=>`${value} ${currency}`,
  trow: (label,value)=>`<tr><th>${label}</th><td>${value}</td></tr>`,
  dealWallet: () => null, deal: id => id===d.id?d:null, val: id => inputs[id]||'',
  approx:()=>({pay:100000,thb:40000,sign:'₽'}), rateUnit:()=> '₽/฿', docFields:()=>({}),
  documentPackStale:()=>false, docFileOf:(_,kind)=>({file:kind+'.pdf'}), docExt:()=> 'PDF',
  docHasIssued: deal=>!!deal.docPack,
  docStepActor: deal=>context.S.role==='admin'||context.S.role===(deal.step==='s8'?'manager':'operator'),
  document:{getElementById:()=>null}, log:()=>{}, saveNote:()=>{},
  filesOf:()=>[{}], managerDraftPublishDocs:()=>{}, notificationDeliveryText:()=>'',
  docIssue:()=>{throw new Error('cannot issue a cash pack without meeting details');},
  go:(deal,step)=>{transitions.push([deal.step,step]);deal.step=step;context.save();},
  save:()=>{context.standBase.deals=[structuredClone(d)];},
  standRequireSaved: async () => true,
  standWaitSaved: async () => ({ok:true}),
  standAction: async (endpoint, payload) => {requests.push([endpoint, JSON.parse(JSON.stringify(payload))]);return {success:true};},
  render: () => {}, toast: text => notices.push(text),
};
vm.createContext(context);
vm.runInContext(['FLOW_RUB','FLOW_USDT','FLOW_CASH_PARTNER','CASH_PARTNER_FIELDS','CASH_PARTNER_LENGTHS'].map(constant).concat(
  ['isNativeCashPartner','flowOf','cashPartnerNumbers','cashPartnerWalletTask','cashPartnerWalletChoices',
    'cashPartnerAction','cashPositiveNumber','cashPartnerDate','uniqueWallets','htmlText','jsLiteralAttr',
    'cashPartnerReady','cashPartnerSetupEdit','cashPartnerCanReturn','cashPartnerReturnToManager',
    'cashPartnerSetupBlock','cashPartnerSetupSave','cashPartnerDetails','cashPartnerHandoffRows','cashPartnerHandoffBlock',
    'docSendBlock','tgPayBlock','askClose','act'].map(source)).join('\n'),context);
const s11Start=html.indexOf('  s11:()=>{'), s11End=html.indexOf('  s11b:()=>{',s11Start);
vm.runInContext('function renderCashS11(d){return ({'+html.slice(s11Start,s11End)+'}).s11();}',context);

async function main(){
  for(const kind of ['Лизхолд','Фрихолд','Аренда']){
    const property={...d,kind};
    const route=Array.from(context.flowOf(property));
    assert.deepEqual(route.slice(route.indexOf('s12'), route.indexOf('s22')+1),['s12','s14c','s14','s22']);
    assert.equal(route.includes('s18'), false);
  }
  for(const extra of [{payType:'По реквизитам'},{autoPayment:true},{kind:'ИППС'},{kind:'Личный счёт'},
    {type:'Обмен валюты'},{manual:true},{step:'s14',docPack:{method:'bank'},cashPartner:{name:'Old'}},
    {step:'done',closed:true},{step:'s14',cashPartnerUsdt:true}]){
    assert.equal(context.isNativeCashPartner({...d,...extra}),false,JSON.stringify(extra));
  }
  const meeting={name:'InternalName',location:'Адрес <офиса>',appointmentAt:'2026-11-26T12:30'};
  const legacy={...meeting,contact:'+7 000 000 00 00'};
  d.step='s11';context.S.role='operator';
  const missingSetup=context.renderCashS11(d);
  assert.match(missingSetup,/Вернуть менеджеру/);
  assert.doesNotMatch(missingSetup,/cash_partner_(name|location|appointmentAt)|Создать договор/);
  assert.equal(await context.cashPartnerSetupSave(42),false);
  await context.act(42,'s11');
  assert.match(notices.pop(),/нужны данные встречи от менеджера/);
  await context.cashPartnerReturnToManager(42);
  assert.deepEqual(transitions.pop(),['s11','s8']);
  assert.equal(context.standBase.deals[0].step,'s8');
  assert.match(notices.pop(),/возвращена менеджеру/);
  context.S.role='manager';d.cashPartner=legacy;
  const setup=context.cashPartnerSetupBlock(d);
  assert.deepEqual([...setup.matchAll(/id="cash_partner_(\w+)_42"/g)].map(m=>m[1]),['name','location','appointmentAt']);
  assert.doesNotMatch(setup,/контакт|000 00/iu);
  for(const [key,value] of Object.entries(meeting))inputs['cash_partner_'+key+'_42']=value;
  assert.equal(await context.cashPartnerSetupSave(42),true);
  assert.deepEqual(context.standBase.deals[0].cashPartner,meeting);
  Object.assign(d,{cashPartner:legacy,docPack:{method:'cash'},docParse:true});
  context.save();
  for(const key of Object.keys(meeting))delete inputs['cash_partner_'+key+'_42'];
  assert.doesNotMatch(context.cashPartnerSetupBlock(d),/<input|Сохранить данные встречи/);
  context.S.role='operator';
  assert.equal(await context.cashPartnerSetupSave(42),false);
  context.S.role='manager';
  await context.act(42,'s8');
  assert.deepEqual(transitions.pop(),['s8','s11']);
  assert.equal(context.standBase.deals[0].step,'s11');
  assert.deepEqual(context.standBase.deals[0].cashPartner,legacy);
  d.step='s11';context.S.role='operator';
  const savedSetup=context.cashPartnerSetupBlock({...d,cashPartner:legacy});
  assert.match(savedSetup,/InternalName/);
  assert.doesNotMatch(savedSetup,/контакт|000 00|<input|Вернуть менеджеру/iu);
  Object.assign(d,{step:'s14c',docPack:{method:'cash'},walletId:1});
  const legacyDeal={...d,cashPartner:legacy,rates:{client:2.5}};
  const instructions=context.cashPartnerHandoffBlock(legacyDeal,100000);
  assert.match(instructions,/Куда передать наличные/);
  assert.match(instructions,/Скопировать для клиента/);
  assert.match(instructions,/100000 ₽/);
  assert.match(instructions,/Адрес &lt;офиса&gt;/);
  assert.doesNotMatch(instructions,/Адрес <офиса>/);
  for(const rendered of [instructions,context.tgPayBlock(legacyDeal,'s12'),context.docSendBlock(legacyDeal)]){
    assert.match(rendered,/100000 ₽/);
    assert.match(rendered,/Дата и время встречи/);
    assert.doesNotMatch(rendered,/партн[её]р|InternalName|контакт|000 00/iu);
  }
  context.askClose(42);
  assert.deepEqual(closeRequests.pop(),[42,'Клиент отказался']);
  assert.equal(context.cashPartnerWalletTask(d,'operator'),true,'an inherited wallet does not satisfy the explicit choice');
  assert.equal(context.cashPartnerWalletTask(d,'manager'),false);
  assert.deepEqual(Array.from(context.cashPartnerWalletChoices(d),w=>w.id),[1]);

  const endpoint='/api/stand/payin/cash-partner';
  inputs.cash_receipt_42='100 000,5';
  await context.cashPartnerAction(42,'receive');
  assert.deepEqual(requests.pop(),[endpoint,{dealId:42,op:'receive',amountRub:100000.5,version:12}]);
  assert.equal(context.cashPositiveNumber('1,234',2),null);
  inputs.cash_wallet_42='1';
  await context.cashPartnerAction(42,'wallet');
  assert.deepEqual(requests.pop(),[endpoint,{dealId:42,op:'wallet',walletId:1,version:12}]);
  d.step='s14';d.cashPartnerWalletId=1;
  inputs.cash_rate_42='80,123456';inputs.cash_rate_at_42='2026-11-26T12:30';
  await context.cashPartnerAction(42,'rate');
  assert.deepEqual(requests.pop(),[endpoint,{dealId:42,op:'rate',rate:80.123456,rateAt:'2026-11-26T12:30',version:12}]);

  d.cashPartnerReceipt={amountRub:80000};d.cashPartnerRate={rate:80};
  context.askClose(42);
  assert.equal(closeRequests.length,0,'a deal with accepted cash remains active');
  d.payinHashes=[{hash:'a',amount:400,verified:true,ledgerUseId:1}];
  assert.equal(context.cashPartnerNumbers(d).matched,false,'partial incoming cannot advance');
  d.payinHashes.push({hash:'b',amount:600.000001,verified:true});
  assert.equal(context.cashPartnerNumbers(d).matched,false,'network check without reservation does not fund the deal');
  d.payinHashes[1].ledgerUseId=2;
  assert.equal(context.cashPartnerNumbers(d).matched,true);
  assert.equal(context.cashPartnerNumbers(d).verified,1000.000001);
  d.payinHashes[1].amount=605.000001;
  assert.equal(context.cashPartnerNumbers(d).matched,false,'a gap above the tolerance is checked at transaction precision');
  inputs.cash_unlink_42_b='Другой платёж';
  await context.cashPartnerAction(42,'unlink','b');
  assert.deepEqual(requests.pop(),[endpoint,{dealId:42,op:'unlink',hash:'b',reason:'Другой платёж',version:12}]);
  console.log('cash partner route, explicit wallet, input and verified amount: PASS');
}

main().catch(error=>{console.error(error);process.exitCode=1;});
