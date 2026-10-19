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
  const re = new RegExp('^const ' + name + '=\\{[^]*?^\\};', 'm');
  const match = html.match(re);
  assert.ok(match, `${name} missing`);
  return match[0];
}

// Только то, что manualClosePayload/manualCloseSubmit реально вызывают. crmPayloadFinal
// намеренно подменён стабом — его собственный расчёт прибыли проверяют другие тесты,
// здесь важно только то, что manualClosePayload кладёт его результат в body.crm.
const SCRIPT = [
  source('num'), source('val'), source('need'),
  source('isCrypto'), source('payCur'), source('exchangeSpec'),
  source('clientRubPaid'), source('payoutHuman'), source('mfList'),
  source('manualCloseFormState'), source('manualCloseMerge'),
  source('manualClosePayload'), constSource('MANUAL_CLOSE_ERRORS'),
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

function makeCtx(deal, reasonText) {
  const S = {deals: [deal], manualCloseDraft: {[deal.id]: true}, manualCloseForm: {}, incomes: []};
  const domFields = {mc_reason: reasonText};
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
}

main().catch(error => { console.error(error); process.exitCode = 1; });
