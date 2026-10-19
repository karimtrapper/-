// Калькулятор → CRM хэндовер должен передавать РЕАЛЬНЫЙ deal_kind/payin_method,
// выбранный пользователем (Фрихолд/Лизхолд/Обмен + способ), а не захардкоженный
// exchange — иначе гейт непроверенных флоу (app.py VERIFIED_FLOWS) блокирует
// даже проверенные связки (фрихолд/лизхолд по реквизитам), ломая рабочий путь.
// См. тикет Карима 2026-10-19 (исправление поверх исходного решения "пропустить Task 8").
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const js = fs.readFileSync(path.join(__dirname, '../static/calculator/calculator.js'), 'utf8');

function fn(name) {
  const oneLine = js.match(new RegExp(`^function ${name}\\([^\\n]*\\)\\{[^\\n]*\\}$`, 'm'));
  if (oneLine) return oneLine[0];
  const found = js.match(new RegExp(`^function ${name}\\([^]*?^}`, 'm'));
  assert.ok(found, `Функция ${name} отсутствует`);
  return found[0];
}

function ctx() {
  const context = {};
  vm.createContext(context);
  vm.runInContext(fn('calcDealKindAndPayin'), context);
  return context;
}

function check(actual, expected, msg) {
  assert.equal(actual.deal_kind, expected.deal_kind, msg);
  assert.equal(actual.payin_method, expected.payin_method, msg);
}

{
  const c = ctx();
  check(c.calcDealKindAndPayin('property_freehold', 'doverka'),
    { deal_kind: 'mf_freehold', payin_method: 'sber_reqs' },
    'Фрихолд должен уходить с реквизитами — у калькулятора нет отдельного выбора способа оплаты для недвижимости');
  check(c.calcDealKindAndPayin('property_freehold', 'broker'),
    { deal_kind: 'mf_freehold', payin_method: 'sber_reqs' });
  check(c.calcDealKindAndPayin('property_leasehold', 'custom'),
    { deal_kind: 'mf_realty', payin_method: 'sber_reqs' });
}
{
  const c = ctx();
  check(c.calcDealKindAndPayin('exchange', 'doverka'),
    { deal_kind: 'exchange', payin_method: 'sber_wl' },
    'обычный обмен — поведение не меняется: doverka = СБП');
  check(c.calcDealKindAndPayin('exchange', 'broker'),
    { deal_kind: 'exchange', payin_method: 'crypto_direct' });
  check(c.calcDealKindAndPayin('other', 'custom'),
    { deal_kind: 'custom', payin_method: 'crypto_direct' });
}
console.log('ALL OK');
