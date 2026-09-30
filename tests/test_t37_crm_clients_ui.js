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
global.fetch = async (url) => {
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
