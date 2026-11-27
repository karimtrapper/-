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
vm.runInContext('const PROFIT_FLOOR = 1.5;\n' + fn('profitLabel') + '\n' + fn('clampProfitFloor'), ctx);

function checkLabel(ladder, profit, expectedMode, expectedDelta) {
  const r = ctx.profitLabel(ladder, profit);
  assert.equal(r.mode, expectedMode, `mode for ladder=${ladder} profit=${profit}`);
  assert.equal(r.deltaPct, expectedDelta, `deltaPct for ladder=${ladder} profit=${profit}`);
}
checkLabel(4.0, 3.5, 'discount', -0.5);
checkLabel(4.0, 4.0, 'standard', 0);
checkLabel(4.0, 5.0, 'markup', 1);
assert.equal(ctx.clampProfitFloor(1.2), 1.5);
assert.equal(ctx.clampProfitFloor(2.0), 2.0);
console.log('profit label + floor clamp: PASS');
