const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('static/stand/crm-draft-core.js', 'utf8');
const context = {window: {}, console, Set, URL, Number, String, Math, Promise,
  setTimeout, clearTimeout};
vm.createContext(context);
vm.runInContext(source, context);

function render(net, part) {
  const ids = new Map();
  const element = id => {
    if (!ids.has(id)) ids.set(id, {value: '', style: {}, innerHTML: '', textContent: '',
      classList: {toggle() {}}, options: [{dataset: {rate: '31.5'}}], selectedIndex: 0});
    return ids.get(id);
  };
  const form = {payin_amount_rub: {value: ''}, payin_rate_rub_usdt: {value: '80'},
    payin_amount_usdt: {value: ''}, payout_amount_thb: {value: ''},
    payout_source: {value: 'binance'}};
  const root = {getElementById: element, querySelector: selector =>
    selector === '[name="payin_amount_rub"]' ? form.payin_amount_rub
      : selector === '[name="payin_amount_usdt"]' ? form.payin_amount_usdt : null};
  const core = context.window.createCrmDraftCore(root, {
    form, payinRubIsNet: net, sberParts: [part], editingDealId: null,
    fetch: async () => ({json: async () => ({incomes: []})}),
    toast() {}, escapeHtml: String, formatDate: () => '',
    currentUsdtThbRate: 31.5, realtyPayinRecalc() {}, realtyPayoutRecalc() {},
  });
  core.sberRender();
  return {summary: element('sberPartsTotal').textContent.replace(/\s/g, ' '),
    row: element('sberPartsList').innerHTML.replace(/\s/g, ' '),
    rub: form.payin_amount_rub.value};
}

const known = render(true, {uuid: 'a', kind: 'acquiring', amount_rub: 98500,
  net_rub: 98500, fee_rub: 1500});
assert.match(known.summary, /Итого на счёт: 98 500,00 ₽/);
assert.match(known.summary, /до комиссии банка 100 000,00 ₽/);
assert.doesNotMatch(known.summary, /97 000/);
assert.equal(known.rub, '98500.00');

const unknown = render(true, {uuid: 'b', kind: 'acquiring', amount_rub: 98500,
  net_rub: 98500, fee_rub: null});
assert.match(unknown.summary, /комиссия эквайринга неизвестна/);
assert.match(unknown.summary, /до комиссии банка неизвестно/);
assert.match(unknown.row, /комиссия неизвестна/);
assert.doesNotMatch(unknown.row, /комиссия 0,00/);

const zero = render(true, {uuid: 'c', kind: 'acquiring', amount_rub: 98500,
  net_rub: 98500, fee_rub: 0});
assert.match(zero.summary, /комиссия эквайринга 0,00 ₽/);
assert.match(zero.summary, /до комиссии банка 98 500,00 ₽/);

const gross = render(false, {uuid: 'd', kind: 'acquiring', amount_rub: 100000,
  net_rub: 98500, fee_rub: 1500});
assert.match(gross.summary, /Итого от клиента до комиссии: 100 000,00 ₽/);
assert.match(gross.summary, /на счёт 98 500,00 ₽/);
assert.equal(gross.rub, '100000.00');
console.log('CRM Sber basis summary: PASS');
