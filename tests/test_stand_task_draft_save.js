const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {webcrypto:crypto} = require('node:crypto');

const html = fs.readFileSync('static/stand/tasks.html', 'utf8');

function extracted(name) {
  const oneLine = html.match(new RegExp('^(?:async )?function '+name+'\\([^\\n]*\\)\\{[^\\n]*\\}$', 'm'));
  if (oneLine) return oneLine[0];
  const result = html.match(new RegExp('^(?:async )?function '+name+'\\([^]*?^}', 'm'));
  assert.ok(result, 'missing '+name);
  return result[0];
}

function setup(savedResult, pull = () => {}) {
  const draft = {clientId: 1, client: 'Synthetic Auto', type: 'Оплата авто',
    kind: 'Фрихолд', payType: 'По реквизитам', cur: 'fhusd',
    invoiceCurrency: 'usd', sum: '45000', note: 'Synthetic note'};
  const S = {draft, deals: [], open: null, view: 'draft'};
  const notices = [];
  let creates = 0, resolves;
  const pending = new Promise(resolve => { resolves = resolve; });
  const ctx = {S, STAND: true, crypto, standBase: {deals: []},
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
    standPull: async () => pull(ctx),
  };
  vm.createContext(ctx);
  vm.runInContext(['standCreateKey','standCreatedDeal','standConfirmCreation',
    'createTask','createGo','createSelf'].map(extracted).join('\n'), ctx);
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
    const board = {draft:{client:'Fixture',clientId:1,inquiryType:'agent'},deals:[],tab:'tasks'};
    let writes=0;
    const ctx = {S:board,STAND:true,crypto,standBase:{deals:[]},standBusy:false,standPush:false,
      standSaveScheduled:false,draftValid:()=>true,ensureClient:()=>{},clientById:()=>({docs:false}),
      deal:id=>board.deals.find(d=>d.id===id),DRAFTS:{},crmDraftLive:new Map(),
      draftAmounts:()=>({amountThb:100}), save:()=>writes++,saveUi:()=>{},render:()=>{},toast:()=>{},
      STAND_SHARED:['deals'],
      newDeal: options => {
        const deal = {...options,id:42,log:['Сделка создана']};
        board.deals.push(deal);
        if(!options.noSave)writes++;
        return deal;
      }};
    vm.createContext(ctx);
    vm.runInContext(['standCreateKey','standCreatedDeal','standSnapshot','createFull','editClose']
      .map(extracted).join('\n'),ctx);
    await ctx.createFull();
    assert.equal(writes,0,'opening the full form never writes an incomplete deal');
    assert.equal(board.deals[0].inquiryType,'agent');
    assert.equal(board.deals[0].manualNew,true);
    assert.equal(ctx.standSnapshot().deals.length,0,'background snapshots exclude unsaved manual deals');
    ctx.editClose();
    assert.equal(board.deals.length,0);
    assert.equal(writes,0,'cancel never writes the unsaved deal');
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
    const colleague = {...t.S.deals[0], creationKey: 'colleague', client: 'Colleague Auto'};
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
    const concurrent = {...t.S.deals[0], id: 3402, creationKey: 'colleague'};
    t.resolve([concurrent, ours]);
    await saving;
    assert.equal(t.S.open, 3403, 'concurrent same-client auto gets original ID; ours is remapped');
  }
  {
    const t = setup({ok:false,error:'network'},ctx=>{
      ctx.standBase = {deals:[{...ctx.S.deals[0],id:3403}]};
    });
    const saving=t.ctx.createSelf();
    const duplicate=t.ctx.createSelf();
    assert.equal(t.creates(),1,'self-rate rejects another click while pending');
    t.resolve();
    await Promise.all([saving,duplicate]);
    assert.equal(t.S.draft,null,'the successful committed deal survives a lost PUT response');
    assert.equal(t.S.open,3403);
    assert.equal(t.S.view,'task');
  }
  {
    const t = setup({ok:false,error:'network'});
    const saving=t.ctx.createGo();
    const first={...t.S.deals[0]};
    t.resolve();
    await saving;
    t.ctx.standBase={deals:[{...first,id:3403}]};
    await t.ctx.createGo();
    assert.equal(t.creates(),1,'retry reopens the previously accepted deal');
    assert.equal(t.S.open,3403);
  }
  {
    const d={id:42,code:'СД-42',type:'Обмен валюты',client:'Synthetic Manual',
      manualNew:true,creationKey:'c'.repeat(32),log:[{text:'Draft journal'}]};
    const S={edit:42,deals:[d],seq:42};
    const notices=[],writes=[];
    let finish;
    const ctx={S,crypto,standBase:{deals:[]},document:{getElementById:()=>null},
      crmDraftLive:new Map([[42,{values:{'payin_amount_rub':'35000'}}]]),
      crmDraftActive:null,render:()=>{},toast:text=>notices.push(text),
      log:(deal,text)=>deal.log.push({text}),deal:id=>S.deals.find(row=>row.id===id),
      save:()=>writes.push(structuredClone(d)),standWaitSaved:()=>new Promise(r=>{finish=r;}),
      standSaveError:result=>result.error,
      standPull:async()=>{}};
    vm.createContext(ctx);
    vm.runInContext(['standCreateKey','standCreatedDeal','standConfirmCreation','standSaveManualCreation']
      .map(extracted).join('\n'),ctx);
    const saving=ctx.standSaveManualCreation(d);
    assert.equal(S.edit,42);
    assert.equal(notices.length,0,'manual form reports no optimistic success');
    assert.equal(writes[0].manualNew,false,'the explicit save submits the completed manual form');
    const other={id:42,code:'СД-42',client:'Different deal'};
    ctx.standBase.deals=S.deals=[other];
    finish({error:'server rejection'});
    await saving;
    assert.equal(S.manualCreateError,'server rejection');
    assert.equal(S.edit,43,'failed creation preserves the local editor without taking the other deal number');
    assert.equal(d.manualNew,true);
    assert.equal(d.log.length,1,'a failed save does not repeat the creation journal');
    assert.equal(ctx.crmDraftLive.get(43).values.payin_amount_rub,'35000');
    const retry=ctx.standSaveManualCreation(d);
    assert.equal(writes[1].creationKey,writes[0].creationKey);
    ctx.standBase.deals=S.deals=[other,{...d,id:44,code:'СД-44'}];
    finish({ok:true});
    await retry;
    assert.equal(S.edit,null);
    assert.equal(S.open,44);
    assert.deepEqual(notices,['Сделка создана: СД-44']);
  }
  console.log('auto task createGo confirmation and rejection: PASS');
})().catch(error => { console.error(error); process.exitCode = 1; });
