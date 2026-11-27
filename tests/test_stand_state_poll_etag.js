const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const html = fs.readFileSync('static/stand/tasks.html', 'utf8');
const source = html.match(/^async function standPull\([^]*?^}/m);
assert.ok(source, 'standPull source');
const reply = (version, etag, marker) => ({status: 200, headers: {get: () => etag},
  json: async () => ({success: true, version, data: {marker}, role: 'operator',
    docAgentProfiles: {}, docAgentAccounts: {}, demoEnabled: false})});
const deferred = () => { let resolve; const promise = new Promise(r => {resolve = r;}); return {promise, resolve}; };

function setup() {
  const S = {role: 'operator', marker: 'old'};
  const calls = [], renders = [];
  const ctx = {S, standVer: 1, standGetEtag: '"A"', standPullPending: false,
    standBusy: false, standPush: false, standSaveScheduled: false, standClosing: false,
    standLoadError: false, standDemoEnabled: false, STAND_DOC_AGENT_META: null,
    lastPointer: 0, brokerSentSubmitPointer: false, standTyping: () => false,
    fetch: (_, options) => {calls.push(options); return Promise.resolve(reply(2, '"B"', 'new'));},
    standClone: x => x, standApply: x => {S.marker = x.marker;}, render: () => renders.push(S.marker),
    Date, Error, location: {href: ''}};
  vm.createContext(ctx); vm.runInContext(source[0], ctx);
  return {ctx, S, calls, renders};
}

(async () => {
  const t = setup();
  t.ctx.standTyping = () => true;
  await t.ctx.standPull(false);
  assert.equal(t.ctx.standVer, 1);
  assert.equal(t.ctx.standGetEtag, '"A"', 'discarded data must not advance validator');
  assert.equal(t.S.marker, 'old');
  t.ctx.standTyping = () => false;
  await t.ctx.standPull(false);
  assert.equal(t.ctx.standVer, 2);
  assert.equal(t.ctx.standGetEtag, '"B"');
  assert.equal(t.S.marker, 'new');
  assert.equal(t.calls[1].headers['If-None-Match'], '"A"');

  // Reset can replace data and generation while the numeric version stays equal.
  t.ctx.fetch = async () => reply(2, '"C"', 'reset-data');
  await t.ctx.standPull(false);
  assert.equal(t.S.marker, 'reset-data');
  assert.equal(t.ctx.standGetEtag, '"C"');

  const slow = deferred(); let count = 0;
  t.ctx.fetch = () => {count++; return slow.promise;};
  const inFlight = t.ctx.standPull(false);
  await t.ctx.standPull(false);
  assert.equal(count, 1, 'slow poll must not start overlapping GETs');
  t.ctx.standVer = 3; // A PUT finished while the old GET was in flight.
  slow.resolve(reply(2, '"stale"', 'stale-data'));
  await inFlight;
  assert.equal(t.ctx.standVer, 3);
  assert.equal(t.ctx.standGetEtag, '"C"', 'late GET must not replace accepted validator');
  assert.equal(t.S.marker, 'reset-data');
  t.ctx.fetch = async () => reply(4, '"D"', 'colleague-data');
  await t.ctx.standPull(false);
  assert.equal(t.ctx.standVer, 4);
  assert.equal(t.S.marker, 'colleague-data');
  assert.equal(t.ctx.standGetEtag, '"D"');
  console.log('stand poll ETag typing, reset, overlap and late GET PASS');
})().catch(error => {console.error(error); process.exitCode = 1;});
