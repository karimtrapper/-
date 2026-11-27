const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const js = fs.readFileSync('static/calculator/calculator.js', 'utf8');
function fn(name) {
  const found = js.match(new RegExp(`^function ${name}\\([^]*?^}`, 'm'));
  assert.ok(found, `Функция ${name} отсутствует`);
  return found[0];
}

function makeBtn(dataProfit) {
  const classes = new Set();
  return {
    dataset: { profit: dataProfit },
    classList: { toggle: (c, on) => { if (on) classes.add(c); else classes.delete(c); }, has: c => classes.has(c) },
    _classes: classes,
  };
}

function buildCtx() {
  const presetValues = ['1.5', '2.0', '2.4', '3.0', '3.5', '4.0', '4.5', '5.0'];
  const presetBtns = presetValues.map(makeBtn);
  const customBtn = makeBtn('custom');
  const label = { textContent: '' };
  const floorHint = { style: { display: 'none' } };
  const elements = { customProfitBtn: customBtn, profitCurrentLabel: label, profitFloorHint: floorHint };
  const ctx = {
    state: { applyDiscount: false, profitMargin: 4, scenario: 'rub-to-thb', direction: 'amount', rates: { rub_usdt: 82 } },
    document: {
      getElementById: id => elements[id] || null,
      querySelectorAll: () => presetBtns,
    },
    getAmount() { return 100000; },
    setProfitMargin(p) { ctx.state.profitMargin = +p; },
  };
  vm.createContext(ctx);
  const PROFIT_CONSTS = 'const PROFIT_LADDER_SMALL=5.0,PROFIT_LADDER_MEDIUM=4.0,PROFIT_LADDER_LARGE=3.0,PROFIT_USDT_TO_THB=2.4,PROFIT_THB_TO_USDT=3.0,PROFIT_FLOOR=1.5;';
  vm.runInContext(PROFIT_CONSTS + [fn('rubBase'), fn('ladderProfit'), fn('effectiveProfit'), fn('profitLabel'), fn('choosePresetProfit'), fn('updateProfitDisplay')].join('\n'), ctx);
  return { ctx, presetBtns, customBtn, label, floorHint };
}

// 100 000 ₽ rub-to-thb amount-direction → small tier, ladder = 5%
{
  const { ctx } = buildCtx();
  assert.equal(ctx.ladderProfit(100000), 5.0);
}

// choosePresetProfit устанавливает applyDiscount и зовёт setProfitMargin прежней логикой
{
  const { ctx } = buildCtx();
  ctx.choosePresetProfit(3.0);
  assert.equal(ctx.state.applyDiscount, true, 'выбор пресета включает согласованную скидку');
  assert.equal(ctx.state.profitMargin, 3.0);
}

// Пресет 5% == стандарту для этой суммы → подпись «Стандарт», сам пресет подсвечен, «Своё» — нет
{
  const { ctx, presetBtns, customBtn, label } = buildCtx();
  ctx.state.applyDiscount = true;
  ctx.state.profitMargin = 5.0;
  ctx.updateProfitDisplay();
  assert.equal(label.textContent, 'Стандарт 5%');
  assert.equal(presetBtns[7]._classes.has('active'), true, 'кнопка 5% подсвечена');
  assert.equal(customBtn._classes.has('active'), false, '«Своё» не подсвечено, когда совпал пресет');
}

// Значение через «Своё» (10%), не совпадающее ни с одним пресетом → подсвечено только «Своё»
// (баг найден на сравнении со скриншотом Карима 2026-10-29: подсветка слетала при вводе значения)
{
  const { ctx, presetBtns, customBtn, label } = buildCtx();
  ctx.state.applyDiscount = true;
  ctx.state.profitMargin = 10;
  ctx.updateProfitDisplay();
  assert.equal(label.textContent, 'Наценка 5%');
  assert.ok(presetBtns.every(b => !b._classes.has('active')), 'ни один пресет не подсвечен');
  assert.equal(customBtn._classes.has('active'), true, '«Своё» подсвечено для произвольного значения');
}

// Пол прибыли по-прежнему показывает подсказку
{
  const { ctx, floorHint } = buildCtx();
  ctx.state.applyDiscount = true;
  ctx.state.profitMargin = 1.5;
  ctx.updateProfitDisplay();
  assert.equal(floorHint.style.display, '', 'подсказка про пол видна на границе 1.5%');
}

console.log('profit buttons (presets + Своё highlight): PASS');
