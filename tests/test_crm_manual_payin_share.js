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
const poolMapping = adapter.match(/amount:d\.payType==='По реквизитам'&&d\.rubReceivingAccount\?\.mode==='flowsole'&&x\._auto\s*\?\s*null\s*:\s*crmDraftNum\(x\.amount_usdt\)/);
assert.ok(poolMapping, 'task adapter distinguishes auto full-hash lookup from explicit pool share');
const mappedShare = new Function('d', 'x', 'crmDraftNum', `return (${poolMapping[0].slice('amount:'.length)});`);
const flow = {payType:'По реквизитам',rubReceivingAccount:{mode:'flowsole'}};
assert.equal(mappedShare(flow,{amount_usdt:500,_auto:true},Number),null,
  'a pool selection alone stays full-hash/null');
assert.equal(mappedShare(flow,{amount_usdt:100,_auto:false},Number),100,
  'a manually set pool share stays numeric through task adapter serialization');
const savedShareSource = adapter.match(/^function crmDraftSavedFlowShare\([^]*?^}/m);
assert.ok(savedShareSource, 'custom editor preserves the saved Flow Sole hash share on reopen/save');
const savedFlowShare = new Function(`${savedShareSource[0]}; return crmDraftSavedFlowShare;`)();
assert.equal(savedFlowShare({payinHashes:[{hash:'same',network:'trc20',amount:100}]},
  'same','TRC20',500),100,'unchanged stored numeric share survives a changed declared amount');
assert.equal(savedFlowShare({payinHashes:[{hash:'same',network:'trc20',amount:null}]},
  'same','trc20',500),null,'unchanged new full-transfer hash remains null');
assert.equal(savedFlowShare({payinHashes:[{hash:'old',network:'trc20',amount:100}]},
  'new','trc20',500),null,'new manual hash does not inherit another transfer share');
assert.equal(savedFlowShare({payinHashes:[{hash:'same',network:'trc20',amount:100}]},
  'same','erc20',500),null,'changed network does not inherit a prior share');
assert.match(adapter, /amount:flowSole\?crmDraftSavedFlowShare\(d,c\.payinTxHash,c\.payinNetwork,payinUsdt\):payinUsdt/,
  'custom task form preserves an existing Flow Sole share without deriving a new one');

console.log('CRM manual hash share: PASS');
