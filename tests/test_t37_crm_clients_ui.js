const fs = require('fs');
const html = fs.readFileSync('static/stand/tasks.html', 'utf8');

const scripts = [];
const scriptRegex = /<script.*?>([\s\S]*?)<\/script>/gi;
let match;
while ((match = scriptRegex.exec(html)) !== null) {
    scripts.push(match[1]);
}
let jsCode = scripts.join('\n');

jsCode = jsCode.replace(/window\.location\.reload\(\)/g, "undefined")
               .replace(/location\.search/g, "''")
               .replace(/localStorage\.setItem/g, "(() => {})")
               .replace(/localStorage\.getItem/g, "(() => null)")
               .replace(/document\.title/g, "dummy")
               .replace(/document\.body/g, "({ classList: { add: ()=>{} } })");

const evalPrefix = `
let fetchResponses = {};
global.fetchCalls = [];
global.fetch = async (url) => {
  fetchCalls.push(url);
  if (typeof fetchResponses[url] === 'function') return fetchResponses[url](url);
  if (fetchResponses[url]) return { ok: true, json: async () => fetchResponses[url] };
  return { ok: false };
};
global.FormData = class {};
global.alert = console.log;
global.prompt = () => null;
global.document = {
  addEventListener: () => {},
  getElementById: () => ({ innerHTML: '', style: {}, scrollIntoView: () => {}, focus: () => {}, classList: { add: ()=>{}, remove: ()=>{} }, textContent: '' })
};
global.window = { addEventListener: () => {}, setTimeout: (f) => f(), history: { replaceState: ()=>{} } };
`;

const assertions = `
(async () => {
try {
  fetchResponses['/api/clients'] = {
    success: true,
    clients: [
      { id: "100", name: "Valid CRM", total_deals: 2, telegram: "@valid" },
      { id: "bad", name: "Invalid CRM" },
      { id: "-5", name: "Negative CRM" },
      { id: null, name: "Null CRM" }
    ]
  };

  await fetchCrmClients();
  if (CRM_CLIENTS.length !== 1) throw new Error("fetchCrmClients did not filter correctly: " + CRM_CLIENTS.length);
  if (CRM_CLIENTS[0].id !== "crm:100") throw new Error("fetchCrmClients ID incorrect");

  const dealTest = {
    id: 999,
    clientId: 'crm:100',
    client: 'Valid CRM',
    manager: 'Елизавета',
    payType: 'Наличные',
    type: 'Обмен валюты',
    rates: { usdtThb: 30 }
  };
  const payload = crmPayload(dealTest);
  if (payload.client_id !== 100) throw new Error("crmPayload extracted wrong client_id: " + payload.client_id);

  const dealLocal = {
    id: 1000,
    clientId: 42,
    crmClientId: 55,
    client: 'Local Bob',
    payType: 'Наличные',
    type: 'Обмен валюты',
    rates: { usdtThb: 30 }
  };
  const payloadLocal = crmPayload(dealLocal);
  if (payloadLocal.client_id !== 55) throw new Error("crmPayload fallback failed: " + payloadLocal.client_id);

  S.draft = {
    source: 'tg',
    sourceRef: 'Елизавета:unknown123',
    clientManual: false,
    client: 'Should be cleared',
    clientId: 999
  };

  TG_CHATS = [{ key: 'Елизавета:unknown123', id: 'unknown123', account: 'Елизавета', name: 'Unknown Chat Name' }];
  draftResolve();

  if (S.draft.client !== '') throw new Error("draftResolve did not clear D.client for unknown chat");
  if (S.draft.clientId !== null) throw new Error("draftResolve did not clear D.clientId for unknown chat");
  if (S.draft.cq !== 'Unknown Chat Name') throw new Error("draftResolve did not set D.cq correctly");

  S.chatClientMap = {};
  S.draft = { source: 'tg', sourceRef: 'Елизавета:persisted', clientManual: false, client: '', cq: '' };
  draftClientPick('crm:100');

  const snapshot = standSnapshot();
  if (!snapshot.chatClientMap || snapshot.chatClientMap['tg:Елизавета:persisted'] !== 'crm:100') {
      throw new Error("standSnapshot did not include chatClientMap");
  }

  S.chatClientMap = {};
  standApply(snapshot);

  if (!S.chatClientMap || S.chatClientMap['tg:Елизавета:persisted'] !== 'crm:100') {
      throw new Error("standApply did not restore chatClientMap");
  }

  S.draft = { source: 'tg', sourceRef: 'Елизавета:persisted', clientManual: false, client: '', cq: '' };
  draftResolve();

  if (S.draft.client !== 'Valid CRM' || S.draft.clientId !== 'crm:100') {
      throw new Error("draftResolve did not return the expected CRM client after reload");
  }

  // Test 11: crmClientsError sets flag and does not crash
  fetchResponses['/api/clients'] = null; // simulate 500 error
  await fetchCrmClients();
  if (!crmClientsError) {
      throw new Error("crmClientsError was not set on fetch failure");
  }

  S.draft = { source: 'tg', sourceRef: 'Елизавета:unknown', cq: 'test', clientManual: false, client: '', clientId: null, pickOther: true };
  const htmlOutput = viewCreateBody(S.draft, '');
  if (!htmlOutput.includes('База клиентов CalcCRM недоступна, повторите позже')) {
      throw new Error("UI did not render the API error message");
  }

  // Test 12: XSS test for draftTakeChat
  S.draft = { source: 'tg', sourceRef: 'chat&"', clientManual: true, client: 'Malicious <script>', clientId: 99 };
  S.clients.push({ id: 99, name: 'Malicious <script>', tg: 'malicious&"tg', docs: false });
  const srcAfter = srcAfterClient(S.draft);
  if (!srcAfter.includes('<b>malicious&amp;&quot;tg</b>')) {
      throw new Error("XSS escaping failed in srcAfterClient for tg text: " + srcAfter);
  }
  if (!srcAfter.includes('Malicious &lt;script&gt;')) {
      throw new Error("XSS escaping failed in srcAfterClient for who text: " + srcAfter);
  }


  // Test 13: Fallback search UI
  CRM_CLIENTS = [{ id: 'crm:1', name: 'CRM Bob', tg: '', phone: '', docs: false, isCrm: true, totalDeals: 5 }];
  S.draft = { source: 'none', cq: 'CRM Bob', searchCrm: false };
  const foundLocalOnly = clientFind(S.draft.cq, S.draft.searchCrm);
  if (foundLocalOnly.some(x => x.id === 'crm:1')) {
      throw new Error("clientFind returned CRM client without searchCrm=true");
  }

  S.draft.searchCrm = true;

const foundWithCrm = clientFind(S.draft.cq, S.draft.searchCrm);
  if (!foundWithCrm.some(x => x.id === 'crm:1')) {
      throw new Error("clientFind failed to return CRM client with searchCrm=true");
  }
  console.log("Fallback search UI test passed.");


  // Test 14: searchCrm persists on input
  S.draft.searchCrm = true;
  draftSet('cq', 'new query', true);
  if (S.draft.searchCrm !== true) {
      throw new Error("searchCrm was reset on input");
  }

  // Changing source resets it
  draftSet('source', 'bitrix', true);
  if (S.draft.searchCrm !== false) {
      throw new Error("searchCrm was NOT reset on source change");
  }
  console.log("Search persistence UI test passed.");


  // Test 15: viewCreate() UX after selecting an unknown chat
  S.draft = { source: 'tg', sourceRef: 'Елизавета:unknown123', clientManual: false, client: '', cq: 'Unknown Chat Name', srcEdit: false, pickOther: false };
  S.clients = [];
  CRM_CLIENTS = [];
  TG_CHATS = [{ key: 'Елизавета:unknown123', id: 'unknown123', account: 'Елизавета', name: 'Unknown Chat Name' }];

  const viewHtml = viewCreate();
  if (viewHtml.includes('Показать все — ещё')) {
      throw new Error("viewCreate did not collapse the chat list for unknown chat");
  }
  if (!viewHtml.includes('клиента выберите ниже')) {
      throw new Error("viewCreate summary did not show 'клиента выберите ниже'");
  }
  if (!viewHtml.includes('Создать нового клиента «Unknown Chat Name»')) {
      throw new Error("viewCreateBody did not show client creation UI for unknown chat");
  }

  // Test 16: Regression on manual warning after client change
  S.draft.clientManual = true;
  S.draft.client = 'Ivan';
  S.draft.sourceRef = 'Елизавета:unknown123';
  const warnHtml = viewCreate();
  if (!warnHtml.includes('Клиент выбран вручную, а чат остался прежний')) {
      throw new Error("Warning for manual client and chat was not shown or not collapsed appropriately");
  }
  if (warnHtml.includes('Начните вводить имя или номер') || warnHtml.includes('Показать все')) {
      throw new Error("Manual client warning expanded the chat picker");
  }

  // Test 17: five recent chats by default, sixth chat reachable by search
  TG_CHATS = Array.from({ length: 8 }, (_, i) => ({
      key: 'Елизавета:chat' + (i + 1), id: 'chat' + (i + 1), account: 'Елизавета',
      name: 'Chat ' + (i + 1), last_active: 2000000000 - i
  }));
  S.draft = { source: 'tg', sourceRef: '', clientManual: false, client: '', cq: '', q: '' };
  let pickerHtml = viewCreate();
  if (!pickerHtml.includes('Chat 5') || pickerHtml.includes('Chat 6')) {
      throw new Error("Default chat picker did not show exactly the first five chats");
  }
  S.draft.q = 'Chat 6';
  pickerHtml = viewCreate();
  if (!pickerHtml.includes('Chat 6') || pickerHtml.includes('Chat 1')) {
      throw new Error("Chat search did not find the sixth chat exclusively");
  }
  draftSet('sourceRef', 'Елизавета:chat6', true);
  pickerHtml = viewCreate();
  if (!pickerHtml.includes('ОТКУДА КЛИЕНТ') || pickerHtml.includes('id="q"')) {
      throw new Error("Selecting a searched chat did not collapse the picker");
  }

  // Fake state-save response separates operator delivery from the admin copy.
  const previousRender=render, previousTyping=standTyping;
  render=()=>{};standTyping=()=>false;
  S.deals=[{id:777,step:'s8',closed:false}];
  S.notes=[];
  S.modal={id:777,step:'s11',to:'operator',noteId:'fake-note-operator',delivery:'pending'};
  standBusy=false;standPush=false;standSaveScheduled=false;standClosing=false;
  fetchResponses['/api/stand/state']={success:true,version:501,data:standSnapshot(),
    notification_delivery:[
      {note_id:'fake-note-operator',role:'admin',status:'sent'},
      {note_id:'fake-note-operator',role:'operator',status:'suppressed'}
    ]};
  await standSave();
  if(S.modal.delivery!=='suppressed'||S.modal.adminDelivery!=='sent')
    throw new Error('Save response mixed operator delivery with the admin copy');
  const operatorSuppressedText=notificationDeliveryText(S.modal);
  if(operatorSuppressedText!=='Задача сохранена. Уведомление получил администратор; Настя увидит задачу в задачнике.')
    throw new Error('Admin copy success was not explained honestly in the handoff status');
  if(!notificationDeliveryText({to:'operator',delivery:'suppressed',adminDelivery:'failed'}).includes('не подтвердил отправку администраторской копии'))
    throw new Error('Admin failure was omitted from the UI status');
  if(!notificationDeliveryText({to:'operator',delivery:'suppressed',adminDelivery:'suppressed'}).includes('не отправлял уведомления'))
    throw new Error('Suppressed admin copy was omitted from the UI status');
  const previousTgLines=tgLines, previousStepTitle=stepTitle, previousRoleSwitch=canSwitchRole;
  const previousNow=now, previousPayBlock=tgPayBlock;
  tgLines=()=>[];stepTitle=()=>'';canSwitchRole=()=>false;now=()=>'';tgPayBlock=()=>'';
  const modalHtml=viewModal();
  if(!modalHtml.includes(operatorSuppressedText))
    throw new Error('Modal did not show the aggregated admin/operator delivery status');
  if(!modalHtml.includes('class="t">Задача сохранена</div>'))
    throw new Error('Saved handoff still looks like a preview');
  if(modalHtml.split(operatorSuppressedText).length-1!==1)
    throw new Error('Delivery status is duplicated in the modal');
  if(!modalHtml.includes('Ответственный:'))
    throw new Error('Modal footer lost the task owner');
  tgLines=previousTgLines;stepTitle=previousStepTitle;canSwitchRole=previousRoleSwitch;
  now=previousNow;tgPayBlock=previousPayBlock;

  const previousFns={render,saveNote,go,val,docParse,toast};
  const handoffToasts=[];
  render=()=>{};saveNote=()=>{};val=()=>'';docParse=()=>{};
  toast=message=>handoffToasts.push(message);
  const makeHandoffDeal=()=>({id:778,code:'SYNTH-778',step:'s8',isOld:false,
    type:'Оплата недвижимости',kind:'Фрихолд',payType:'Крипта',docs:{},docMeta:{},files:{},
    _managerDraft:{docs:{pass:true,inv:true},docMeta:{pass:{file:'p.pdf'},inv:{file:'i.pdf'}},
      files:{pass:[{file:'p.pdf',mime:'application/pdf',bytes:8,data:'data:application/pdf;base64,JVBERi0xLjQK'}],
        inv:[{file:'i.pdf',mime:'application/pdf',bytes:8,data:'data:application/pdf;base64,JVBERi0xLjQK'}]}}});
  const runFailedHandoff=async response=>{
    const handoffDeal=makeHandoffDeal();
    S.role='manager';S.deals=[handoffDeal];S.notes=[{id:'confirmed-note'}];S.modal=null;
    standBase=standClone({deals:[handoffDeal],notes:standClone(S.notes)});
    standVer=30;standBusy=false;standPush=false;standSaveScheduled=false;standClosing=false;
    standLastSaveResult={ok:true};
    fetchResponses['/api/stand/state']=response;
    go=(d,next)=>{d.step=next;S.notes.unshift({id:'pending-handoff-note',role:'operator',dealId:d.id});
      S.modal={id:d.id,step:next,to:'operator',noteId:'pending-handoff-note',delivery:'pending'};save();};
    await act(778,'s8');
    const restored=deal(778);
    if(!restored||restored.step!=='s8')throw new Error('Failed s8 handoff left the local deal on the operator step');
    if(filesOf(restored,'pass').length!==1||filesOf(restored,'inv').length!==1)
      throw new Error('Failed handoff discarded confirmed manager draft files');
    if(S.modal!==null||notificationDeliveryText(S.modal)!=='')
      throw new Error('Failed handoff left a delivery modal claiming it was sent');
    if(!handoffToasts.some(x=>x.includes('файлы остались на шаге документов')))
      throw new Error('Failed handoff did not explain that files remain on s8');
    return restored;
  };
  const statePutCount=()=>fetchCalls.filter(url=>url==='/api/stand/state').length;
  let beforeHandoffPuts=statePutCount();
  await runFailedHandoff({success:false,error:'synthetic rejection'});
  if(statePutCount()-beforeHandoffPuts!==1)throw new Error('Rejected handoff issued a duplicate PUT');
  const retryData=standClone(standBase);
  const retryDeal=retryData.deals.find(x=>x.id===778);
  retryDeal.files=retryDeal._managerDraft.files;retryDeal.docs=retryDeal._managerDraft.docs;
  retryDeal.docMeta=retryDeal._managerDraft.docMeta;delete retryDeal._managerDraft.files;
  delete retryDeal._managerDraft.docs;delete retryDeal._managerDraft.docMeta;retryDeal.step='s11';
  retryData.notes.unshift({id:'pending-handoff-note',role:'operator',dealId:778});
  fetchResponses['/api/stand/state']={success:true,version:31,data:retryData,notification_delivery:[
    {note_id:'pending-handoff-note',role:'operator',status:'sent'}]};
  await act(778,'s8');
  if(deal(778).step!=='s11')throw new Error('Successful retry could not hand the task to the operator');
  if(statePutCount()-beforeHandoffPuts!==2)throw new Error('Successful retry sent an unexpected number of PUTs');
  beforeHandoffPuts=statePutCount();
  await runFailedHandoff(async()=>Promise.reject(new Error('synthetic network timeout')));
  if(statePutCount()-beforeHandoffPuts!==1)throw new Error('Timed out handoff issued a duplicate PUT');

  // A request still in flight at the wait timeout must not trigger another PUT;
  // if the original later succeeds, standSave must apply and render that response.
  const originalWaitSaved=standWaitSaved;
  let pendingWaits=0,resolvePendingPut=null,pendingSavedData=null,lastRenderedStep=null;
  const pendingDeal=makeHandoffDeal();
  S.role='manager';S.deals=[pendingDeal];S.notes=[{id:'confirmed-note'}];S.modal=null;
  standBase=standClone({deals:[pendingDeal],notes:standClone(S.notes)});
  standVer=40;standBusy=false;standPush=false;standSaveScheduled=false;standClosing=false;
  standLastSaveResult={ok:true};
  render=()=>{lastRenderedStep=deal(778)?.step||null;};
  go=(d,next)=>{d.step=next;S.notes.unshift({id:'pending-late-note',role:'operator',dealId:d.id});
    S.modal={id:d.id,step:next,to:'operator',noteId:'pending-late-note',delivery:'pending'};
    pendingSavedData=standClone(standSnapshot());save();};
  fetchResponses['/api/stand/state']=()=>new Promise(resolve=>{resolvePendingPut=resolve;});
  standWaitSaved=async()=>{
    pendingWaits++;
    if(pendingWaits===1)return {ok:true};
    throw new Error('synthetic wait timeout');
  };
  beforeHandoffPuts=statePutCount();
  await act(778,'s8');
  if(deal(778).step!=='s8'||S.modal!==null)throw new Error('Pending timeout did not roll back the local handoff');
  if(statePutCount()-beforeHandoffPuts!==1)throw new Error('Timeout rollback issued another PUT');
  standWaitSaved=originalWaitSaved;
  resolvePendingPut({ok:true,json:async()=>({success:true,version:41,data:pendingSavedData,
    notification_delivery:[{note_id:'pending-late-note',role:'operator',status:'sent'}]})});
  await originalWaitSaved();
  if(deal(778).step!=='s11'||lastRenderedStep!=='s11')
    throw new Error('Late success response was not applied and rendered: step='+deal(778).step+', rendered='+lastRenderedStep+', save='+JSON.stringify(standLastSaveResult));
  if(statePutCount()-beforeHandoffPuts!==1)throw new Error('Late response caused a duplicate PUT');
  render=previousFns.render;saveNote=previousFns.saveNote;go=previousFns.go;
  val=previousFns.val;docParse=previousFns.docParse;toast=previousFns.toast;
  render=previousRender;standTyping=previousTyping;

  // Keep the mandatory passport rule for new real estate deals.
  if (!jsCode.includes("if(!d.isOld&&!filesOf(d,'pass').length){toast('Нужен паспорт');return;}")) {
      throw new Error("Mandatory passport validation for a new deal is missing");
  }

  console.log("All real function tests passed.");
  process.exit(0);
} catch(e) {
  console.error(e);
  process.exit(1);
}
})();
`

eval(evalPrefix + jsCode + assertions);
