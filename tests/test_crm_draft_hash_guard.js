const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const source = fs.readFileSync(path.join(__dirname, '../static/stand/crm-draft-adapter.js'), 'utf8');

function adapter(fetch) {
  const messages = [];
  const context = vm.createContext({
    Map, URL, location: {origin: 'http://localhost'},
    window: {fetch}, toast: message => messages.push(message),
    document: {getElementById: () => null},
    deal: () => ({}),
  });
  vm.runInContext(source, context);
  return {context, messages};
}

// Auto-vivifying DOM element stub: any id not explicitly seeded still answers
// to .value/.style/.checked/etc. so crmDraftLayout's housekeeping (hiding
// sections, toggling checkboxes) doesn't crash on ids this test doesn't care about.
function elementRegistry(seed) {
  const byId = new Map(Object.entries(seed));
  return key => {
    if (!byId.has(key)) byId.set(key, {value: '', style: {}, checked: false,
      textContent: '', disabled: false, parentElement: null, appendChild: () => {}});
    return byId.get(key);
  };
}

function fullDraft(hash) {
  const getElementById = elementRegistry({
    payinManualHash: {value: hash},
    payinManualNetwork: {value: 'trc20'},
    payin_amount_usdt: {value: ''},
    payinTxWarn: {textContent: '', style: {}},
  });
  return {
    form: {querySelectorAll: () => []},
    core: {
      payinTxPool: [], sberParts: [], payinExtra: [], stdAgents: [], customAgents: [],
      customUsdtMode: {}, mfPayoutTxPool: [], payoutTxPool: [],
      resetPayinTxPool: () => {}, stdAgentsLoad: () => {}, customAgentsLoad: () => {},
      onCustomUsdtInput: () => {}, applyPayinMethodFields: () => {},
    },
    root: {getElementById, querySelector: () => null},
    manualTx: null,
  };
}

function active(pool = [], hash = '') {
  const fields = {
    payinManualHash: {value: hash},
    payinManualNetwork: {value: 'trc20'},
    payin_amount_usdt: {value: ''},
    payinTxWarn: {textContent: '', style: {}},
  };
  return {
    core: {payinTxPool: pool.map(value => ({hash: value, network: 'trc20'}))},
    root: {
      getElementById: key => fields[key] || null,
      querySelector: () => null,
    },
    manualTx: null,
  };
}

test('one or two selected incoming transfers are recognized in the manual field', () => {
  const {context} = adapter(() => { throw new Error('unexpected network request'); });
  for (const hashes of [['a'.repeat(64)], ['a'.repeat(64), 'b'.repeat(64)]]) {
    const draft = active(hashes, hashes[0]);
    assert.equal(context.crmDraftManualHashFromPool(draft, hashes[0], 'trc20'), true);
    assert.equal(context.crmDraftManualHashFromPool(draft, hashes[0], 'TRC-20'), true);
    assert.equal(context.crmDraftManualHashFromPool(draft, hashes[0], 'erc20'), false);
    assert.equal(context.crmDraftManualHashFromPool(draft, hashes[0], 'ERC-20'), false);
  }
});

test('a genuinely manual hash still uses network verification', async () => {
  const {context} = adapter(async () => ({
    ok: true, json: async () => ({success: true, amount_usdt: 125}),
  }));
  const draft = active(['a'.repeat(64)], 'b'.repeat(64));
  assert.equal(context.crmDraftManualHashFromPool(draft, 'b'.repeat(64), 'trc20'), false);
  await context.crmDraftLookupPayin(draft);
  assert.equal(draft.manualTx.amount, 125);
  assert.equal(draft.manualTx.network, 'trc20');
});

test('rejected manual hash remains unverified', async () => {
  const {context, messages} = adapter(async () => ({
    ok: false, json: async () => ({success: false, error: 'synthetic chain rejection'}),
  }));
  const draft = active([], 'c'.repeat(64));
  await context.crmDraftLookupPayin(draft);
  assert.equal(draft.manualTx, null);
  assert.match(messages[0], /synthetic chain rejection/);
});

test('manual hash confirmation survives a board re-render (snapshot/restore)', async () => {
  const {context} = adapter(async () => ({
    ok: true, json: async () => ({success: true, amount_usdt: 50}),
  }));
  const hash = 'd'.repeat(64);
  const draft = fullDraft(hash);
  await context.crmDraftLookupPayin(draft);
  assert.equal(draft.manualTx.amount, 50);

  const snapshot = context.crmDraftSnapshot(draft);

  // The board re-renders on every poll: crmDraftMount tears down the shadow DOM
  // form and rebuilds a fresh draft object, then restores field values from the
  // last snapshot. The hash value comes back, so confirmation must too.
  const remounted = fullDraft(hash);
  context.crmDraftRestore(remounted, snapshot);

  assert.equal(remounted.manualTx?.hash, hash);
  assert.equal(remounted.manualTx?.amount, 50);
});
