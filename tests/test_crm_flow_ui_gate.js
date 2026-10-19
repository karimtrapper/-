// Гейт непроверенных флоу (тип сделки + способ Pay-In) в legacy CRM-форме:
// visible-but-disabled <option> для менеджера, confirm-диалог для admin.
// Логика проверяется напрямую на извлечённых функциях (как в
// test_stand_flow_ui_gate.js); визуальное состояние <option disabled> —
// через design-gate на живом стенде.
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

function cst(name) {
  const found = html.match(new RegExp(`^\\s*const ${name}\\s*=[\\s\\S]*?;`, 'm'));
  assert.ok(found, `Константа ${name} отсутствует`);
  return found[0].replace(/const /, 'var ');
}

function ctx() {
  const context = { CRM_VERIFIED_FLOWS: [['freehold', 'requisites'], ['leasehold', 'requisites']] };
  vm.createContext(context);
  vm.runInContext(cst('CRM_KIND_CANON') + '\n' + cst('CRM_PAYIN_CANON') + '\n' + fn('crmComboVerified'), context);
  return context;
}

{
  const c = ctx();
  assert.equal(c.crmComboVerified('mf_freehold', 'sber_reqs'), true, 'фрихолд + сбер реквизиты — проверено');
  assert.equal(c.crmComboVerified('mf_freehold', 'flow_sole_reqs'), true, 'фрихолд + Flow Sole — проверено');
  assert.equal(c.crmComboVerified('mf_realty', 'sber_reqs'), true, 'лизхолд + сбер реквизиты — проверено');
}
{
  const c = ctx();
  assert.equal(c.crmComboVerified('rental', 'sber_reqs'), false, 'аренда — непроверена даже с реквизитами');
  assert.equal(c.crmComboVerified('exchange', 'sber_reqs'), false, 'обычный обмен — непроверен даже с реквизитами');
  assert.equal(c.crmComboVerified('mf_freehold', 'crypto_direct'), false, 'фрихолд + крипта — непроверено');
  assert.equal(c.crmComboVerified('mf_freehold', 'partners_cash'), false, 'фрихолд + наличные — непроверено');
  assert.equal(c.crmComboVerified('mf_freehold', 'sber_wl'), false, 'фрихолд + СБП — непроверено');
}
console.log('ALL OK');
