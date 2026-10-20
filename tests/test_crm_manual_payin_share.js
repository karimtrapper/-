const assert = require('node:assert/strict');
const fs = require('node:fs');

const crm = fs.readFileSync('static/crm/crm.html', 'utf8');
const adapter = fs.readFileSync('static/stand/crm-draft-adapter.js', 'utf8');

// Execute the expressions used by the real manual-hash fallbacks. A provider
// lookup of the whole transaction is not an explicitly selected Flow Sole share.
const standardFallback = crm.match(/: \(data\.payin_tx_hash \? \[\{([\s\S]*?)\}\] : \[\]\);/);
assert.ok(standardFallback, 'standard CRM manual hash fallback');
const standardExpr = standardFallback[1].match(/amount_usdt:\s*([\s\S]*?),\s*$/m);
assert.ok(standardExpr, 'standard CRM manual share');
const standardShare = new Function('data', `return (${standardExpr[1]});`);
assert.equal(standardShare({payin_method: 'crypto_direct', payin_amount_usdt: 700}), 700);
assert.equal(standardShare({payin_method: 'sber_reqs', payin_amount_usdt: 700}), 700);
assert.equal(standardShare({payin_method: 'crypto_direct'}), null);
assert.equal(standardShare({payin_method: 'flow_sole_reqs', payin_amount_usdt: 700}), null);

const adapterFallback = adapter.match(/d\.payinHashes\.push\(\{([\s\S]*?)\}\);/);
assert.ok(adapterFallback, 'task CRM manual hash fallback');
const adapterExpr = adapterFallback[1].match(/amount:\s*(crmDraftRead\(r,'payinMethod'\)[^,]*),/);
assert.ok(adapterExpr, 'task CRM manual share');
const adapterShare = new Function('method', 'amount',
  `const r={}; const a={manualTx:{amount}}; const crmDraftRead=()=>method; return (${adapterExpr[1]});`);
assert.equal(adapterShare('crypto_direct', 700), 700);
assert.equal(adapterShare('sber_reqs', 700), 700);
assert.equal(adapterShare('flow_sole_reqs', 700), null);
assert.match(adapter, /amount:flowSole\?null:payinUsdt/, 'custom task form keeps the same distinction');

console.log('CRM manual hash share: PASS');
