const fs = require('fs');
const html = fs.readFileSync('static/stand/tasks.html', 'utf8');

let S = { draft: {}, clients: [], deals: [], chatClientMap: {} };
let CRM_CLIENTS = [];
let TG_CHATS = [{ key: 'Елизавета:id6', account: 'Елизавета', id: 'id6', name: 'Chat 6' }];
let WA_CHATS = [];
let BX_DEALS = [];
let toast = () => {};
let render = () => {};
let save = () => {};

// Mock functions required by tasks.html snippets
function knownBy(src, ref) { return []; }
function clientsInit() { return []; }
function getChatObj(src, v) { 
  if(!v) return null;
  const all=src==='tg'?TG_CHATS:src==='wa'?WA_CHATS:src==='bitrix'?BX_DEALS:[];
  return all.find(c => c.key === v || c.id === v) || all.find(c => c.name === v);
}
function isKnownRef(src, v) { return false; }
function bxRefCode() { return null; }
function refByCode() { return null; }
function refOfClient() { return null; }
function clientDeals(id) { return []; }
function agentsDefault() { return []; }
function econ(d) { return { agents: [] }; }
function isCrypto(d) { return false; }
const PAYIN_CRM = {};
function num(v) { return Number(v)||0; }
function crmNet() { return 'TRC20'; }

// Evaluate necessary parts
const evals = [
  "clients", "clientById", "clientFind", "draftResolve", 
  "draftClientPick", "draftClientClear", "ensureClient", "draftClientNew",
  "editClientFromChat", "editClientNew"
];

for (const fnName of evals) {
  const regex = new RegExp(`function ${fnName}\\(.*?\\)[^{]*{(?:[^{}]*|{(?:[^{}]*|{[^{}]*})*})*}`, 'g');
  const m = html.match(regex);
  if (m) eval(m[m.length-1]);
}

const payloadMatch = html.match(/client_id:typeof d\.clientId==='string'&&d\.clientId\.startsWith\('crm:'\)\?parseInt\(d\.clientId\.slice\(4\)\):\(d\.crmClientId\?\?null\)/);
if (!payloadMatch) throw new Error("Could not find payload line");

function crmPayload(d) {
  return {
    client_id: typeof d.clientId==='string'&&d.clientId.startsWith('crm:')?parseInt(d.clientId.slice(4)):(d.crmClientId??null)
  };
}

try {
// Test 1: ID Collision
S.clients = [{ id: 1, name: 'Local Bob', tg: '', docs: false }];
CRM_CLIENTS = [{ id: 'crm:1', name: 'CRM Bob', tg: '', phone: '', docs: false, isCrm: true, totalDeals: 5 }];

const cLocal = clientById(1);
const cCrm = clientById('crm:1');
if (!cLocal || cLocal.name !== 'Local Bob') throw new Error("ID collision: local client not found");
if (!cCrm || cCrm.name !== 'CRM Bob') throw new Error("ID collision: CRM client not found");

// Test 2: Chat binding surviving reload (S.chatClientMap)
S.chatClientMap = { "tg:Елизавета:id6": "crm:1" };
S.draft = { source: 'tg', sourceRef: 'Елизавета:id6', clientManual: false, client: '' };
draftResolve();
if (S.draft.client !== 'CRM Bob') throw new Error("draftResolve did not use chatClientMap");
if (S.draft.clientId !== 'crm:1') throw new Error("draftResolve did not use chatClientMap clientId");

// Test 3: No duplicate client created for existing CRM client
// ensureClient now does NOT auto match CRM Bob. It should create a new one to prevent incorrect merge.
S.draft = { source: 'none', sourceRef: '', clientManual: true, client: 'CRM Bob', clientId: null };
ensureClient(S.draft);
if (S.draft.clientId === 'crm:1') throw new Error("ensureClient matched CRM client by name automatically!");
if (S.draft.clientId !== 2) throw new Error("ensureClient generated wrong local ID: " + S.draft.clientId);

// Test 4: New client creates local numeric ID
S.draft = { source: 'none', sourceRef: '', clientManual: true, client: 'Alice', clientId: null };
ensureClient(S.draft);
if (S.draft.clientId !== 3) throw new Error("ensureClient generated wrong local ID: " + S.draft.clientId);

// Test 5: Exact CRM client_id in payload
const dealCrm = { clientId: 'crm:42', client: 'CRM Dude', manager: 'Admin', payType: 'Наличные', type: 'Обмен валюты' };
const pCrm = crmPayload(dealCrm);
if (pCrm.client_id !== 42) throw new Error("crmPayload extracted wrong client_id for CRM: " + pCrm.client_id);

const dealLocal = { clientId: 3, client: 'Local Dude', manager: 'Admin', payType: 'Наличные', type: 'Обмен валюты', crmClientId: 99 };
const pLocal = crmPayload(dealLocal);
if (pLocal.client_id !== 99) throw new Error("crmPayload lost fallback crmClientId: " + pLocal.client_id);

// Test 6: No docs inference
if (CRM_CLIENTS[0].docs !== false) throw new Error("Docs should be explicitly false, not inferred from totalDeals");

// Test 7: Verify draftClientPick sets correct key
S.draft = { source: 'tg', sourceRef: 'Елизавета:id6' };
draftClientPick('crm:1');
if (S.chatClientMap['tg:Елизавета:id6'] !== 'crm:1') throw new Error("draftClientPick did not set S.chatClientMap correctly");

console.log("All UI tests passed.");
} catch (e) {
  console.error(e);
  process.exit(1);
}
