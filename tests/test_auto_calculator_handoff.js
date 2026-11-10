const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function fn(source, name) {
  const one = source.match(new RegExp(`^function ${name}\\([^\\n]*\\)\\{[^\\n]*\\}$`, 'm'));
  if (one) return one[0];
  const found = source.match(new RegExp(`^function ${name}\\([^]*?^}`, 'm'));
  assert.ok(found, `missing ${name}`);
  return found[0];
}
const tasks = fs.readFileSync('static/stand/tasks.html', 'utf8');
const calculator = fs.readFileSync('static/calculator/calculator.js', 'utf8');
const page = fs.readFileSync('static/calculator/index.html', 'utf8');

const task = {id: 1501, code: 'СД-1501', autoPayment: true, kind: 'Фрихолд',
  rates: {rubUsdt: 83}, ippsTariff: 'soft', client: 'Synthetic'};
const stand = {URLSearchParams, CALC_URL: '/',
  dealKind: () => 'mf_auto', exchangeSpec: () => null, isCrypto: () => false,
  autoShownMarginPct: () => 3};
vm.createContext(stand);
vm.runInContext(fn(tasks, 'calcLink') + '\n' + fn(tasks, 'calcBtn'), stand);

for (const [mode, amount] of [['usd', 79800], ['rub', 6949596.82]]) {
  const d = {...task, autoRequestMode: mode,
    requestedUsd: mode === 'usd' ? 79800 : null,
    requestedRub: mode === 'rub' ? 6949596.82 : null};
  const url = new URL(stand.calcLink(d), 'http://localhost');
  const q = url.searchParams;
  assert.equal(q.get('cat'), 'property_auto');
  assert.equal(q.get('scenario'), 'rub-to-usdt');
  assert.equal(q.get('dir'), mode === 'usd' ? 'target' : 'amount');
  assert.equal(q.get('amount'), String(amount));
  assert.equal(q.get('tariff'), 'soft');
  assert.equal(q.get('rub_usdt'), '83');
  assert.equal(q.get('profit'), '3');
  assert.match(stand.calcBtn(d), /Открыть в калькуляторе/);
}

const calc = {state: {dealCategory: 'property_auto', scenario: 'rub-to-usdt',
  direction: 'target', customRubUsdt: 83, rates: {rub_usdt: 82}, applyDiscount: false},
  Math};
vm.createContext(calc);
const constants = ['PROFIT_LADDER_SMALL', 'PROFIT_LADDER_MEDIUM', 'PROFIT_LADDER_LARGE',
  'PROFIT_USDT_TO_THB', 'PROFIT_THB_TO_USDT', 'PROFIT_FLOOR']
  .map(name => calculator.match(new RegExp(`^const ${name} = [^;]+;`, 'm'))[0].replace(/^const /, 'var '));
vm.runInContext(constants.join('\n') + '\n' +
  ['rubBase', 'ladderProfit', 'effectiveProfit', 'calcDealKindAndPayin']
    .map(name => fn(calculator, name)).join('\n'), calc);
assert.equal(calc.effectiveProfit(79800), 3);
assert.equal(calc.effectiveProfit(100), 5, 'USD base is converted to RUB only once');
calc.state.direction = 'amount';
assert.equal(calc.effectiveProfit(6949596.82), 3);
assert.equal(calc.calcDealKindAndPayin('property_auto', 'custom').deal_kind, 'mf_auto');
assert.equal(calc.calcDealKindAndPayin('property_auto', 'custom').payin_method, 'sber_reqs');
assert.match(page, /data-category="property_auto"[^>]*>\s*Оплата авто/);

const elements = new Map();
const el = id => {
  if (!elements.has(id)) elements.set(id, {style: {}, textContent: '', value: '',
    classList: {toggle() {}}});
  return elements.get(id);
};
const ui = {state: {dealCategory: 'exchange', scenario: 'rub-to-usdt',
  direction: 'target', method: 'custom'},
  document: {body: {classList: {toggle() {}}},
    getElementById: el, querySelectorAll: () => []},
  localStorage: {setItem() {}},
  setPropTariff() {}, setPropInvoiceCur() {},
  switchMethod(method) { ui.state.method = method; },
  switchScenario(scenario) { ui.state.scenario = scenario; },
  updateProfitDisplay() {}, hideResults() {},
  hidePreciseRateStatus() {}, hidePreciseRateFallback() {}};
vm.createContext(ui);
vm.runInContext(['updateB2DirectionHint', 'updateScenarioUI', 'switchDealCategory']
  .map(name => fn(calculator, name)).join('\n'), ui);
ui.switchDealCategory('property_auto');
assert.equal(el('inputLabel').textContent, 'Сумма продавцу, USD');
assert.equal(el('inputCurrency').textContent, 'USD');
ui.switchDealCategory('exchange');
assert.equal(el('inputLabel').textContent, 'Введите желаемую сумму в USDT');
assert.equal(el('inputCurrency').textContent, 'USDT');
assert.equal(el('resultLabel').textContent, 'Клиент должен внести:');
assert.equal(el('calculatorSubtitle').textContent, 'Рубли · баты · USDT');
assert.match(page, /@media \(max-width: 700px\)[^]*?dealtype-switcher \{ grid-template-columns: repeat\(2,/);

const cardStart = tasks.indexOf('      const X=d.invoiceUsd||0;\n      const k=num(d.rates.client);');
const cardEnd = tasks.indexOf('\n    }\n    return `<div class="card">', cardStart);
assert.ok(cardStart > 0 && cardEnd > cardStart);
const s6 = {num: x => Number(String(x || '0').replace(',', '.')),
  ago: () => '', ippsTariff: () => ({percent: 1.5, fixed: 50}),
  freeholdSend: () => 81047, htmlText: String, moneyKop: String, usd: String,
  freeholdInvoiceInputs6: () => 'SOURCE_FIELDS', freeholdSummary6: () => 'RESULT_FIELDS',
  calcBtn: () => 'CALCULATOR_LINK', fmtAmount: String, quotesSummary: () => ''};
vm.createContext(s6);
vm.runInContext('function autoCard(d){' + tasks.slice(cardStart, cardEnd) + '}', s6);
const rendered = s6.autoCard({...task, step: 's6', autoRequestMode: 'usd',
  requestedUsd: 79800, invoiceUsd: 79800, amountRub: 6949596.82,
  rates: {rubUsdt: 83, client: '87.0877'}, freeholdClientInput: 'sum'});
assert.equal((rendered.match(/CALCULATOR_LINK/g) || []).length, 1);
assert.ok(rendered.indexOf('CALCULATOR_LINK') < rendered.indexOf('SOURCE_FIELDS'));
assert.doesNotMatch(rendered, /Прибыль в расчёте|autoMarginSet/);
assert.match(rendered, /id="r4"/);
assert.match(rendered, /Рассчитайте в калькуляторе и укажите сумму клиенту в рублях/);
console.log('auto calculator URL, category and profit base: PASS');
