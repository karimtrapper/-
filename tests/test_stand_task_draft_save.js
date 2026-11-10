const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const html = fs.readFileSync('static/stand/tasks.html', 'utf8');
const source = html.match(/^async function createGo\([^]*?^}/m);
assert.ok(source, 'createGo is async');

function setup(savedResult) {
  const draft = {clientId: 1, client: 'Synthetic Auto', type: 'Оплата авто',
    kind: 'Фрихолд', payType: 'По реквизитам', cur: 'fhusd',
    invoiceCurrency: 'usd', sum: '45000', note: 'Synthetic note'};
  const S = {draft, deals: [], open: null, view: 'draft'};
  const notices = [];
  let creates = 0, resolves;
  const pending = new Promise(resolve => { resolves = resolve; });
  const ctx = {S, STAND: true, standBase: {deals: []}, STEPS: {s5: {title: 'Ответить курс'}},
    draftValid: () => true, ensureClient: () => {}, clientById: () => ({docs: false}),
    draftAmounts: () => ({invoiceUsd: 45000, requestedUsd: 45000,
      autoRequestMode: 'usd', invoiceCurrency: 'usd'}),
    newDeal: options => {
      creates++;
      const d = {...options, id: 3402, createdAt: 'synthetic:3402', log: []};
      S.deals.unshift(d);
      return d;
    },
    log: (d, message) => d.log.push(message),
    save: () => {}, render: () => {}, toast: message => notices.push(message),
    standWaitSaved: () => pending, standSaveError: result => result.error || 'Failed',
  };
  vm.createContext(ctx);
  vm.runInContext(source[0], ctx);
  return {ctx, S, draft, notices, resolve: serverDeals => {
    if(serverDeals)ctx.standBase = {deals: serverDeals};
    resolves(savedResult);
  }, creates: () => creates};
}

(async () => {
  {
    const t = setup({ok: false, error: 'Сервер отклонил сохранение'});
    const first = t.ctx.createGo();
    const duplicate = t.ctx.createGo();
    assert.equal(t.creates(), 1, 'double click cannot create a second local deal');
    assert.equal(t.S.draft, t.draft, 'form stays open while saving');
    assert.equal(t.notices.length, 0, 'no optimistic success');
    t.resolve();
    await Promise.all([first, duplicate]);
    assert.equal(t.S.draft, t.draft, 'rejected save keeps original form');
    assert.equal(t.S.deals.length, 0, 'rejected local deal is removed');
    assert.equal(t.S.view, 'draft');
    assert.match(t.draft.createError, /отклонил/);
    assert.equal(t.notices.length, 0);
  }
  {
    const t = setup({ok: false, error: 'conflict'});
    const saving = t.ctx.createGo();
    const colleague = {...t.S.deals[0], client: 'Colleague Auto'};
    t.S.deals = [colleague]; // ответ 409 уже применил серверную доску
    t.resolve();
    await saving;
    assert.equal(t.S.deals.length, 1);
    assert.equal(t.S.deals[0], colleague, 'rollback must preserve server deal with same ID/time');
    assert.equal(t.S.draft, t.draft);
  }
  {
    const t = setup({ok: true});
    const saving = t.ctx.createGo();
    assert.equal(t.S.draft, t.draft);
    t.resolve(t.S.deals.map(x => ({...x})));
    await saving;
    assert.equal(t.S.draft, null);
    assert.equal(t.S.open, 3402);
    assert.equal(t.S.view, 'deal');
    assert.equal(t.S.deals[0].autoPayment, true);
    assert.equal(t.S.deals[0].step, 's5');
    assert.match(t.notices[0], /Заявка создана/);
  }
  {
    const t = setup({ok: true});
    const saving = t.ctx.createGo();
    const ours = {...t.S.deals[0], id: 3403};
    const concurrent = {...t.S.deals[0], id: 3402};
    t.resolve([concurrent, ours]);
    await saving;
    assert.equal(t.S.open, 3403, 'concurrent same-client auto gets original ID; ours is remapped');
  }
  console.log('auto task createGo confirmation and rejection: PASS');
})().catch(error => { console.error(error); process.exitCode = 1; });
