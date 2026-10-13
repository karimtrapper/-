const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../static/stand/tasks.html'), 'utf8');
const source = ['s14PingBlock', 's14Ping'].map(name => {
  const found = html.match(new RegExp(`^function ${name}\\([^]*?^}|^async function ${name}\\([^]*?^}`, 'm'));
  assert.ok(found, name);
  return found[0];
}).join('\n');
const deal = {id: 9308, step: 's14', s14Ping: {at: Date.now(), by: 'Елизавета', text: 'Проверь приход'}};
const calls = [];
const ctx = {
  S: {role: 'manager'}, standVer: 7, Date, htmlText: value => String(value),
  deal: () => deal, document: {getElementById: () => ({value: 'Клиент оплатил'})},
  standAction: async (route, payload) => { calls.push([route, payload]); return {success: true}; },
  toast: () => {},
};
vm.createContext(ctx);
vm.runInContext(source, ctx);
assert.match(ctx.s14PingBlock(deal, true), /Пингануть операциониста/);
assert.match(ctx.s14PingBlock(deal, false), /Елизавета.*Проверь приход/);
assert.doesNotMatch(ctx.s14PingBlock(deal, false), /Пингануть операциониста/);
ctx.s14Ping(9308).then(() => {
  assert.equal(calls.length, 1);
  assert.equal(calls[0][0], '/api/stand/s14/ping');
  assert.equal(calls[0][1].text, 'Клиент оплатил');
  ctx.S.role = 'operator';
  return ctx.s14Ping(9308);
}).then(() => {
  assert.equal(calls.length, 1);
  assert.match(html, /\(S\.role==='manager'\|\|S\.role==='admin'\)&&d\.step==='s14'\?s14PingBlock\(d,true\)/);
  assert.match(html, /S\.role==='operator'&&d\.step==='s14'\?s14PingBlock\(d,false\)/);
  console.log('s14 ping UI and role routing OK');
}).catch(error => {console.error(error); process.exitCode = 1;});
