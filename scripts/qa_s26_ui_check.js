// UI-проверка на РЕАЛЬНОМ ответе close-evidence СД-1483 (из qa_s26_dump_repro.py positive_real):
// настоящие функции static/stand/tasks.html рисуют «проверено · операционист NAME · время s26», без кнопки.
// Запуск: node scripts/qa_s26_ui_check.js /tmp/claude/s26/facts-1483.json   (из корня репозитория)
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const real = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const html = fs.readFileSync('static/stand/tasks.html', 'utf8');
const source = name => { const m = html.match(new RegExp('^function ' + name + '\\([^]*?^}', 'm')); assert.ok(m, name); return m[0]; };
const ctx = { S: { role: 'manager' }, htmlText: s => String(s).replace(/</g, '&lt;'), standVer: real.version, CRM_CLOSE_STATUS: new Map() };
vm.createContext(ctx);
for (const name of ['crmCloseReason', 'crmCloseBlockers', 'crmEvidenceParts']) vm.runInContext(source(name), ctx);
const deal = { id: 1483, type: 'Оплата недвижимости', transfer: { sends: [] } };
ctx.crmCloseStatus = () => ({ version: real.version, facts: real.facts });
const when = new Date(real.at).toLocaleString('ru-RU');
for (const role of ['manager', 'operator', 'admin']) {
  ctx.S.role = role;
  const parts = ctx.crmEvidenceParts(deal);
  assert.ok(parts.receiptBtn.includes(`проверено · операционист ${real.author} · ${when}`), role + ': ' + parts.receiptBtn);
  assert.doesNotMatch(parts.receiptBtn, /<button|crmEvidence|Подтвердить/, role + ' кнопка подтверждения');
  assert.deepEqual(ctx.crmCloseBlockers(deal), [], role + ' blockers');
  for (const k of ['payinBtn', 'payoutBtn']) assert.doesNotMatch(parts[k], /<button/, role + ' ' + k);
}
// Не принят (реальные причины API): причина без кнопки «Подтвердить» для всех ролей.
for (const reason of ['operator_receipt_acceptance_missing', 'invoice_payment_or_receipt_missing']) {
  ctx.crmCloseStatus = () => ({ version: real.version, facts: real.facts.map(f => f.kind === 'receipt' ? { kind: 'receipt', ready: false, reason } : f) });
  for (const role of ['manager', 'operator', 'admin']) {
    ctx.S.role = role;
    assert.doesNotMatch(ctx.crmEvidenceParts(deal).receiptBtn, /<button|crmEvidence|Подтвердить/, reason + ' ' + role);
  }
}
ctx.crmCloseStatus = () => ({ version: real.version, facts: real.facts });
ctx.S.role = 'manager';
console.log('UI OK (real 1483 facts):', ctx.crmEvidenceParts(deal).receiptBtn.replace(/<[^>]+>/g, ''));
