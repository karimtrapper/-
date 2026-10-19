// Регресс, найденный живым браузерным прогоном (design-gate): выбор «Аренда»
// в dealKindSelect молча откатывался на «Обычная (обмен)», потому что
// onDealKindChange() безусловно вызывает toggleCustomDeal/toggleMfDeal/
// toggleFhDeal → syncDealKindSelect(), а тот не умел отличить «аренда, ни
// один чекбокс не включён» от «обмен, ни один чекбокс не включён» — и
// всегда коллапсировал в 'exchange'. rental — такой же "без своего
// чекбокса" тип, как exchange (см. test_kind_select_options_match_toggles),
// поэтому syncDealKindSelect должен сохранять текущее 'rental', а не
// переписывать его.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../static/crm/crm.html'), 'utf8');

function fn(name) {
  const oneLine = html.match(new RegExp(`^\\s*(?:async )?function ${name}\\([^\\n]*\\)\\{[^\\n]*\\}$`, 'm'));
  if (oneLine) return oneLine[0];
  const found = html.match(new RegExp(`^\\s*(?:async )?function ${name}\\([^]*?^        }`, 'm'));
  assert.ok(found, `Функция ${name} отсутствует`);
  return found[0];
}

function makeSelect(initial) {
  return { value: initial, options: [] };
}

function ctx() {
  const select = makeSelect('rental');
  const toggles = {
    mfDealToggle: { checked: false },
    fhDealToggle: { checked: false },
    customDealToggle: { checked: false },
  };
  const elements = { dealKindSelect: select, ...toggles };
  const context = {
    document: { getElementById: (id) => elements[id] || null },
    applyFlowGateOptions: () => {},
  };
  vm.createContext(context);
  vm.runInContext(fn('syncDealKindSelect'), context);
  return { context, select };
}

{
  const { context, select } = ctx();
  context.syncDealKindSelect();
  assert.equal(select.value, 'rental',
    'выбранная Аренда должна сохраняться — ни один чекбокс недвижимости её не представляет, как и exchange');
}
{
  // Контроль: пустой/обменный выбор по-прежнему коллапсирует в 'exchange',
  // поведение для обычного обмена не изменилось.
  const select = makeSelect('exchange');
  const elements = {
    dealKindSelect: select,
    mfDealToggle: { checked: false },
    fhDealToggle: { checked: false },
    customDealToggle: { checked: false },
  };
  const context = { document: { getElementById: (id) => elements[id] || null }, applyFlowGateOptions: () => {} };
  vm.createContext(context);
  vm.runInContext(fn('syncDealKindSelect'), context);
  context.syncDealKindSelect();
  assert.equal(select.value, 'exchange');
}
{
  // Чекбокс мф-лизхолда побеждает, даже если select сейчас стоит на rental.
  const select = makeSelect('rental');
  const elements = {
    dealKindSelect: select,
    mfDealToggle: { checked: true },
    fhDealToggle: { checked: false },
    customDealToggle: { checked: false },
  };
  const context = { document: { getElementById: (id) => elements[id] || null }, applyFlowGateOptions: () => {} };
  vm.createContext(context);
  vm.runInContext(fn('syncDealKindSelect'), context);
  context.syncDealKindSelect();
  assert.equal(select.value, 'mf_realty');
}
console.log('ALL OK');
