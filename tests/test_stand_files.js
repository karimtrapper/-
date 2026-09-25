// Проверка реальных вложений задачника без сети и браузера.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../static/stand/tasks.html'), 'utf8');
const names = ['docDownload', 'docOpen', 'fileValid', 'fileBlob', 'demoPdfData',
  'filesOf', 'fileSync', 'fileAdd', 'fileAddReal', 'fileAppend', 'fileDel'];
const source = names.map(name => {
  const found = html.match(new RegExp(`^function ${name}\\([^]*?^}`, 'm'));
  assert.ok(found, `нет функции ${name}`);
  return found[0];
}).join('\n');

function fixture() {
  const d = {id: 1, code: 'СД-1', docs: {}, docMeta: {}, files: {}, log: []};
  const S = {deals: [d]};
  const toasts = [], clicks = [], opened = [];
  const input = {files: [], click: () => clicks.push('picker')};
  const link = {style: {}, click: () => clicks.push('download'), remove: () => {}};
  const ctx = {S, DOCT: {receipt: 'Чек'}, deal: () => d, now: () => '24.09',
    save: () => {}, render: () => {}, log: (x, s) => x.log.push(s),
    toast: s => toasts.push(s), document: {createElement: tag => tag === 'input' ? input : link,
      body: {appendChild: () => {}}}, window: {open: url => {opened.push(url);return {}; }},
    URL: {createObjectURL: () => 'blob:fixture', revokeObjectURL: () => {}},
    FileReader: class {readAsDataURL() {this.result = ctx.readerResult;this.onload();}},
    Blob, Uint8Array, atob, btoa, setTimeout: fn => fn(), Math, Number, String, Object};
  vm.createContext(ctx);vm.runInContext(source, ctx);
  return {ctx, d, S, toasts, clicks, opened, input};
}

{
  const {ctx, d, clicks, opened} = fixture();
  ctx.fileAdd(1, 'receipt', true);
  assert.equal(d.docs.receipt, true);
  assert.equal(d.files.receipt[0].demo, true);
  assert.equal(d.files.receipt[0].file, 'DEMO_receipt.pdf');
  assert.ok(ctx.fileValid(d.files.receipt[0]));
  const blob = ctx.fileBlob(d.files.receipt[0]);
  assert.equal(blob.type, 'application/pdf');
  ctx.docDownload(1, 'receipt'); // раньше ext=undefined бросал TypeError
  ctx.docOpen(1, 'receipt', 0);
  assert.ok(clicks.includes('download'));
  assert.equal(opened[0], 'blob:fixture');
}
{
  const {ctx, d, toasts} = fixture();
  ctx.docDownload(1, 'receipt');
  assert.ok(toasts[0].includes('не загружен'));
  assert.equal(d.docs.receipt, false);
  const pdf = ctx.demoPdfData();
  for (const [mime, name] of [['text/html', 'x.html'], ['image/svg+xml', 'x.svg'],
      ['application/javascript', 'x.js']]) {
    assert.equal(ctx.fileValid({file: name, mime, data: pdf}), false);
  }
  assert.equal(ctx.fileValid({file: 'x.pdf', mime: 'application/pdf',
    data: 'data:application/pdf;base64,' + btoa('<script>')}), false);
}
{
  const {ctx, d, input, toasts} = fixture();
  ctx.fileAdd(1, 'receipt');
  assert.equal(input.type, 'file');
  input.files = [{name: 'evil.svg', type: 'image/svg+xml', size: 100}];
  input.onchange();
  assert.equal((d.files.receipt || []).length, 0);
  assert.ok(toasts.at(-1).includes('PDF'));
  ctx.fileAdd(1, 'receipt');
  input.files = [{name: 'big.pdf', type: 'application/pdf', size: 2 * 1024 * 1024 + 1}];
  input.onchange();
  assert.equal((d.files.receipt || []).length, 0);
  assert.ok(toasts.at(-1).includes('2 МБ'));
  ctx.fileAdd(1, 'receipt');
  input.files = [{name: '<receipt>.pdf', type: 'application/pdf', size: 100}];
  ctx.readerResult = ctx.demoPdfData();
  input.onchange();
  assert.equal(d.files.receipt[0].file, '_receipt_.pdf');
  assert.equal(d.docs.receipt, true);
}
{
  const {ctx, d, S, input, toasts} = fixture();
  S.deals.push({files: {receipt: [{data: 'x'.repeat(8 * 1024 * 1024)}]}});
  ctx.fileAdd(1, 'receipt');
  input.files = [{name: 'receipt.pdf', type: 'application/pdf', size: 100}];
  input.onchange();
  assert.equal((d.files.receipt || []).length, 0);
  assert.ok(toasts.at(-1).includes('8 МБ'));
}
console.log('stand files: 4 сценария PASS');
