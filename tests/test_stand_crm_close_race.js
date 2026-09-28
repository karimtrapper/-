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
  const stale = structuredClone(original);
  const S = {deals: [original], open: 1474};
  const pendingPut = deferred(), pendingGet = deferred(), putStarted = deferred();
  const requests = [], toasts = [];
  const ctx = {
    S, STAND: true, STAND_SHARED: ['deals', 'open'],
    standBusy: false, standPush: false, standSaveScheduled: false, standClosing: false,
    standVer: 10, standBase: {deals: [structuredClone(original)], open: 1474},
    lastPointer: 0, location: {href: ''}, Date, setTimeout, clearTimeout, AbortController,
    deal: id => S.deals.find(d => d.id === id),
    now: () => '28.09', log: (d, msg) => d.log.push(msg),
    render: () => {}, toast: msg => toasts.push(msg),
    load: () => ({deals: [], open: null}), migrate: x => x,
    standClone: structuredClone, standTyping: () => false,
    crmGaps: () => [], crmPayloadFinal: () => ({deal_kind: 'exchange'}),
    crmEditDiff: () => [], usd: n => '$' + n,
    fetch: (url, options) => {
      requests.push({url, options});
      if (url === '/api/stand/state' && !options) return pendingGet.promise;
      if (url === '/api/stand/state') {
        putStarted.resolve(JSON.parse(options.body).data);
        return pendingPut.promise;
      }
      assert.equal(url, '/api/stand/deals/1474/crm-close');
      const body = JSON.parse(options.body);
      assert.equal(body.version, 11);
      const closed = structuredClone(S);
      closed.deals[0].closed = true;
      closed.deals[0].crmDealId = 2;
      closed.deals[0].step = 'done';
      return Promise.resolve({status: 201, json: async () => ({success: true,
        deal: {id: 2}, version: 12, data: closed})});
    },
  };
  vm.createContext(ctx);
  vm.runInContext([
    source('standSnapshot'), source('standApply'), source('standPull', true),
    source('standSave', true), source('standWaitSaved', true),
    source('sentToggle'), source('crmPushClose', true),
    `function save(){ standSave(); }`,
  ].join('\n'), ctx);

  const pulling = ctx.standPull(false);
  ctx.sentToggle(1474);
  const sent = await putStarted.promise;
  assert.equal(sent.deals[0].sentToClient, true);
  const closing = ctx.crmPushClose(1474);
  pendingGet.resolve({status: 200, json: async () => ({success: true,
    version: 10, data: {deals: [stale]}})});
  await pulling;
  assert.equal(S.deals[0].sentToClient, true, 'stale GET must not overwrite pending sent toggle');
  assert.equal(requests.filter(x => x.url.includes('crm-close')).length, 0,
    'close must await the stand PUT response');
  pendingPut.resolve({status: 200, json: async () => ({success: true,
    version: 11, data: sent})});
  await closing;
  assert.equal(requests.filter(x => x.url.includes('crm-close')).length, 1);
  assert.equal(S.deals[0].crmDealId, 2);
  assert.equal(S.deals[0].closed, true);
  assert.ok(toasts.some(x => x.includes('Сделка закрыта')));
  console.log('T24 pending save / reordered GET / one-click close PASS');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
