const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../static/stand/tasks.html'), 'utf8');

function fn(name) {
  const oneLine = html.match(new RegExp(`^(?:async )?function ${name}\\([^\\n]*\\)\\{[^\\n]*\\}$`, 'm'));
  if (oneLine) return oneLine[0];
  const found = html.match(new RegExp(`^(?:async )?function ${name}\\([^]*?^}`, 'm'));
  assert.ok(found, `Функция ${name} отсутствует`);
  return found[0];
}

function cst(name) {
  const found = html.match(new RegExp(`^const ${name}\\s*=[\\s\\S]*?;`, 'm'));
  assert.ok(found, `Константа ${name} отсутствует`);
  return found[0].replace(/^const /, 'var ');
}

function ctx() {
  const context = {
    STAND_VERIFIED_FLOWS: [['freehold','requisites'],['leasehold','requisites'],['auto','requisites']],
    standMe: 'manager', confirms: [], save: () => {}, render: () => {}, toast: () => {},
    confirm(text) { context.confirms.push(text); return context.accept; },
    jeq: (a,b) => JSON.stringify(a) === JSON.stringify(b),
    htmlText: value => value.replaceAll('"', '&quot;'), SIGN:{rub:'RUB',thb:'THB',usdt:'USDT'},
    S: {draft: {type:'Оплата недвижимости',kind:'Лизхолд',payType:'По реквизитам',mode:'need',cur:'thb'}},
  };
  vm.createContext(context);
  const constants = ['STAND_KIND_CANON','STAND_PAYTYPE_CANON','PAIRS','PAIR_CFG','PAIR_PAYCUR'];
  const functions = ['standFlowCombo','draftComboVerified','canConfirmStandFlow','confirmStandFlow',
    'draftFlowOption','draftFlowChip','draftSetGated','draftSet','pairOf','payWays','askModes','draftPair','exchangeSpec'];
  vm.runInContext([...constants.map(cst), ...functions.map(fn)].join('\n'), context);
  return context;
}

// ── draftComboVerified: чистая логика сверки с кэшем verified-пар ────────

{
  const c = ctx();
  assert.equal(c.draftComboVerified('Оплата недвижимости', 'Фрихолд', 'По реквизитам'), true,
    'Фрихолд + По реквизитам — проверенная комбинация');
  assert.equal(c.draftComboVerified('Оплата недвижимости', 'Лизхолд', 'По реквизитам'), true,
    'Лизхолд + По реквизитам — проверенная комбинация');
}
{
  const c = ctx();
  assert.equal(c.draftComboVerified('Оплата недвижимости', 'Аренда', 'Наличные'), false,
    'Аренда + Наличные — непроверенная комбинация');
  assert.equal(c.draftComboVerified('Оплата недвижимости', 'Фрихолд', 'Крипта'), false,
    'Фрихолд + Крипта — непроверенная комбинация');
  assert.equal(c.draftComboVerified('Обмен валюты', null, 'По реквизитам'), false,
    'Обмен валюты — тип сам по себе не проверен, даже с По реквизитам');
}
console.log('draftComboVerified: OK');

{
  const c = ctx();
  const draft=c.S.draft;
  assert.match(c.draftFlowChip(draft,'payType','Наличные'),/unchecked-flow/);
  assert.doesNotMatch(c.draftFlowChip(draft,'payType','Наличные'),/disabled/);
  c.draftSetGated('payType','Наличные');
  assert.match(c.confirms[0], /Наличные.*Лизхолд/);
  assert.equal(draft.payType,'По реквизитам');
  assert.equal(draft.unverified_flow_confirmation,undefined);

  c.accept=true;
  c.draftSetGated('payType','Наличные');
  assert.equal(draft.payType,'Наличные');
  assert.equal(JSON.stringify(draft.unverified_flow_confirmation),'["leasehold","cash"]');
  c.draftSetGated('kind','Аренда');
  assert.equal(JSON.stringify(draft.unverified_flow_confirmation),'["rental","cash"]');
  c.draftSetGated('type','Обмен валюты');
  assert.equal(JSON.stringify(draft.unverified_flow_confirmation),'["exchange","cash"]');
  c.accept=false;
  c.draftPair('USDT → THB');
  assert.equal(draft.pair,'RUB → THB');
  assert.equal(draft.payType,'Наличные');
  assert.equal(JSON.stringify(draft.unverified_flow_confirmation),'["exchange","cash"]');
  c.accept=true;
  c.draftPair('USDT → THB');
  assert.equal(draft.payType,'Крипта');
  assert.equal(JSON.stringify(draft.unverified_flow_confirmation),'["exchange","crypto"]');
  c.draftSetGated('type','Оплата недвижимости');
  assert.equal(draft.pair,null);
  assert.equal(draft.cur,'thb');
  assert.equal(JSON.stringify(draft.unverified_flow_confirmation),'["rental","crypto"]');
  const warningCount=c.confirms.length;
  c.draftSetGated('type','Оплата авто');
  assert.equal(draft.payType,'По реквизитам');
  assert.equal(draft.unverified_flow_confirmation,null);
  assert.equal(c.confirms.length,warningCount);
}
{
  const c=ctx();
  c.standMe='operator';
  assert.match(c.draftFlowChip(c.S.draft,'payType','СБП'),/disabled/);
  c.draftSetGated('payType','СБП');
  assert.equal(c.S.draft.payType,'По реквизитам');
  assert.equal(c.confirms.length,0);
}

function newDealCtx() {
  const context = { now: () => 0, SOURCES: { tg: 'Telegram' }, log: () => {} };
  vm.createContext(context);
  vm.runInContext(fn('newDeal'), context);
  context.S = { seq: 1000, deals: [] };
  return context;
}

{
  const context = newDealCtx();
  const deal = context.newDeal({ type: 'Оплата недвижимости', kind: 'Аренда', payType: 'Наличные',
    source: 'tg', step: 's5', unverified_flow_confirmation: ['rental','cash'], noSave: true });
  assert.equal(JSON.stringify(deal.unverified_flow_confirmation),'["rental","cash"]');
}
{
  const context = newDealCtx();
  const deal = context.newDeal({ type: 'Оплата недвижимости', kind: 'Фрихолд', payType: 'По реквизитам',
    source: 'tg', step: 's5', noSave: true });
  assert.equal(deal.unverified_flow_confirmation, undefined);
}

console.log('ALL OK');
