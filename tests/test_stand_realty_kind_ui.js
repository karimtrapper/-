const fs = require('fs');
const vm = require('vm');
const html = fs.readFileSync('static/stand/tasks.html', 'utf8');
const start = html.indexOf('const pendingRealtyKinds=new Set();');
const end = html.indexOf('\nfunction docIssuedTitle(d,k){', start);
const mergeStart = html.indexOf('function standMerge(base,mine,theirs){');
const mergeEnd = html.indexOf('\nfunction standSnapshot(){', mergeStart);
const approxStart = html.indexOf('function freeholdApprox(d){');
const approxEnd = html.indexOf('\nfunction approx(d){', approxStart);
if (start < 0 || end < 0 || mergeStart < 0 || mergeEnd < 0 || approxStart < 0 || approxEnd < 0)
  throw new Error('realty-kind UI code not found');
let resolveRequest;
const scheduled = [];

const context = vm.createContext({
  STAND: true,
  S: {role: 'manager', open: 1532, view: 'deal', deals: []},
  standMe: 'manager',
  toastMessages: [],
  toastMessages: [],
  toast(message) { context.toastMessages.push(message); },
  setTimeout(callback) { scheduled.push(callback); return scheduled.length; },
  fetch(url, options) {
    context.request = {url, options};
    return new Promise(resolve => { resolveRequest = resolve; });
  },
});
vm.runInContext(`
  const STAND_SHARED=['deals'];
  let standBusy=false,standPush=false,standSaveScheduled=false,standClosing=false,standVer=1;
  let standGetEtag='etag',standBase=null;
  let S=globalThis.S;
  let renderCount=0,lastControl='';
  function render(){renderCount++;lastControl=dealRealtyKindControl(S.deals[0]);}
  function standClone(value){return JSON.parse(JSON.stringify(value||{}));}
  function jeq(a,b){return JSON.stringify(a)===JSON.stringify(b);}
  function deal(id){return S.deals.find(item=>item.id===id);}
  function standSnapshot(){return standClone({deals:S.deals});}
  function standApply(data){S.deals=standClone(data.deals||[]);}
  function standPull(){globalThis.didPull=true;}
  function standSave(){globalThis.didSave=true;}
  function htmlText(value){return String(value??'');}
`+html.slice(mergeStart, mergeEnd)+'\n'+html.slice(start, end), context);

const liveShape = {
  id: 1532, client: 'Synthetic client', isTask: true, autoPayment: false, type: 'Оплата недвижимости',
  kind: 'Лизхолд', step: 's5', closed: false,
  amountRub: 5000000, rates: {at: 1795509184493, rubUsdt: '83'},
  quotes: [{dir: 'rub', rate: 83}], pay: {}, docs: {}, files: {}, issued: {},
  payinParts: [], payinHashes: [], log: [],
};
context.S.deals = [liveShape];
if (!context.canSetRealtyKind(liveShape)) throw new Error('SD-1532 early state should be editable');
if (context.canSetRealtyKind({...liveShape, autoPayment: true})) throw new Error('auto payment must be read-only');
if (context.canSetRealtyKind({...liveShape, amountThb: 1000})) throw new Error('settled amount must be read-only');
if (context.canSetRealtyKind({...liveShape, rates: {...liveShape.rates, usdtThb: '34'}}))
  throw new Error('THB quote must be read-only');
context.S.role = 'operator';
if (context.canSetRealtyKind(liveShape)) throw new Error('operator must be read-only');

context.S.role = 'manager';
const earlyNoQuote = {...liveShape, step: 's4', rates: {}, quotes: []};
context.S.deals = [earlyNoQuote];
vm.runInContext('standBase=standClone({deals:S.deals})', context);
vm.runInContext('render()', context);
const pending = context.setDealRealtyKind(1532, 'Фрихолд');
if (!vm.runInContext('lastControl', context).includes('disabled')) throw new Error('select should lock during PATCH');
context.S.deals[0].client = 'queued local edit';
vm.runInContext('standPush=true', context);
const serverDeal = {...earlyNoQuote, kind: 'Фрихолд', amountRub: 5000000,
  freeholdClientInput: 'sum'};
resolveRequest({ok: true, status: 200, json: async () => ({
  success: true, version: 2, data: {deals: [serverDeal]}, notification_delivery: [],
})});
pending.then(applied => {
  if (!applied) throw new Error('PATCH should apply');
  if (context.S.deals[0].kind !== 'Фрихолд') throw new Error('updated kind should be visible');
  if (context.S.deals[0].freeholdClientInput !== 'sum') throw new Error('freehold amount mode was lost');
  if (context.S.deals[0].client !== 'queued local edit') throw new Error('queued local edit was lost');
  const control = vm.runInContext('lastControl', context);
  if (control.includes('disabled') || !control.includes('selected'))
    throw new Error('select should rerender unlocked with the updated value');
  if (!vm.runInContext('standSaveScheduled', context))
    throw new Error('queued local edit should be scheduled for save');
  if (scheduled.length !== 1) throw new Error('queued save should be scheduled exactly once');
  if (vm.runInContext('renderCount', context) < 2) throw new Error('successful PATCH should rerender the card');
  context.isCrypto = () => false;
  context.num = value => Number(value) || null;
  context.ippsTariff = () => 0;
  context.freeholdSend = value => value;
  vm.runInContext(html.slice(approxStart, approxEnd), context);
  const shown = vm.runInContext('freeholdApprox(S.deals[0])', context);
  if (shown.pay !== 5000000 || shown.approx !== null)
    throw new Error('Freehold overview should display the preserved 5M RUB request');
  console.log('test_stand_realty_kind_ui.js: OK');
}).catch(error => { console.error(error); process.exitCode = 1; });
