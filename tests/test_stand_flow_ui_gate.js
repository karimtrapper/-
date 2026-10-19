// Гейт непроверенных флоу (тип сделки + способ Pay-In) в форме создания
// заявки на стенде: visible-but-disabled для менеджера, confirm-дialog для
// admin. Логика проверяется напрямую на извлечённых функциях (как в
// test_stand_freehold.js); визуальное состояние чипов — через design-gate
// на живом стенде (см. docs/superpowers/plans/2026-10-18-gate-unverified-flows.md Task 9).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../static/stand/tasks.html'), 'utf8');

function fn(name) {
  const oneLine = html.match(new RegExp(`^(?:async )?function ${name}\\([^\\n]*\\)\\{[^\\n]*\\}$`, 'm'));
  if (oneLine) return oneLine[0];
  const found = html.match(new RegExp(`^(?:async )?function ${name}\\([^]*?^}`, 'm'));
  assert.ok(found, `Функция ${name} отсутствует`);
  return found[0];
}

function cst(name) {
  const found = html.match(new RegExp(`^const ${name}\\s*=[\\s\\S]*?;`, 'm'));
  assert.ok(found, `Константа ${name} отсутствует`);
  return found[0].replace(/^const /, 'var ');
}

function ctx() {
  const context = { STAND_VERIFIED_FLOWS: [['freehold', 'requisites'], ['leasehold', 'requisites']] };
  vm.createContext(context);
  vm.runInContext(cst('STAND_KIND_CANON') + '\n' + cst('STAND_PAYTYPE_CANON') + '\n' + fn('draftComboVerified'), context);
  return context;
}

// ── draftComboVerified: чистая логика сверки с кэшем verified-пар ────────

{
  const c = ctx();
  assert.equal(c.draftComboVerified('Оплата недвижимости', 'Фрихолд', 'По реквизитам'), true,
    'Фрихолд + По реквизитам — проверенная комбинация');
  assert.equal(c.draftComboVerified('Оплата недвижимости', 'Лизхолд', 'По реквизитам'), true,
    'Лизхолд + По реквизитам — проверенная комбинация');
}
{
  const c = ctx();
  assert.equal(c.draftComboVerified('Оплата недвижимости', 'Аренда', 'Наличные'), false,
    'Аренда + Наличные — непроверенная комбинация');
  assert.equal(c.draftComboVerified('Оплата недвижимости', 'Фрихолд', 'Крипта'), false,
    'Фрихолд + Крипта — непроверенная комбинация');
  assert.equal(c.draftComboVerified('Обмен валюты', null, 'По реквизитам'), false,
    'Обмен валюты — тип сам по себе не проверен, даже с По реквизитам');
}
console.log('draftComboVerified: OK');

// ── draftTypeVerified: «Тип запроса» — Обмен валюты никогда не проверен,
// независимо от kind/payType; Оплата недвижимости сама по себе нейтральна ──

{
  const context = {};
  vm.createContext(context);
  vm.runInContext(fn('draftTypeVerified'), context);
  assert.equal(context.draftTypeVerified('Оплата недвижимости'), true);
  assert.equal(context.draftTypeVerified('Обмен валюты'), false,
    'Обычный обмен — непроверенный тип сам по себе, как Аренда для kind');
}
console.log('draftTypeVerified: OK');

// ── newDeal переносит unverified_confirmed из драфта в сделку ────────────

function newDealCtx() {
  const context = { now: () => 0, SOURCES: { tg: 'Telegram' }, log: () => {} };
  vm.createContext(context);
  vm.runInContext(fn('newDeal'), context);
  context.S = { seq: 1000, deals: [] };
  return context;
}

{
  const context = newDealCtx();
  const deal = context.newDeal({ type: 'Оплата недвижимости', kind: 'Аренда', payType: 'Наличные',
    source: 'tg', step: 's5', unverified_confirmed: true, noSave: true });
  assert.equal(deal.unverified_confirmed, true,
    'newDeal должен сохранить unverified_confirmed, иначе admin-подтверждение не дойдёт до сервера');
}
{
  const context = newDealCtx();
  const deal = context.newDeal({ type: 'Оплата недвижимости', kind: 'Фрихолд', payType: 'По реквизитам',
    source: 'tg', step: 's5', noSave: true });
  assert.equal(deal.unverified_confirmed, false,
    'без явного подтверждения поле должно быть ложным, а не undefined (чтобы сервер видел явный false)');
}
console.log('newDeal unverified_confirmed passthrough: OK');

console.log('ALL OK');
