const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const js = fs.readFileSync('static/calculator/calculator.js', 'utf8');
function fn(name) {
  const found = js.match(new RegExp(`^function ${name}\\([^]*?^}`, 'm'));
  assert.ok(found, `Функция ${name} отсутствует`);
  return found[0];
}
const ctx = {};
vm.createContext(ctx);
vm.runInContext(fn('buildClientMessage'), ctx);

const forbidden = /прибыл|маржа|margin|скидк|наценк|profit/i;
const cases = [
  { isTarget: false, propFeeApplied: false, inputAmount: 100000, inputCurrency: '₽', outputAmount: '37 037', rateValue: 2.7, rateCurrency: '฿' },
  { isTarget: true, propFeeApplied: false, inputAmount: 37037, inputCurrency: '฿', outputAmount: '100 000', rateValue: 2.7, rateCurrency: '฿' },
  { isTarget: false, propFeeApplied: true, inputAmount: 100000, inputCurrency: '₽', outputAmount: '37 037', rateValue: 2.7, rateCurrency: '฿' },
];
for (const c of cases) {
  const msg = ctx.buildClientMessage(c);
  assert.ok(!forbidden.test(msg), `текст клиенту не должен содержать прибыль/скидку: ${msg}`);
  assert.ok(msg.includes('Курс:'), 'курс должен быть в тексте');
}
console.log('client text excludes profit/discount: PASS');
