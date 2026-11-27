// Банковская выписка в Excel: выбор и перетаскивание идут через тот же upload.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const html = fs.readFileSync(path.join(__dirname, '../static/stand/tasks.html'), 'utf8');
const names = ['fileValid', 'fileAddReal', 'fileAdd', 'fileDrop'];
const code = names.map(name => {
  const found = html.match(new RegExp(`^function ${name}\\([^]*?^}`, 'm'));
  assert.ok(found, `нет функции ${name}`);
  return found[0];
}).join('\n');

(async () => {
  const uploaded = [], toasts = [];
  const picker = {click() { this.clicked = true; }};
  const ctx = {
    STAND: true, SCREEN: false, SNAP: false, File, atob,
    document: {createElement: () => picker},
    toast: value => toasts.push(value),
    fileOptimizeImage: async file => file,
    fileUploadServer: async (id, kind, file) => uploaded.push({id, kind, name: file.name, mime: file.type}),
  };
  vm.createContext(ctx);
  vm.runInContext('let fileUploadQueue=Promise.resolve();\n' + code, ctx);
  ctx.fileAdd(1489, 'bankCreditEvidence');
  assert.match(picker.accept, /\.xls,\.xlsx/);
  const excel = new File(['PK\x03\x04workbook'], 'bank.xlsx', {type: 'application/octet-stream'});
  picker.files = [excel];
  picker.onchange();
  await vm.runInContext('fileUploadQueue', ctx);
  assert.deepEqual(uploaded, [{id: 1489, kind: 'bankCreditEvidence', name: 'bank.xlsx',
    mime: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}]);
  ctx.fileDrop({preventDefault() {}, stopPropagation() {}, dataTransfer: {files: [excel]},
    currentTarget: {classList: {remove() {}}}}, 1489, 'bankCreditEvidence');
  await vm.runInContext('fileUploadQueue', ctx);
  assert.equal(uploaded.length, 2);
  assert.equal(ctx.fileValid({file: 'bank.xlsx', mime: uploaded[0].mime,
    data: '__detached__'}, 'bankCreditEvidence'), true);
  assert.equal(ctx.fileValid({file: 'bank.xlsx', mime: uploaded[0].mime,
    data: '__detached__'}, 'receipt'), false);
  await ctx.fileAddReal(1489, 'receipt', excel);
  assert.equal(uploaded.length, 2);
  assert.match(toasts.at(-1), /PDF, PNG, JPEG или WEBP/);
  console.log('bank Excel picker, drop, MIME fallback, scope PASS');
})().catch(error => { console.error(error); process.exitCode = 1; });
