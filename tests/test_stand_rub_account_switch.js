// Переключение рублёвого счёта на копии уже сохранённой сделки.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const html = fs.readFileSync('static/stand/tasks.html', 'utf8');
const fn = name => {
  const match = html.match(new RegExp(`^(?:async )?function ${name}\\([^\\n]*\\)\\{(?:[^\\n]*}|[^]*?^})`, 'm'));
  assert.ok(match, name);
  return match[0];
};
const constants = html.slice(html.indexOf('const MF='), html.indexOf('/* Паспорт знакомого клиента', html.indexOf('const MF=')));
const oldState = JSON.parse(JSON.stringify({deals: [{id: 1, code: 'SYN-1', step: 's11',
  rates: {client: 2.6}, rubReceivingAccount: {mode: 'flowsole'},
  docFields: {payTo: 'ООО «ЭМ ЭФ КОРПОРЕЙШН» · ПАО Сбербанк · р/с 40807810938720000286',
    purpose: 'Оплата по договору', fio: 'Ручная правка'},
  expect: {acc: '…0286 · Сбер', bank: 'ПАО Сбербанк', account: '40807810938720000286',
    amount: 100000, tol: 500, purpose: 'Назначение из выписки'}}]}));
const deal = oldState.deals[0];
const fields = {};
const ctx = vm.createContext({S: oldState, deal: () => deal,
  docHasIssued: d => Boolean(d.docVersion || d.docPack),
  STAND:true, SCREEN:null, SNAP:null, standMe:'operator', standMeId:7, standBusy:false,
  standPush:false, standVer:1, standBase:null, DRAFTS:{}, DOC_REISSUE_FORMS:{},
  DOC_REQ:['fio','passNo','object','amountThb','rate','amountPay'], DOC_SRC:{purpose:'пишет операционист'},
  STAND_DOC_AGENT_META:{profiles:{mf_corp:{name:'MF Corporation Company Limited',reg:'0835565024547',director:'Miss Katika Sakornnoi'},
    flow_sole:{name:'Flow Sole Company Limited',reg:'284530232-000',director:'Mr. Souvahn Phanthavong'}},
    accounts:{'bank:044525094:40807810819000000261':'flow_sole'}},
  document: {getElementById: id => Object.hasOwn(fields, id) ? {value: fields[id]} : null},
  fake: () => ({}), approx: () => ({pay: 100000}), parsed: () => '',
  prevPassport: () => ({}), isCrypto: () => false, payCur: () => 'rub', payinWallet: () => null,
  stepWho: d => d.step==='s12'?'manager':'operator',
  htmlText: s => String(s??'').replace(/"/g,'&quot;'), exchangeSpec: () => null,
  standRequireSaved:async () => true, standClone:structuredClone,
  standApply:data => Object.assign(deal,data.deals[0]),
  go: (d,step) => {d.step=step;}, log: () => {}, toast: () => {},
  save: () => {ctx.saves++;}, render: () => {}, saves:0});
vm.runInContext(constants + ['standDocAgent', 'docFields', 'expectOf', 'rubReceivingAccountSave',
  'rubReceivingBankLabel', 'manualBankDocsMismatch', 'payinS11Fields', 'documentPackStale',
  'docReq', 'docPurposeOptional', 'docIssueVersion', 'docAccountChangeAvailable', 'docStepActor', 'docCanReopen',
  'docFormReceivingMode', 'docSelectReceivingAccount', 'docFormFields', 'docFormProblem',
  'docFieldSave', 'docIssue'].map(fn).join('\n'), ctx);
const run = source => vm.runInContext(source, ctx);

// Старая сделка получает актуальные реквизиты без миграции JSON и потери ручных полей.
assert.match(run('docFields(S.deals[0]).payTo'), /ФЛОУ СОЛЕ КО., ЛТД.*40807810819000000261.*044525094/);
assert.equal(run('expectOf(S.deals[0]).acc'), 'Flow Sole (СГБ) …0261');
assert.equal(run('expectOf(S.deals[0]).account'), '40807810819000000261');
assert.equal(run('expectOf(S.deals[0]).bank'), 'Московский филиал "БАНК СГБ" г. Москва');
assert.equal(run('expectOf(S.deals[0]).purpose'), 'Назначение из выписки');
assert.equal(run('expectOf(S.deals[0]).amount'), 100000);
assert.equal(run('docFields(S.deals[0]).fio'), 'Ручная правка');

run("rubReceivingAccountSave(1, 'sber')");
assert.match(run('docFields(S.deals[0]).payTo'), /ЭМ ЭФ КОРПОРЕЙШН.*40807810938720000286/);
assert.equal(run('expectOf(S.deals[0]).acc'), '…0286 · Сбер');
run("rubReceivingAccountSave(1, 'flowsole')");
assert.match(deal.docFields.payTo, /ФЛОУ СОЛЕ.*40807810819000000261/);

Object.assign(fields, {rub_bank_1: 'Банк Тест', rub_account_1: '40702810900000012345',
  rub_corr_1: '30101810000000000000', rub_bik_1: '044525225',
  rub_recip_name_1: 'ООО ТЕСТ', rub_recip_inn_1: '7700000000', rub_recip_kpp_1: '770101001'});
run("rubReceivingAccountSave(1, 'custom')");
assert.match(run('docFields(S.deals[0]).payTo'), /ООО ТЕСТ.*Банк Тест.*40702810900000012345/);
// 20-значный счёт — ровно порог для сокращения середины (Карим, живой стенд, 17.10)
assert.equal(run('expectOf(S.deals[0]).acc'), 'Банк Тест · 40702810…00012345');
assert.equal(run('expectOf(S.deals[0]).account'), '40702810900000012345');
assert.equal(run('expectOf(S.deals[0]).purpose'), 'Назначение из выписки');
assert.equal(run('docFields(S.deals[0]).fio'), 'Ручная правка');
fields.rub_bank_1 = '';
run("rubReceivingAccountSave(1, 'custom')");
assert.equal(deal.rubReceivingAccount.bank, '', 'очистка поля сохраняется');

assert.match(html, /fld\('purpose','Назначение перевода — клиент впишет его в платёжное поручение'/);
assert.doesNotMatch(html, /Назначение платежа в Сбер — клиент впишет его в перевод/);
assert.equal(run("docReq(deal(1)).includes('purpose')"), true);

// Перевыпуск старого пакета с реквизитами только в снимке договора.
Object.assign(deal, {
  type:'Оплата недвижимости', kind:'Фрихолд', payType:'По реквизитам', step:'s11',
  docVersion:2, docPack:{version:2, agent:'mf_corp', agreementNumber:'MF-123', amount:100000, transfer:1000, rate:100},
  docFields:{fio:'Ручная правка', amountPay:100000, amountThb:1000, rate:100,
    payTo:'ООО «ЭМ ЭФ КОРПОРЕЙШН» · ПАО Сбербанк · р/с 40807810938720000286',
    purpose:'По текущему договору'},
  amountRub:100000, invoiceUsd:1000, rates:{client:100},
});
delete deal.rubReceivingAccount;
const oldFields = structuredClone(deal.docFields);
const saves = ctx.saves;
assert.match(run("payinS11Fields(deal(1),null,true)"), /<label class="fl" for="rub_receiving_1">Куда клиент переводит рубли<\/label>/);
assert.match(run("payinS11Fields(deal(1),null,true)"), /<option value="" selected>Счёт из выпущенного пакета/);
assert.equal(run("docFormFields(deal(1)).payTo"), oldFields.payTo);
assert.equal(run("docReq(deal(1)).includes('purpose')"), true);
ctx.DRAFTS['1|df_purpose']='Черновик назначения по старым реквизитам';
ctx.DRAFTS['1|df_fio']='Черновик ФИО';
run("docSelectReceivingAccount(1,'flowsole')");
assert.equal(ctx.DRAFTS['1|df_purpose'], undefined);
assert.equal(ctx.DRAFTS['1|df_fio'], 'Черновик ФИО');
assert.equal(run("docFormReceivingMode(deal(1))"), 'flowsole');
assert.equal(run("docReq(deal(1),'flowsole').includes('purpose')"), false);
assert.match(run("payinS11Fields(deal(1),null,true,docFormReceivingMode(deal(1)))"), /value="flowsole" selected/);
let preview = run("docFormFields(deal(1),docFormReceivingMode(deal(1)))");
assert.match(preview.payTo, /ФЛОУ СОЛЕ.*40807810819000000261/);
assert.equal(preview.agent, 'Flow Sole Company Limited');
assert.equal(preview.agentReg, '284530232-000');
assert.equal(preview.agentDir, 'Mr. Souvahn Phanthavong');
assert.equal(preview.purpose, '');
assert.equal(preview.amountPay, 100000);
assert.equal(preview.amountThb, 1000);
assert.equal(preview.rate, 100);
assert.equal(preview.fio, 'Ручная правка');
assert.equal(ctx.saves, saves);
assert.deepEqual(deal.docFields, oldFields);
assert.equal(deal.rubReceivingAccount, undefined);
assert.equal(deal.expect.purpose, 'Назначение из выписки');
ctx.DRAFTS['1|df_purpose']='Черновик назначения для Flow Sole';
run("docSelectReceivingAccount(1,'flowsole')");
assert.equal(ctx.DRAFTS['1|df_purpose'], 'Черновик назначения для Flow Sole');
run("docSelectReceivingAccount(1,'')");
assert.equal(ctx.DRAFTS['1|df_purpose'], undefined);
assert.equal(run("docFormReceivingMode(deal(1))"), '');
assert.equal(run("docFormFields(deal(1)).purpose"), oldFields.purpose);

deal.rubReceivingAccount={mode:'flowsole'};
assert.equal(run("docReq(deal(1)).includes('purpose')"), false);
assert.equal(run("docFormFields(deal(1)).purpose"), oldFields.purpose);
deal.docFields.purpose='Оплата по агентскому договору № MF-123, НДС не облагается';
assert.equal(run("docFormFields(deal(1)).purpose"), '');
deal.docFields.purpose='Оплата по агентскому договору № MF-999, НДС не облагается';
assert.equal(run("docFormFields(deal(1)).purpose"), deal.docFields.purpose);
deal.docFields.purpose=oldFields.purpose;
delete deal.rubReceivingAccount;

// Возврат из ожидания доступен исполнителю до фиксации оплаты.
deal.step='s12';
assert.equal(run("docCanReopen(deal(1))"), false);
ctx.standMe='manager';
assert.equal(run("docCanReopen(deal(1))"), true);
deal.step='s14';
assert.equal(run("docCanReopen(deal(1))"), false);
ctx.standMe='operator';
deal.assigneeAdminId=8;
assert.equal(run("docCanReopen(deal(1))"), false);
ctx.standMe='admin';
assert.equal(run("docCanReopen(deal(1))"), true);
ctx.standMe='operator';
deal.assigneeAdminId=7;
assert.equal(run("docCanReopen(deal(1))"), true);
deal.files={clientPayinReceipt:[{file:'proof.pdf'}]};
assert.equal(run("docCanReopen(deal(1))"), false);
delete deal.files;
oldState.incomes=[{dealId:1}];
assert.equal(run("docCanReopen(deal(1))"), false);
oldState.incomes=[];
deal.outgoingOrderAt=123;
assert.equal(run("docCanReopen(deal(1))"), false);
delete deal.outgoingOrderAt;

(async () => {
  deal.step='s11';
  run("docSelectReceivingAccount(1,'flowsole')");
  preview=run("docFormFields(deal(1),docFormReceivingMode(deal(1)))");
  const requests=[];
  ctx.fetch=async (_url,options)=>{
    requests.push(JSON.parse(options.body));
    return {status:400, json:async()=>({success:false,detail:'Проверьте пакет'})};
  };
  deal.docVersion=3;
  await ctx.docIssue(1,preview,[],'','flowsole');
  assert.equal(requests.length,0,'a local draft of an earlier version cannot authorize a switch');
  deal.docVersion=2;
  await ctx.docIssue(1,preview,[],'','flowsole');
  assert.equal(requests[0].docFields.purpose,'');
  assert.equal(requests[0].receivingAccountMode,'flowsole');
  assert.equal(requests[0].expectedDocVersion,2);
  assert.equal(deal.rubReceivingAccount,undefined);
  assert.deepEqual(deal.docFields,oldFields);
  assert.equal(run("docFormReceivingMode(deal(1))"),'flowsole');
  fields.df_purpose='  Оплата инвойса 123 по согласованию с банком  ';
  const manual=run("docFieldSave(1,'flowsole')");
  assert.equal(manual.F.purpose,'Оплата инвойса 123 по согласованию с банком');
  await ctx.docIssue(1,manual.F,manual.ch,'','flowsole');
  assert.equal(requests[1].docFields.purpose,manual.F.purpose);
  assert.equal(ctx.DRAFTS['1|df_purpose'],fields.df_purpose,'validation failure preserves the entered purpose');
  assert.deepEqual(deal.docFields,oldFields);
  ctx.fetch=async (_url,options)=>{
    requests.push(JSON.parse(options.body));
    const saved=Object.assign({},deal,{rubReceivingAccount:{mode:'flowsole'},docVersion:3,
      docFields:{...preview,purpose:'Оплата по новому договору'},expect:{purpose:'Оплата по новому договору'}});
    return {status:200,json:async()=>({success:true,data:{deals:[saved]},version:2})};
  };
  await ctx.docIssue(1,preview,[],'','flowsole');
  assert.equal(deal.docFields.purpose, 'Оплата по новому договору');
  assert.equal(deal.rubReceivingAccount.mode, 'flowsole');
  assert.equal(deal.step, 's11b');
  assert.equal(deal.invoiceUsd,1000);
  assert.equal(deal.amountRub,100000);
  console.log('rub account switch UI: PASS');
})().catch(error=>{console.error(error);process.exitCode=1;});
