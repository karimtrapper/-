// Старые серверные события журнала без ts и role не выводят undefined.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const html = fs.readFileSync('static/stand/tasks.html', 'utf8');
const code = ['htmlText', 'employeeName', 'logWhen', 'logAuthor', 'logMeta'].map(name => {
  const match = html.match(new RegExp(`^function ${name}\\([^]*?^}`, 'm'));
  assert.ok(match, `Нет ${name}`);
  return match[0];
}).join('\n');
const ctx = {
  ROLES: {operator: {t: 'Операционист'}},
  STAND_EMPLOYEES: [{id: 1, display_name: 'Настя', role: 'operator', login_disabled: true},
    {id: 2, display_name: 'Ирина', role: 'operator'}],
};
vm.createContext(ctx);
vm.runInContext(code, ctx);

const old = {at: 1791880000000, text: 'Приход подтверждён'};
assert.doesNotMatch(ctx.logMeta(old), /undefined|от —/);
assert.match(ctx.logMeta(old), /Система.*Приход подтверждён/);
assert.match(ctx.logMeta({role: 'operator', ts: '13.10, 10:00', text: 'Сверил'}),
  /от Операционист · 13.10, 10:00 · Сверил/);
assert.match(ctx.logMeta({role: 'operator', by: 1, text: 'Сверила'}), /от Настя/);
assert.match(ctx.logMeta({role: 'operator', byId: 2, by: 'Ирина прежнее имя', text: 'Сверила'}),
  /от Ирина прежнее имя/);
assert.match(ctx.logMeta({role: 'operator', actorId: 1, text: 'Сверила'}), /от Настя/);
assert.match(ctx.logMeta({role: 'operator', by: 5, text: 'Сверила'}), /от Операционист/);
assert.doesNotMatch(html, /last\.ts|r\.l\.ts|\$\{l\.ts\}/);
console.log('legacy stand log: PASS');
