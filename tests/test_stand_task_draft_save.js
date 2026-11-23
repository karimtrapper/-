const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const html = fs.readFileSync('static/stand/tasks.html', 'utf8');
const source = html.match(/^async function createGo\([^]*?^}/m);
assert.ok(source, 'createGo is async');

function extracted(name) {
  const oneLine = html.match(new RegExp('^function '+name+'\\([^\\n]*\\)\\{[^\\n]*\\}$', 'm'));
  if (oneLine) return oneLine[0];
  const result = html.match(new RegExp('^(?:async )?function '+name+'\\([^]*?^}', 'm'));
  assert.ok(result, 'missing '+name);
  return result[0];
}

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
  for (const draft of [null,{manualNew:true},{manualNew:true,originMode:'manual'}]) {
    const deal = {id:42,...draft};
    const board = {edit:null,deals:[deal],tab:'tasks'};
    let writes=0;
    const ctx = {S:board,STAND:true,deal:id=>board.deals.find(item=>item.id===id),
      DRAFTS:{},crmDraftLive:new Map(),saveUi:()=>{},save:()=>writes++,render:()=>{},toast:()=>{}};
    vm.runInNewContext([extracted('editOpen'),extracted('editClose'),'editOpen(42);editClose();'].join('\n'),ctx);
    assert.equal(writes,draft?.originMode==='manual'?1:0,'opening and cancelling are UI-only for existing deals');
    assert.equal(board.deals.length,draft?0:1);
  }
  {
    const board = {draft:{client:'Fixture',clientId:1,inquiryType:'agent'},deals:[]};
    const snapshots = [];
    const save = () => snapshots.push(JSON.parse(JSON.stringify(board.deals[0])));
    const ctx = {S:board,draftValid:()=>true,ensureClient:()=>{},clientById:()=>({docs:false}),
      draftAmounts:()=>({amountThb:100}), log:(d,text)=>d.log.push(text), save, render:()=>{},toast:()=>{},
      newDeal: options => {
        const deal = {...options,id:42,log:['Сделка создана']};
        board.deals.push(deal);
        if(!options.noSave)save();
        return deal;
      }};
    vm.runInNewContext(extracted('createFull')+'\ncreateFull();',ctx);
    assert.equal(snapshots.length,1,'manual full creation writes the board once');
    assert.equal(snapshots[0].inquiryType,'agent');
    assert.match(snapshots[0].log[0],/Сделка внесена вручную/);
  }
  for (const otherEdited of [false,true]) {
    const deal = {id:42,inquiryType:'agent'};
    const board = {edit:42};
    let typeWrites=0, financialWrites=0, commits=0;
    const ctx = {S:board,STAND:true,pendingInquiryTypes:new Set(),deal:()=>deal,validInquiryType:()=>true,
      val:()=> 'client', standBusy:false,crmDraftActive:{id:42},crmDraftLive:new Map(),
      crmDraftHasEdits:()=>otherEdited,document:{getElementById:()=>({})},
      setDealInquiryType:async (id,value,redraw)=>{
        assert.equal(id,42);assert.equal(redraw,false);
        typeWrites++;deal.inquiryType=value;return true;
      },
      crmDraftCommit:()=>{commits++;return ['Сумма'];},
      save:()=>financialWrites++,render:()=>{},toast:()=>{}};
    await vm.runInNewContext(extracted('editSave')+'\neditSave(42);',ctx);
    assert.equal(typeWrites,1);
    assert.equal(commits,Number(otherEdited),'a type-only edit never serializes financial defaults');
    assert.equal(financialWrites,Number(otherEdited),'real financial edits still reach their normal save');
    assert.equal(board.edit,null);
    assert.equal(deal.inquiryType,'client');
  }
  for (const conflict of [false,true]) {
    const current = {id:42,inquiryType:'agent',notes:'локальное примечание'};
    const stored = {id:42,inquiryType:'agent',notes:'записанное примечание'};
    const requests = [];
    let queued=0, refreshed=0, finish;
    const pending = new Promise(resolve=>{finish=resolve;});
    const ctx = {S:{open:42},STAND:true,SCREEN:null,SNAP:null,standClosing:false,standVer:9,
      standBusy:false,standPush:false,standSaveScheduled:false,standBase:{deals:[stored]},DRAFTS:{},
      pendingInquiryTypes:new Set(),deal:()=>current,validInquiryType:()=>true,canSetInquiryType:()=>true,
      render:()=>{},toast:()=>{},standPull:async()=>{refreshed++;},standSave:()=>{queued++;},
      setTimeout:callback=>callback(),fetch:(path,params)=>{requests.push([path,params]);return pending;}};
    const result=vm.runInNewContext(extracted('setDealInquiryType')+'\nsetDealInquiryType(42,"client");',ctx);
    assert.equal(ctx.standBusy,true);
    if(!conflict)ctx.standPush=true;
    finish({status:conflict?409:200,ok:!conflict,
      json:async()=>conflict?{error:'conflict'}:{success:true,version:10}});
    assert.equal(await result,!conflict);
    assert.equal(requests[0][0],'/api/stand/deals/42/inquiry-type');
    assert.equal(requests[0][1].method,'PATCH');
    assert.deepEqual(JSON.parse(requests[0][1].body),{version:9,inquiryType:'client'});
    assert.equal(current.notes,'локальное примечание');
    assert.equal(stored.notes,'записанное примечание');
    assert.equal(current.inquiryType,conflict?'agent':'client');
    assert.equal(stored.inquiryType,current.inquiryType);
    assert.equal(ctx.standVer,conflict?9:10);
    assert.equal(queued,conflict?0:1);
    assert.equal(refreshed,conflict?1:0);
  }
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
