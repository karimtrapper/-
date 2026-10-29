const assert = require('node:assert/strict');
const fs = require('node:fs');
const js = fs.readFileSync('static/calculator/calculator.js', 'utf8');
const body = js.match(/function initB2Layout\(\)\s*\{[^]*?\n\}/m)[0];
const idx = s => body.indexOf(s);
const barCopyIdx = idx("bar.appendChild(copy)");
const moreCreateDealIdx = idx("more.appendChild(document.getElementById('createDealSection'))");
assert.ok(barCopyIdx >= 0, 'кнопка копирования должна добавляться в bar');
assert.ok(moreCreateDealIdx >= 0, 'секция создания сделки CRM должна уходить в more (второстепенное)');
assert.ok(barCopyIdx < moreCreateDealIdx,
  'кнопка копирования (bar, главное) должна конструироваться раньше, чем секция CRM уходит в more (второстепенное)');
console.log('copy-primary DOM order: PASS');
