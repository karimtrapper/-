// Static synthetic parity: core functions are generated verbatim from CRM.
// No app import, browser, credentials or network access.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('static/stand/crm-draft-core.js', 'utf8');
const context = {window:{}, console, Set, URL, Number, String, Math, Promise,
  setTimeout, clearTimeout};
vm.createContext(context);
vm.runInContext(source, context);

function fakeRoot() {
  const ids = new Map();
  for (const id of ['sberKindSelect','sberIncomesAvail','sberPartsList','sberPartsTotal',
    'sberManualAmount','sberManualNote','mfPayoutPicker','mfPayoutPickerList',
    'mfPayoutPickerSum','mfPayoutTxPoolBox','mfPayoutSearch']) {
    ids.set(id,{value:'',style:{display:'none'},innerHTML:'',textContent:''});
  }
  const form = {payin_amount_rub:{value:''},payin_rate_rub_usdt:{value:'80'},
    payin_amount_usdt:{value:''}};
  return {ids, form, root:{getElementById:id=>ids.get(id) || null,
    querySelector:selector=>selector==='[name="payin_amount_rub"]'
      ? form.payin_amount_rub : selector==='[name="payin_amount_usdt"]'
        ? form.payin_amount_usdt : null}};
}

(async () => {
  const {ids,form,root} = fakeRoot();
  const rows = [
    {uuid:'a',kind:'acquiring',gross_rub:266000,amount_rub:263446.40,
      fee_rub:2553.60,merchant:'1234',operation_date:'2026-09-28T08:00:00Z'},
    {uuid:'b',kind:'transfer',amount_rub:100000,payer:'Test',
      operation_date:'2026-09-27T08:00:00Z'},
  ];
  const urls=[];
  const core=context.window.createCrmDraftCore(root, {
    form,editingDealId:null,
    fetch:async url=>{urls.push(url);return {json:async()=>({incomes:rows})};},
    toast:()=>{}, escapeHtml:String, formatDate:()=>'',
    calculateProfit:()=>{}, realtyPayinRecalc:()=>{},realtyPayoutRecalc:()=>{},
  });
  await core.sberLoadIncomes();
  assert.match(ids.get('sberIncomesAvail').innerHTML,/266/);
  assert.match(ids.get('sberIncomesAvail').innerHTML,/100/);
  await core.sberKindChanged('acquiring');
  assert.match(urls.at(-1),/kind=acquiring/);
  await core.sberKindChanged('transfer');
  assert.match(urls.at(-1),/kind=transfer/);
  await core.sberKindChanged('');
  assert.doesNotMatch(urls.at(-1),/kind=/);
  core.sberAddIncome('a');
  core.sberAddIncome('b');
  assert.equal(core.sberPartsSum(),366000);
  assert.equal(form.payin_amount_rub.value,'366000.00');
  assert.equal(form.payin_amount_usdt.value,'4575.00');
  assert.match(ids.get('sberPartsList').innerHTML,/комиссия 2/);
  assert.match(ids.get('sberPartsTotal').textContent,/на счёт/);
  core.sberRemovePart(0);
  assert.equal(core.sberPartsSum(),100000);
  assert.match(ids.get('sberIncomesAvail').innerHTML,/266/);

  core.mfPayoutTxOptions=[
    {tx_hash:'h1',amount_usdt:50,to_address:'TAAAA',timestamp:1},
    {tx_hash:'h2',amount_usdt:70,to_address:'TBBBB',timestamp:2},
  ];
  assert.equal(core.mfPayoutVisible().length,2);
  ids.get('mfPayoutSearch').value='TAAAA';
  assert.equal(core.mfPayoutVisible().length,1);
  core.mfPayoutCheckAll(true);
  assert.match(ids.get('mfPayoutPickerSum').textContent,/1.*50/);
  core.mfPayoutCheckAll(false);
  assert.equal(ids.get('mfPayoutPickerSum').textContent,'Ничего не отмечено');
  console.log('CRM draft generated Sber/MF core: PASS');
})().catch(error=>{console.error(error);process.exitCode=1;});
