// crmPushClose: сервер (прод-код d2a8ec6/2c40e91) может ответить 409
// requires_confirmation, если расход выплаты выше подтверждённого on-chain перевода.
// Задачник должен спросить человека и повторить запрос с confirm_payout_tx_overage,
// а не падать и не закрывать сделку молча. Отказ — второго запроса быть не должно.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../static/stand/tasks.html'), 'utf8');
const found = html.match(/^async function crmPushClose\([^]*?^}/m);
assert.ok(found, 'нет функции crmPushClose');
const source = found[0];

function fixture(responses, confirmAnswer) {
  const d = {id: 1, code: 'СД-1', crmDealId: null, sentToClient: true,
    type: 'Обмен', pay: {}, log: []};
  const S = {deals: [d]};
  const toasts = [], logs = [], calls = [];
  let call = 0;
  const ctx = {
    S,
    deal: () => d,
    crmGaps: () => [],
    crmPayloadFinal: () => ({fake: 'body'}),
    crmEditDiff: () => [],
    closeDeal: (dd, reason) => { dd.closed = true; dd.closeReason = reason; },
    log: (dd, s) => logs.push(s),
    save: () => {},
    render: () => {},
    toast: s => toasts.push(s),
    now: () => '28.09',
    usd: v => '$' + v,
    confirm: msg => { calls.push({type: 'confirm', msg}); return confirmAnswer; },
    fetch: (url, opts) => {
      const body = JSON.parse(opts.body);
      calls.push({type: 'fetch', url, method: opts.method, body});
      const r = responses[call++];
      return Promise.resolve({status: r.status, json: () => Promise.resolve(r.json)});
    },
    JSON,
  };
  vm.createContext(ctx);
  vm.runInContext(source, ctx);
  return {ctx, d, toasts, logs, calls};
}

(async () => {
  // 409 → человек подтверждает → повтор с confirm_payout_tx_overage:true → закрыта
  {
    const {ctx, d, toasts, calls} = fixture([
      {status: 409, json: {success: false, requires_confirmation: true, warning: 'Расход выше остатка'}},
      {status: 200, json: {success: true, deal: {id: 42}}},
    ], true);
    await ctx.crmPushClose(1);
    const fetches = calls.filter(c => c.type === 'fetch');
    assert.equal(fetches.length, 2, 'должно быть два запроса: первый и повтор с подтверждением');
    assert.equal(fetches[0].body.confirm_payout_tx_overage, undefined);
    assert.equal(fetches[1].body.confirm_payout_tx_overage, true);
    assert.equal(d.crmDealId, 42);
    assert.equal(d.closed, true);
    assert.ok(!toasts.some(t => t.includes('отменено')));
  }
  // QA FAIL №4: успех ПОСЛЕ подтверждённого повтора тоже может прийти с warning
  // (та же цифра расхода, что была в 409) — это нужно показать, а не проглотить.
  {
    const {ctx, d, toasts} = fixture([
      {status: 409, json: {success: false, requires_confirmation: true, warning: 'QA: превышение $100'}},
      {status: 200, json: {success: true, deal: {id: 15}, warning: 'QA: превышение $100'}},
    ], true);
    await ctx.crmPushClose(1);
    assert.equal(d.crmDealId, 15);
    assert.equal(d.closed, true);
    assert.ok(toasts.some(x => x.includes('QA: превышение $100')),
      'предупреждение об успешном закрытии с превышением должно быть показано человеку');
  }
  // 409 → человек отказывается → второго запроса нет, сделка не закрыта
  {
    const {ctx, d, toasts, calls} = fixture([
      {status: 409, json: {success: false, requires_confirmation: true, warning: 'Расход выше остатка'}},
    ], false);
    await ctx.crmPushClose(1);
    const fetches = calls.filter(c => c.type === 'fetch');
    assert.equal(fetches.length, 1, 'отказ — второго запроса быть не должно');
    assert.equal(d.crmDealId, null);
    assert.equal(d.closed, undefined);
    assert.ok(toasts.some(t => t.includes('отменено')));
  }
  // Обычное закрытие без 409 — как раньше, один запрос
  {
    const {ctx, d, calls} = fixture([
      {status: 200, json: {success: true, deal: {id: 7}}},
    ], true);
    await ctx.crmPushClose(1);
    const fetches = calls.filter(c => c.type === 'fetch');
    assert.equal(fetches.length, 1);
    assert.equal(d.crmDealId, 7);
    assert.equal(d.closed, true);
  }
  console.log('stand crmPushClose: 4 сценария PASS');
})();
