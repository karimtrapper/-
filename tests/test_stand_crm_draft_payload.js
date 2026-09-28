// Synthetic contract between stand_state and the deferred CRM close payload.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync('static/stand/tasks.html', 'utf8');
const fn = name => {
  const hit = html.match(new RegExp(`^function ${name}\\([^]*?^}`, 'm'));
  assert.ok(hit, `missing ${name}`);
  return hit[0];
};
const constants = ['IPPS_TARIFFS','PAYIN_CRM','PAYOUT_CRM'].map(name => {
  const hit = html.match(new RegExp(`^const ${name}\\s*=[\\s\\S]*?;`, 'm'));
  assert.ok(hit, `missing ${name}`);
  return hit[0];
}).join('\n');
const ctx = {
  econ: d => ({payin: (d.amountUsdt||0) + (d.payinExtra||[]).reduce((s,x)=>s+(x.amount_usdt||0),0),cost:10,sentThb:100}),
  isCrypto: d => d.payType==='Крипта',
  num: x => x == null || x==='' ? null : Number(x),
  mfList: d => d.mfPayout||[],
  refById: () => null,
  freeholdSend: (x,t) => x*(1+t.percent/100)+t.fixed,
  Math, JSON,
};
vm.createContext(ctx);
vm.runInContext(constants+'\n'+['crmNet','crmPayload'].map(fn).join('\n'),ctx);
const base = {
  client:'synthetic',manager:'Марина',type:'Оплата недвижимости',kind:'Аренда',
  payType:'По реквизитам',amountRub:100000,amountUsdt:1000,incomeAmount:100000,
  amountThb:35000,rates:{broker:100,usdtThb:33,sellRate:32.5,client:32.5},
  spread:null,companyPct:0,agents:[],object:'rental unit',
  payinParts:[{uuid:'synthetic-sber',amountRub:100000,fee:960,net:99040,kind:'acquiring'}],
  payinExtra:[{method:'crypto_direct',amount_usdt:200,tx_hashes:[{hash:'synthetic-in',amount_usdt:200}]}],
  payinHashes:[],mfPayout:[{hash:'synthetic-out',net:'trc20',amount:10}],
  docLinks:{invoice:'local-invoice',contract:'local-contract',payment:'local-payment'},
};
const rental = ctx.crmPayload(base);
assert.equal(rental.deal_kind,'mf_realty');
assert.equal(rental.payin_amount_usdt,1000,'extra must be added by server once');
assert.equal(rental.payin_extra[0].amount_usdt,200);
assert.equal(rental.payin_parts[0].amount_rub,100000);
assert.equal(rental.payin_parts[0].net_rub,99040);
assert.equal(rental.sell_rate_thb_usdt,32.5);
assert.equal(rental.company_percent,0,'explicit zero is not a default');
assert.equal(rental.doc_invoice_url,'local-invoice');
const leasehold=ctx.crmPayload({...base,kind:'Лизхолд'});
assert.equal(leasehold.deal_kind,'mf_realty');
for(const [tariff,pct,sent] of [['bank',0.8,45410],['soft',1.5,45725]]){
  const free=ctx.crmPayload({...base,kind:'Фрихолд',ippsTariff:tariff,invoiceUsd:45000,mfPayout:[]});
  assert.equal(free.deal_kind,'mf_freehold');
  assert.equal(free.transfer_fee_percent,pct);
  assert.equal(free.transfer_sent_usd,sent);
  assert.equal(free.invoice_amount_usd,45000);
}
const noTariff=ctx.crmPayload({...base,kind:'Фрихолд',ippsTariff:null,invoiceUsd:45000,mfPayout:[]});
assert.equal(noTariff.transfer_fee_percent,null);
assert.equal(noTariff.transfer_sent_usd,null);
const custom=ctx.crmPayload({...base,type:'Обмен валюты',kind:'',custom:true,
  payinParts:[],payinExtra:[],agents:[{name:'Synthetic Agent',tier:1,comp:'revshare',percent:10}],
  customData:{payinCurrency:'RUB',payinAmount:92000,payinRate:92,payinUsdt:1000,
    payoutCurrency:'THB',payoutAmount:30000,payoutRate:31.5,payoutUsdt:952.38,
    payinMethod:'sber_reqs',payoutMethod:'transfer',payinTxHash:'',
    date:'',notes:'custom fixture',netProfit:42.86}});
assert.equal(custom.is_custom,true);
assert.equal(custom.deal_kind,undefined,'CRM custom has no new deal_kind');
assert.equal(custom.custom_payin_rate,92);
assert.equal(custom.custom_payout_rate,31.5);
assert.equal(custom.payin_amount_usdt,1000);
assert.equal(custom.payout_amount_usdt,952.38);
assert.equal(custom.profit_usdt,47.620000000000005);
assert.equal(custom.net_profit_usdt,42.86);
assert.equal(custom.agents[0].percent,10);
const founder=ctx.crmPayload({...base,type:'Обмен валюты',kind:'',payType:'Крипта',
  paySrc:'founder',amountUsdt:3300,amountThb:100000,
  payout:{thb:100000,settledByPayin:true,hashes:[{hash:'f'.repeat(64),amount:3205.13,
    from_address:'synthetic-founder',to_address:'synthetic-client'}]}});
assert.equal(founder.payout_source,'founder_personal');
assert.equal(founder.needs_reimbursement,false);
assert.equal(founder.payout_tx_hashes[0].from_address,'synthetic-founder');
console.log('T17 rental/freehold/custom/multi-payin payload: PASS');
