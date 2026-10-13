const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../static/stand/tasks.html'), 'utf8');
const source = ['htmlText', 'logWhen', 'logMeta', 'viewDeal', 'pathCard', 'ctxCard'].map(name => {
  const found = html.match(new RegExp(`^function ${name}\\([^]*?^}`, 'm'));
  assert.ok(found, name);
  return found[0];
}).join('\n');
const payload = '<img src=x onerror=alert(1)>';
const entry = {at: Date.now() - 120000, ts: '13.10, 10:00', role: 'manager', text: payload};
const deal = {id: 9500, code: 'SYN-9500', client: 'Клиент', type: 'Оплата недвижимости',
  kind: 'Фрихолд', source: 'tg', step: 's14', docs: {}, rates: {}, pay: {}, log: [entry]};
const ctx = {
  Date, Number, String, Math, S: {view: 'deal', role: 'operator'},
  STEPS: {s14: {title: 'Ждём приход', n: 14, who: 'operator'}},
  ROLES: {manager: {n: 'Менеджер', t: 'менеджер'}, operator: {n: 'Операционист', t: 'операционист'}},
  SOURCES: {tg: 'Telegram'},
  stepWho: () => 'operator', progress: () => ({i: 1, n: 2}),
  overview: () => '', quotesCard: () => '', prepayPanel: () => '', payToCard: () => '',
  demoAllowed: () => false, stepTitle: () => 'Ждём приход', plural: () => 'событие',
  approx: () => ({pay: 100, thb: 0}), apMoney: () => '100', isCrypto: () => false,
  rateUnit: () => '₽', money: n => String(n), dur: () => '2 мин', flowOf: () => [],
};
vm.createContext(ctx);
vm.runInContext(source, ctx);
function escaped(label, rendered) {
  assert.ok(rendered.includes('&lt;img src=x onerror=alert(1)&gt;'), label + ': escaped text missing');
  assert.ok(!rendered.includes(payload), label + ': executable HTML present');
}
escaped('список задач', ctx.logMeta(entry));
escaped('Коротко о пути', ctx.viewDeal(deal));
const pathHtml = ctx.pathCard(deal);
escaped('Хронология и Весь путь', pathHtml);
assert.equal((pathHtml.match(/&lt;img/g) || []).length, 2, 'table and longest-wait alert');
escaped('Последнее действие', ctx.ctxCard(deal));

// Любой новый прямой вывод текста журнала в HTML должен попасть в этот тест.
assert.doesNotMatch(html, /\$\{(?:l|r\.l|longest\.l|last)\.text\}/);
console.log('journal HTML escaping in all current views OK');
