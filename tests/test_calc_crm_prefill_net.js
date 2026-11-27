const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const html = fs.readFileSync('static/crm/crm.html', 'utf8');
const functions = ['prefillDealForm', 'updatePayinRubBasisHint'].map(name => {
  const match = html.match(new RegExp(`^        function ${name}\\([^]*?^        }`, 'm'));
  assert.ok(match, name);
  return match[0];
}).join('\n');

const fields = new Map();
const field = name => {
  if (!fields.has(name)) fields.set(name, {value: '', dataset: {}, style: {}});
  return fields.get(name);
};
const form = {querySelector: selector => field(selector)};
const ctx = {
  document: {getElementById: id => id === 'createDealForm' ? form : field(id)},
  payinRubIsNet: false,
  formatNumber: value => Number(value).toLocaleString('ru-RU'),
  setTimeout: callback => callback(), calculateProfit: () => {},
  history: {replaceState: () => {}}, window: {location: {pathname: '/crm', search: ''}},
  console: {log: () => {}},
};
vm.createContext(ctx);
vm.runInContext(functions, ctx);
vm.runInContext('prefillDealForm({payin_gross_rub_reference:100000, payin_amount_usdt:1250, payin_rate_rub_usdt:80, profit_usdt:10})', ctx);
assert.equal(field('[name="payin_amount_rub"]').value, '');
assert.equal(field('[name="payin_amount_usdt"]').value, '');
assert.equal(field('[name="payin_rate_rub_usdt"]').value, '');
assert.equal(field('[name="profit_usdt"]').value, '');
assert.equal(field('payinRubHint').textContent, 'после комиссии банка');
assert.equal(field('[name="payin_amount_rub"]').required, true);
assert.match(field('payinGrossReference').textContent, /100\s000 ₽ до комиссии банка.*Введите фактически зачисленную сумму/);
assert.match(fs.readFileSync('static/calculator/calculator.js', 'utf8'),
  /payin_amount_rub: null,[\s\S]*?payin_gross_reference_rub: r\.rub_paid \|\| r\.rub_to_pay/);
console.log('calculator gross prefill leaves CRM net and dependent money for explicit input');
