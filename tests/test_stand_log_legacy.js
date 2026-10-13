// Старые серверные события журнала без ts и role не выводят undefined.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const html = fs.readFileSync('static/stand/tasks.html', 'utf8');
const code = ['logWhen', 'logMeta'].map(name => {
  const match = html.match(new RegExp(`^function ${name}\\([^]*?^}`, 'm'));
  assert.ok(match, `Нет ${name}`);
  return match[0];
}).join('\n');
const ctx = {ROLES: {operator: {n: 'Операционист'}}};
vm.createContext(ctx);
vm.runInContext(code, ctx);

const old = {at: 1791880000000, text: 'Приход подтверждён'};
assert.doesNotMatch(ctx.logMeta(old), /undefined|от —/);
assert.match(ctx.logMeta(old), /Система.*Приход подтверждён/);
assert.match(ctx.logMeta({role: 'operator', ts: '13.10, 10:00', text: 'Сверил'}),
  /от Операционист · 13.10, 10:00 · Сверил/);
assert.doesNotMatch(html, /last\.ts|r\.l\.ts|\$\{l\.ts\}/);
console.log('legacy stand log: PASS');
