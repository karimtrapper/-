// Распознавание не должно читать файлы через fetch(data:): CSP стенда (connect-src 'self') его режет.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, '../static/stand/tasks.html'), 'utf8');
const body = html.match(/^async function docParse\([^]*?^}/m)[0];
assert.ok(!/fetch\(\s*f\.data/.test(body), 'docParse не должен делать fetch(data:)');
const fn = html.match(/^function dataUrlBlob\([^]*?^}/m)[0];
const ctx = { atob: s => Buffer.from(s, 'base64').toString('binary'), Uint8Array, Blob };
vm.createContext(ctx); vm.runInContext(fn, ctx);
(async () => {
  const b = ctx.dataUrlBlob('data:application/pdf;base64,' + Buffer.from('%PDF-1.4 test').toString('base64'));
  assert.equal(b.type, 'application/pdf');
  assert.equal(Buffer.from(await b.arrayBuffer()).toString(), '%PDF-1.4 test');
  assert.throws(() => ctx.dataUrlBlob('not-a-data-url'));
  console.log('stand docparse data-url: PASS');
})();
