// Deterministic baseline reproduction of the sent -> pending save -> CRM close race.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../static/stand/tasks.html'), 'utf8');
function source(name, async = false) {
  const re = new RegExp('^' + (async ? 'async ' : '') + 'function ' + name + '\\([^]*?^}', 'm');
  const match = html.match(re);
  assert.ok(match, `${name} missing`);
  return match[0];
}
function deferred() {
  let resolve;
  const promise = new Promise(r => { resolve = r; });
  return {promise, resolve};
}
async function main() {
  const original = {id: 1474, code: 'СД-1474', sentToClient: false,
    pay: {}, type: 'Обмен валюты', step: 's27', closed: false, crmDealId: null, log: []};
  const S = {deals: [original], open: 1474};
  const pendingPut = deferred();
  const pendingGet = deferred();
  const pendingPost = deferred();
  const firstPut = deferred();
  const requests = [];
  const toasts = [];
  const ctx = {
    S, STAND_SHARED: ['deals', 'open'], standBusy: false, standPush: false,
    standVer: 10, standBase: {deals: [structuredClone(original)], open: 1474},
    lastPointer: 0, location: {href: ''},
    deal: id => S.deals.find(d => d.id === id),
    now: () => '28.09', log: (d, msg) => d.log.push(msg),
    render: () => {}, toast: msg => toasts.push(msg),
    load: () => ({deals: [], open: null}), migrate: x => x,
    standClone: structuredClone, standTyping: () => false,
    crmGaps: () => [], crmPayloadFinal: () => ({payin_amount_usdt: 3257.52}),
    crmEditDiff: () => [], usd: n => '$' + n,
    setTimeout: () => {}, Date,
    fetch: (url, options) => {
      requests.push({url, options});
      if (url === '/api/stand/state') {
        if (!options) return pendingGet.promise;
        const snapshot = JSON.parse(options.body).data;
        firstPut.resolve(snapshot);
        return pendingPut.promise;
      }
      assert.equal(url, '/api/deals');
      return pendingPost.promise;
    },
  };
  vm.createContext(ctx);
  vm.runInContext([
    source('standSnapshot'), source('standApply'), source('standPull', true), source('standSave', true),
    source('sentToggle'), source('closeDeal'), source('crmPushClose', true),
    `function save(){ standSave(); }`,
  ].join('\n'), ctx);

  const pulling = ctx.standPull(false);
  ctx.sentToggle(1474);
  const s27Snapshot = await firstPut.promise;
  assert.equal(s27Snapshot.sentToClient, undefined); // snapshot is the board
  assert.equal(s27Snapshot.deals[0].sentToClient, true);
  assert.equal(s27Snapshot.deals[0].closed, false);
  const closing = ctx.crmPushClose(1474);
  pendingPut.resolve({status: 200, json: async () => ({success: true,
    version: 11, data: s27Snapshot})});
  await new Promise(resolve => setImmediate(resolve));
  pendingGet.resolve({status: 200, json: async () => ({success: true,
    version: 12, data: s27Snapshot})});
  await pulling;
  pendingPost.resolve({status: 201, json: async () => ({success: true, deal: {id: 2}})});
  await closing;
  assert.equal(requests.filter(x => x.url === '/api/deals').length, 1);
  assert.equal(original.closed, true);
  assert.ok(toasts.some(x => x.includes('Сделка закрыта')));
  // The earlier GET replaces S.deals while CRM POST is pending. closeDeal
  // mutates its detached d; the queued save serializes the replacement.
  assert.equal(S.deals[0].closed, false);
  assert.equal(S.deals[0].crmDealId, null);
  console.log('T24 BASELINE FAIL reproduced: CRM #2 and success toast, board s27/open');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
