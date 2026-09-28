const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../static/stand/tasks.html'), 'utf8');
function source(name, async = false) {
  const match = html.match(new RegExp('^' + (async ? 'async ' : '') + 'function ' + name + '\\([^]*?^}', 'm'));
  assert.ok(match, name + ' missing');
  return match[0];
}
let answerFirst;
const first = new Promise(resolve => { answerFirst = resolve; });
const requests = [];
const draft = {id: 1474, manual: true, manualNew: true, step: 'manual', client: 'before'};
const S = {deals: [draft]};
const ctx = {S, STAND_SHARED: ['deals'], standVer: 1, standBase: {deals: []},
  standBusy: false, standPush: false, standSaveScheduled: false,
  standClone: structuredClone, standTyping: () => false,
  standApply: () => { throw new Error('queued response replaced local draft'); },
  render: () => {}, toast: () => {}, setTimeout, JSON,
  fetch: (_url, options) => {
    requests.push(JSON.parse(options.body));
    return requests.length === 1 ? first : Promise.resolve({status: 200,
      json: async () => ({success: true, version: 3, data: {deals: [requests[1].data.deals[0]]}})});
  },
};
vm.createContext(ctx);
vm.runInContext(source('standSnapshot') + '\n' + source('standSave', true), ctx);
(async () => {
  const firstSave = ctx.standSave();
  assert.equal(requests[0].data.deals[0].client, 'before');
  draft.client = 'edited while first response pending';
  await ctx.standSave();
  answerFirst({status: 200, json: async () => ({success: true, version: 2,
    data: {deals: [{id: 1474, manual: true, manualNew: true, step: 'manual',
                   client: 'before', originMode: 'manual'}]}})});
  await firstSave;
  await new Promise(resolve => setTimeout(resolve, 160));
  assert.equal(requests.length, 2);
  assert.equal(requests[1].version, 2);
  assert.equal(requests[1].data.deals[0].originMode, 'manual');
  assert.equal(requests[1].data.deals[0].client, 'edited while first response pending');
  console.log('T24 server origin ack + queued local edit retained PASS');
})().catch(error => { console.error(error); process.exitCode = 1; });
