const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const js = fs.readFileSync('static/calculator/calculator.js', 'utf8');
function fn(name) {
  const found = js.match(new RegExp(`^function ${name}\\([^]*?^}`, 'm'));
  assert.ok(found, `Функция ${name} отсутствует`);
  return found[0];
}
const ctx = {
  state: { applyDiscount: false, profitMargin: 4, scenario: 'rub-to-thb', direction: 'amount', rates: { rub_usdt: 82 } },
  document: { getElementById: () => null, querySelectorAll: () => [], body: { classList: { contains: () => true } } },
  hideResults() {},
  setProfitMargin(p) { ctx.state.profitMargin = +p < 1.5 ? 1.5 : +p; ctx.state.applyDiscount = true; },
  resetDiscount() { ctx.state.applyDiscount = false; ctx.state.profitMargin = ctx.ladderProfit(100000); },
  getAmount() { return 100000; },
};
vm.createContext(ctx);
const PROFIT_CONSTS = 'const PROFIT_LADDER_SMALL=5.0,PROFIT_LADDER_MEDIUM=4.0,PROFIT_LADDER_LARGE=3.0,PROFIT_USDT_TO_THB=2.4,PROFIT_THB_TO_USDT=3.0,PROFIT_FLOOR=1.5;';
vm.runInContext(PROFIT_CONSTS + [fn('rubBase'), fn('ladderProfit'), fn('effectiveProfit'), fn('profitLabel'), fn('stepProfit'), fn('applyQuickProfit')].join('\n'), ctx);

// 100 000 ₽ rub-to-thb amount-direction → small tier, ladder = 5%
assert.equal(ctx.ladderProfit(100000), 5.0);
ctx.applyQuickProfit(-0.5);
assert.equal(ctx.state.profitMargin, 4.5, 'стандарт 5% − 0,5% = 4,5%');
ctx.stepProfit(-0.1);
assert.equal(+ctx.state.profitMargin.toFixed(1), 4.4, 'шаг −0,1% от текущего эффективного значения');
ctx.applyQuickProfit(0);
assert.equal(ctx.state.applyDiscount, false, '«Стандарт» возвращает в режим лестницы');
for (let i = 0; i < 40; i++) ctx.stepProfit(-0.1);
assert.ok(ctx.state.profitMargin >= 1.5 - 1e-6, 'не опускается ниже PROFIT_FLOOR');
console.log('profit stepper: PASS');
