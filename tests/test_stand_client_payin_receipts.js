// Проверка нового блока чеков на настоящих функциях задачника.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const html = fs.readFileSync('static/stand/tasks.html', 'utf8');
const names = ['fileValid', 'filesOf', 'fileSync', 'fileAppend', 'fileDel',
  'clientPayinCanAdd', 'clientPayinCanDelete', 'clientPayinNote',
  'clientPayinBlock', 'docListRows'];
const source = names.map(name => {
  const match = html.match(new RegExp(`^(?:async )?function ${name}\\([^]*?^}`, 'm'));
  assert.ok(match, name);
  return match[0];
}).join('\n');

const safe = v => String(v == null ? '' : v).replace(/[&<>"']/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const deal = {id: 1485, step: 's12', docs: {}, files: {}, log: []};
const ctx = {S: {role: 'manager', deals: [deal]}, standMe: 'manager', standMeId: 1,
  STAND_EMPLOYEES: [{id: 1, display_name: 'Елизавета'}],
  ROLES: {manager: {n: 'Елизавета'}}, deal: () => deal,
  managerDraftDocTarget: () => null, htmlText: safe, now: () => '12.10',
  log: (d, text) => d.log.push({text}), save: () => {}, render: () => {},
  toast: () => {}, DOCT: {clientPayinReceipt: 'Чеки клиента об оплате'},
  docFileOf: () => null, doctOf: () => 'Документ', docIssuedTitle: () => '',
  docExt: () => '', fileUrl: () => '', atob, crypto: {randomUUID: () => '12345678-1234-1234-1234-123456789abc'},
  STAND: false, SCREEN: false, SNAP: false};
vm.createContext(ctx);
vm.runInContext(source, ctx);

assert.match(ctx.clientPayinBlock(deal), /приход подтверждает только операционист/i);
assert.doesNotMatch(ctx.clientPayinBlock(deal), /Загрузить/);
deal.docsSent = {at: '12.10', version: 3};
assert.match(ctx.clientPayinBlock(deal), /Загрузить/);
const data = 'data:application/pdf;base64,' + Buffer.from('%PDF-1.4\nreceipt').toString('base64');
(async () => {
  await ctx.fileAppend(1485, 'clientPayinReceipt', {file: 'client.pdf', size: '1 КБ',
    at: '12.10', mime: 'application/pdf', bytes: 16, data, demo: false});
  assert.equal(deal.files.clientPayinReceipt.length, 1);
  assert.equal(deal.docs.clientPayinReceipt, undefined);
  assert.match(deal.log[0].text, /Чек клиента прикреплён · client.pdf · Елизавета/);
  assert.match(ctx.clientPayinBlock(deal), /client.pdf/);
  assert.match(ctx.docListRows(deal).client.join(''), /Чек клиента об оплате/);
  ctx.clientPayinNote(1485, 0, '50 000 ₽ · 12.10 · Иванов');
  assert.match(ctx.clientPayinBlock(deal), /50 000 ₽/);
  ctx.S.role = 'operator'; ctx.standMe = 'operator'; ctx.standMeId = 2;
  assert.doesNotMatch(ctx.clientPayinBlock(deal), /Убрать/);
  ctx.fileDel(1485, 'clientPayinReceipt', 0);
  assert.equal(deal.files.clientPayinReceipt.length, 1);
  ctx.standMe = 'admin'; ctx.standMeId = 3;
  ctx.fileDel(1485, 'clientPayinReceipt', 0);
  assert.equal(deal.files.clientPayinReceipt.length, 0);
  assert.match(deal.log.at(-1).text, /Чек клиента удалён/);
  console.log('client payin receipts UI: passed');
})().catch(error => {console.error(error); process.exitCode = 1;});
