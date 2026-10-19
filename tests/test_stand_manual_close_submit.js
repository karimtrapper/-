// Отправка ручного переноса сделки в CRM (задача 6): пэйлоад из формы задачи 5 плюс
// тот же идемпотентный guard и стиль обработки ошибок, что в crmPushClose.
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
function constSource(name) {
  // Лениво до первой ';' после '=' — подходит и для однострочного объекта (BROKER_FEE),
  // и для многострочных массива/объекта (CRM_FACTS_MISMATCH, MANUAL_CLOSE_ERRORS).
  const re = new RegExp('^const ' + name + '=.*?;', 'ms');
  const match = html.match(re);
  assert.ok(match, `${name} missing`);
  return match[0];
}

// Только то, что manualClosePayload/manualCloseSubmit реально вызывают. crmPayloadFinal
// намеренно подменён стабом — его собственный расчёт прибыли проверяют другие тесты,
// здесь важно только то, что manualClosePayload кладёт его результат в body.crm.
// hashSum/brokerSend/BROKER_FEE/payinParts — цепочка зависимостей для нерублёвой ветки
// amountUsdt (T5): она реально вызывает payinParts, а не только упоминает его в коде.
const SCRIPT = [
  source('num'), source('val'), source('need'),
  source('isCrypto'), source('payCur'), source('exchangeSpec'),
  source('hashSum'), constSource('BROKER_FEE'), source('brokerSend'), source('payinParts'),
  source('clientRubPaid'), source('payoutHuman'), source('mfList'),
  source('manualCloseFormState'), source('manualCloseMerge'),
  source('manualClosePayload'), constSource('MANUAL_CLOSE_ERRORS'),
  constSource('CRM_FACTS_MISMATCH'), source('crmFactsMismatchMessage'),
  source('manualCloseSubmit', true),
].join('\n');

// Сделка на s27, где и приход, и расход уже полностью известны — ветки чтения из DOM
// (val()) в manualClosePayload не используются вовсе, кроме mc_reason (он обязателен всегда).
function fullyKnownDeal(id) {
  return {id, code: 'СД-' + id, client: 'Клиент', manager: 'Елизавета',
    type: 'Обмен валюты', kind: 'Обмен', pair: 'USDT → THB',
    payType: 'Крипта', amountUsdt: 500,
    payinHashes: [{amount: 500, network: 'TRC20', hash: 'TRXIN' + id}],
    paySrc: 'coins', payout: {usdt: 450, hashes: [{amount: 450, network: 'TRC20', hash: 'TRXOUT' + id}]},
    agents: [], rates: {}, docs: {}, files: {}};
}

// Рублёвая сделка без amountUsdt, но с известным методом/расходом — открыты только
// mc_payin_amount_rub и mc_payin_rate (T5: нерублёвая математика через payinParts).
function nonCryptoMissingAmountDeal(id) {
  return {id, code: 'СД-' + id, client: 'Клиент', manager: 'Елизавета',
    type: 'Обмен валюты', kind: 'Обмен', pair: 'RUB → USDT',
    payType: 'СБП', amountUsdt: null, amountRub: null, incomeAmount: null,
    payinHashes: [], paySrc: 'coins', payout: {usdt: 450, hashes: [{amount: 450, network: 'TRC20', hash: 'TRXOUT' + id}]},
    agents: [], rates: {}, docs: {}, files: {}};
}

function makeCtx(deal, reasonText, extraFields) {
  const S = {deals: [deal], manualCloseDraft: {[deal.id]: true}, manualCloseForm: {}, incomes: []};
  const domFields = {mc_reason: reasonText, ...(extraFields || {})};
  const toasts = [];
  const fetchCalls = [];
  const ctx = {
    S, STAND: false, standClosing: false, standVer: 10, standBase: null,
    deal: idArg => S.deals.find(d => d.id === idArg),
    toast: msg => toasts.push(msg),
    render: () => {}, standClone: x => x, standApply: () => {},
    confirm: () => true,
    crmPayloadFinal: () => ({deal_kind: 'exchange', mock: true}),
    document: {
      getElementById: id => Object.hasOwn(domFields, id) ? {value: domFields[id] || ''} : null,
      querySelectorAll: () => [],
    },
    AbortController, setTimeout, clearTimeout,
    fetch: (url, options) => { fetchCalls.push({url, options}); return ctx._fetchImpl(url, options); },
    _fetchImpl: () => Promise.reject(new Error('fetch not stubbed for this test')),
  };
  vm.createContext(ctx);
  vm.runInContext(SCRIPT, ctx);
  return {ctx, S, toasts, fetchCalls};
}

async function main() {
  // T1: повторный клик, пока предыдущая отправка ещё не закончилась, — ничего не делает,
  // в сеть не ходит (тот же guard, что у crmPushClose).
  {
    const {ctx, fetchCalls} = makeCtx(fullyKnownDeal(1), 'Причина закрытия вручную — достаточно длинная');
    ctx.standClosing = true;
    await ctx.manualCloseSubmit(1);
    assert.equal(fetchCalls.length, 0, 'повторный вызов при standClosing=true не должен обращаться к сети');
    console.log('T1 standClosing re-entrancy guard blocks submit PASS');
  }

  // T2: manualClosePayload(d) кладёт текст из textarea#mc_reason в manualOverride.reason.
  {
    const {ctx, S} = makeCtx(fullyKnownDeal(2), 'Перенесли вручную — клиент заплатил наличными через офис');
    const payload = ctx.manualClosePayload(S.deals[0]);
    assert.equal(payload.manualOverride.reason,
      'Перенесли вручную — клиент заплатил наличными через офис');
    assert.equal(payload.crm.mock, true, 'crm-половина должна быть результатом crmPayloadFinal');
    console.log('T2 manualClosePayload reads reason from mc_reason textarea PASS');
  }

  // T3: сервер отвечает 400 {success:false, error:'payin_hash_required'} — тост называет
  // конкретное недостающее поле, а не обобщённый провал.
  {
    const {ctx, toasts} = makeCtx(fullyKnownDeal(3), 'Причина закрытия вручную — достаточно длинная');
    ctx._fetchImpl = () => Promise.resolve({status: 400,
      json: async () => ({success: false, error: 'payin_hash_required'})});
    await ctx.manualCloseSubmit(3);
    assert.ok(toasts.some(t => t.includes('хеш') && t.includes('прихода')),
      'ожидали упоминание хеша прихода в тосте: ' + JSON.stringify(toasts));
    assert.ok(!toasts.some(t => t.includes('Перенос не выполнен: payin_hash_required')),
      'это должен быть предметный, а не обобщённый тост с сырым кодом ошибки');
    console.log('T3 field-specific error surfaced for payin_hash_required PASS');
  }

  // T4: успешное закрытие очищает черновик ручного переноса этой сделки.
  {
    const {ctx, S, toasts} = makeCtx(fullyKnownDeal(4), 'Причина закрытия вручную — достаточно длинная');
    const closedData = {deals: [{...S.deals[0], closed: true, crmDealId: 99, step: 'done'}]};
    ctx._fetchImpl = () => Promise.resolve({status: 201,
      json: async () => ({success: true, version: 11, deal: {id: 99}, data: closedData})});
    assert.equal(S.manualCloseDraft[4], true, 'черновик должен существовать перед отправкой');
    await ctx.manualCloseSubmit(4);
    assert.ok(!S.manualCloseDraft[4], 'черновик ручного переноса должен быть очищен после успеха');
    assert.ok(toasts.some(t => t.includes('CRM #99')), 'ожидали тост с номером сделки CRM');
    console.log('T4 success clears S.manualCloseDraft[id] PASS');
  }

  // T5 (ревью задачи 6): для рублёвой сделки без amountUsdt payload считает его той же
  // формулой, что payinParts (курс минус удержание брокера) — не своей отдельной.
  // Сервер не проверяет эту цифру ни с чем (нет on-chain квитанции для РУБ), поэтому
  // ошибка здесь тихо осталась бы фактом на доске — отдельный тест обязателен.
  {
    const {ctx, S} = makeCtx(nonCryptoMissingAmountDeal(5),
      'Причина закрытия вручную — достаточно длинная',
      {mc_payin_amount_rub: '100000', mc_payin_rate: '95'});
    const payload = ctx.manualClosePayload(S.deals[0]);
    const d = S.deals[0];
    const expected = ctx.payinParts({...d, incomeAmount: 100000, amountRub: 100000,
      rates: {...d.rates, broker: 95}})[0].usdt;
    assert.ok(Number.isFinite(expected) && expected > 0, 'ожидали конечный положительный расчёт payinParts для сверки');
    assert.equal(payload.manualOverride.payin.amountUsdt, expected,
      'amountUsdt должен совпасть с payinParts() на тех же входных данных, а не со своей формулой');
    assert.equal(payload.manualOverride.payin.amountRub, 100000);
    assert.equal(payload.manualOverride.payin.rate, 95);
    console.log('T5 non-crypto amountUsdt matches payinParts() output PASS (' + expected + ')');
  }

  // T6 (ревью задачи 6): _stand_crm_fact_problem выполняется безусловно и после ветки
  // override тоже — код «цифры отличаются от доски» должен показать ту же понятную фразу,
  // что у crmPushClose, а не сырой код ошибки (на случай, если manualCloseMerge когда-то
  // разойдётся с тем, что сервер реально применил на доску).
  {
    const {ctx, toasts} = makeCtx(fullyKnownDeal(6), 'Причина закрытия вручную — достаточно длинная');
    ctx._fetchImpl = () => Promise.resolve({status: 409,
      json: async () => ({success: false, error: 'payin_facts_mismatch'})});
    await ctx.manualCloseSubmit(6);
    assert.ok(toasts.some(t => t.includes('Цифры или переводы отличаются от сохранённой сделки')),
      'ожидали ту же дружелюбную фразу, что у crmPushClose: ' + JSON.stringify(toasts));
    assert.ok(!toasts.some(t => t.includes('payin_facts_mismatch')),
      'не должен показывать сырой код ошибки для этого класса');
    console.log('T6 facts-mismatch code reuses crmPushClose\'s friendly message PASS');
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
