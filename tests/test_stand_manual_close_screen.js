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

// manualCloseScreen's own dependency surface (задача 5): нужно вытащить сам экран плюс
// всё, что он реально ВЫЗЫВАЕТ при рендере (не то, что просто упомянуто в onclick-строках —
// те не выполняются без клика, их определять в контексте не нужно).
const SCRIPT = [
  source('htmlText'), source('jsLiteralAttr'), source('num'), source('hashSum'),
  source('txShort'), source('explorer'), source('moneyKop'), source('usd'),
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

function makeCtx(deal) {
  const S = {deals: [deal], incomes: [], role: 'admin', manualCloseForm: {}};
  const ctx = {
    S, SOURCES_PAY,
    render: () => {}, toast: () => {}, fetch: () => Promise.reject(new Error('not used in render')),
  };
  vm.createContext(ctx);
  vm.runInContext(SCRIPT, ctx);
  return ctx;
}

// Сделка на s14: про Pay-In ничего не известно, хешей прихода нет вовсе — ранний случай
// (брали вручную, задачник не дошёл даже до прихода).
function earlyDeal() {
  return {id: 1, code: 'СД-1001', client: 'Иван Early', type: 'Обмен валюты', kind: 'Обмен',
    pair: 'USDT → THB', step: 's14', payType: null, amountUsdt: null, payinHashes: [],
    payout: {}, docs: {}, agents: [], rates: {}};
}

// Сделка на s27: про Pay-In почти всё известно — метод, сумма, хеш уже записан на доске.
function lateDeal() {
  return {id: 2, code: 'СД-1002', client: 'Пётр Late', type: 'Обмен валюты', kind: 'Обмен',
    pair: 'USDT → THB', step: 's27', payType: 'Крипта', amountUsdt: 1000,
    payinHashes: [{amount: 1000, network: 'TRC20', hash: 'TRXABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'}],
    payout: {usdt: 900, hashes: [{amount: 900, network: 'TRC20', hash: 'TRXOUT987654321ZYXWVUTSRQPONMLKJIHGFEDCBA'}]},
    docs: {}, agents: [], rates: {}};
}

function countClass(html, cls) {
  const re = new RegExp('class="[^"]*\\b' + cls + '\\b[^"]*"', 'g');
  return (html.match(re) || []).length;
}

function main() {
  // T1: сделка на s14 без payinHashes — хеш прихода рисуется открытым редактируемым полем,
  // а не готовой строкой «известно».
  {
    const ctx = makeCtx(earlyDeal());
    const out = ctx.manualCloseScreen(ctx.S.deals[0]);
    assert.ok(/onchange="mcHashSet\(1,'payin',0,'hash'/.test(out),
      'ожидали редактируемый input хеша прихода (mcHashSet), когда d.payinHashes пуст');
    assert.ok(!/class="sumhash"/.test(out),
      'не должно быть готовой read-only строки хеша, когда прихода ещё нет');
    console.log('T1 editable payin hash input when payinHashes empty PASS');
  }

  // T2: сделка на s27 с d.payinHashes — хеш показан read-only строкой (hashCell), без
  // полей ввода хеша прихода.
  {
    const ctx = makeCtx(lateDeal());
    const out = ctx.manualCloseScreen(ctx.S.deals[0]);
    assert.ok(/class="sumhash"/.test(out),
      'ожидали read-only отображение хеша прихода (hashCell), когда d.payinHashes уже есть');
    assert.ok(!/mcHashSet\(2,'payin'/.test(out),
      'не должно быть редактируемых полей хеша прихода, когда он уже известен');
    console.log('T2 read-only payin hash rows when payinHashes present PASS');
  }

  // T3: обязательное поле причины закрытия есть всегда — и на раннем, и на почти готовом шаге.
  {
    for (const deal of [earlyDeal(), lateDeal()]) {
      const ctx = makeCtx(deal);
      const out = ctx.manualCloseScreen(ctx.S.deals[0]);
      assert.ok(/<textarea[^>]*id="mc_reason"/.test(out),
        'ожидали textarea#mc_reason на экране ручного переноса (deal ' + deal.id + ')');
    }
    console.log('T3 mandatory reason textarea always rendered PASS');
  }

  // T4: ровно одна первичная (coral) кнопка — кнопка отправки, остальные outline/secondary.
  {
    for (const deal of [earlyDeal(), lateDeal()]) {
      const ctx = makeCtx(deal);
      const out = ctx.manualCloseScreen(ctx.S.deals[0]);
      assert.equal(countClass(out, 'btn-primary'), 1,
        'ожидали ровно одну .btn-primary на экране ручного переноса (deal ' + deal.id + ')');
    }
    console.log('T4 exactly one .btn-primary PASS');
  }
}

main();
