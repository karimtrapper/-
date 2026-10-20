const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../static/stand/tasks.html'), 'utf8');
function source(name, async = false) {
  const re = new RegExp('^' + (async ? 'async ' : '') + 'function ' + name + '\\([^]*?^}', 'm');
  const match = html.match(re);
  assert.ok(match, `${name} missing`);
  return match[0];
}

// Та же сборка зависимостей, что test_stand_manual_close_screen.js (задача 5) —
// manualCloseScreen и всё, что оно реально вызывает при рендере.
const SCRIPT = [
  source('htmlText'), source('jsLiteralAttr'), source('num'), source('hashSum'),
  source('txShort'), source('explorer'), source('moneyKop'), source('usd'), source('money'),
  source('isCrypto'), source('payCur'), source('exchangeSpec'), source('payinParts'),
  source('refAgents'), source('econ'),
  source('refSignal'), source('agentsBlock'),
  source('managerDraftDocTarget'), source('fileValid'), source('filesOf'), source('fileBlock'),
  source('hashShareOf'), source('hashCell'),
  source('payoutHuman'), source('clientRubPaid'), source('mfList'),
  source('txPoolInit'), source('txPool'), source('txUsed'),
  source('manualCloseFormState'), source('manualCloseScreen'),
].join('\n');

const SOURCES_PAY = {
  ipps: {t: 'Баланс IPPS · MF Corp'}, cash: {t: 'Касса · партия налички'},
  scb: {t: 'Счёт SCB · MF Corp'}, coins: {t: 'Coins / Bitazza'},
  founder: {t: 'Кошелёк фаундера'}, client: {t: 'USDT клиенту на кошелёк'},
};

function makeCtx(deal, preview) {
  const S = {deals: [deal], incomes: [], role: 'admin', manualCloseForm: {}};
  const ctx = {
    S, SOURCES_PAY,
    render: () => {}, toast: () => {}, fetch: () => Promise.reject(new Error('not used in render')),
    // crmPreviewFor's own correctness (the real /api/stand/crm-preview fetch +
    // cache wrapper) is already exercised elsewhere (dealSummaryBlock's s27
    // use) - stubbed here the same way test_stand_manual_close_submit.js
    // stubs crmPayloadFinal, so this test is scoped to realtySection's own
    // consumption of {data:{profit_usdt}}/{error}, not crmPreviewFor itself.
    crmPreviewFor: () => preview || {pending: true},
  };
  vm.createContext(ctx);
  vm.runInContext(SCRIPT, ctx);
  return ctx;
}

// СД-1489-подобная сделка: шаги s4-s12 пройдены, инвойс/курсы/назначение/перевод/
// документы уже на доске (как описал координатор) - застряла на аренда+наличные.
function realtyKnownDeal() {
  return {id: 1489, code: 'СД-1489', client: 'Synthetic Rental', type: 'Оплата недвижимости',
    kind: 'Аренда', step: 's14', payType: 'Наличные', amountUsdt: null, amountRub: null,
    incomeAmount: null, payinHashes: [], payout: {}, agents: [],
    amountThb: 50000, companyPct: 1, rates: {usdtThb: 36.0, client: 35.0},
    payTo: {purpose: 'Оплата аренды виллы, авг 2026'},
    mfPayout: [{hash: 'b'.repeat(64), net: 'TRC20', amount: 1388.89}],
    docs: {inv: true, receipt: true}};
}

// Тот же тип сделки, но инвойс/курсы/назначение ещё не внесены - ранний случай без
// каких-либо realty-фактов на доске.
function realtyMissingDeal() {
  return {id: 1490, code: 'СД-1490', client: 'Synthetic Rental Missing', type: 'Оплата недвижимости',
    kind: 'Аренда', step: 's14', payType: 'Наличные', amountUsdt: null, amountRub: null,
    incomeAmount: null, payinHashes: [], payout: {}, agents: [],
    amountThb: null, companyPct: null, rates: {}, payTo: {}, mfPayout: [], docs: {}};
}

function main() {
  // T1: денежные поля доступны прямо в ручном переносе, без сохранения
  // непроверенной комбинации через обычный редактор сделки.
  {
    const ctx = makeCtx(realtyKnownDeal());
    const out = ctx.manualCloseScreen(ctx.S.deals[0]);
    assert.ok(out.includes('Инвойс и курс'), 'ожидали блок «Инвойс и курс» для realty-сделки');
    assert.ok(/50.*000.*฿|฿.*50.*000/.test(out) || out.includes('50000'),
      'ожидали сумму инвойса на экране');
    assert.ok(out.includes('36'), 'ожидали курс покупки на экране');
    assert.ok(out.includes('id="mc_invoiceThb"') && out.includes('id="mc_buyRate"') &&
      out.includes('id="mc_sellRate"') && out.includes('id="mc_companyPercent"'),
      'инвойс, курсы и комиссия должны редактироваться в ручном переносе');
    assert.ok(out.includes('id="mc_payin_amount_usdt"'),
      'фактический приход USDT нужен до расчёта прибыли');
    assert.ok(out.includes('Курс ₽/฿ из заявки не используется'),
      'рублёвый курс не должен считаться курсом ฿/USDT');
    assert.ok(out.includes('Оплата аренды виллы'), 'ожидали назначение платежа на экране');
    assert.ok(!out.includes('— не хватает'),
      'не должно быть сообщений о нехватке realty-фактов, когда все они уже на доске');
    console.log('T1 realty facts shown as known when already on board PASS');
  }

  // T2: отсутствующие денежные поля можно заполнить здесь; документы и назначение
  // по-прежнему показывают явный блокер.
  {
    const ctx = makeCtx(realtyMissingDeal());
    const out = ctx.manualCloseScreen(ctx.S.deals[0]);
    assert.ok(out.includes('— не хватает'),
      'ожидали явное сообщение о нехватке realty-фактов, когда их нет на доске');
    assert.ok(out.includes('id="mc_invoiceThb"') && out.includes('id="mc_buyRate"'),
      'денежные поля доступны в форме ручного переноса');
    assert.ok(out.includes('Редактировать'), 'нехватка документов должна объяснять следующий шаг');
    console.log('T2 missing realty facts show explicit blocking message PASS');
  }

  // T3: для обычного обмена (не недвижимость) блок «Инвойс и курс» не рисуется вовсе.
  {
    const exchangeDeal = {id: 2, code: 'СД-2', client: 'X', type: 'Обмен валюты', kind: 'Обмен',
      pair: 'USDT → THB', step: 's14', payType: null, amountUsdt: null, payinHashes: [],
      payout: {}, docs: {}, agents: [], rates: {}};
    const ctx = makeCtx(exchangeDeal);
    const out = ctx.manualCloseScreen(ctx.S.deals[0]);
    assert.ok(!out.includes('Инвойс и курс'),
      'блок «Инвойс и курс» не должен рисоваться для сделок обмена валюты');
    console.log('T3 realty section absent for exchange deals PASS');
  }

  // T4: до ввода фактического USDT не показываем ложную прибыль по курсу ₽/฿.
  {
    const ctx = makeCtx(realtyKnownDeal());
    const out = ctx.manualCloseScreen(ctx.S.deals[0]);
    assert.ok(out.includes('id="mc_profit">Укажите фактически полученную сумму USDT'),
      'до факта прихода вместо суммы прибыли должен быть запрос факта');
    console.log('T4 pending profit awaits actual USDT PASS');
  }

  console.log('ALL PASS');
}

main();
