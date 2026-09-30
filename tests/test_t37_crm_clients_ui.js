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
function deal(id) { return S.deals.find(x=>x.id===id); }
function htmlText(s) { return s; }
const PAYIN_CRM = {};
function num(v) { return Number(v)||0; }
function crmNet() { return 'TRC20'; }

// Evaluate necessary parts
const evals = [
  "clients", "clientById", "clientFind", "draftResolve", 
  "draftClientPick", "draftClientClear", "ensureClient", "draftClientNew",
  "editClientFromChat", "editClientNew", "editClientPick"
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
S.clients = [{ id: 1, name: 'Local Bob', tg: '', docs: false }];
CRM_CLIENTS = [{ id: 'crm:1', name: 'CRM Bob', tg: '', phone: '', docs: false, isCrm: true, totalDeals: 5 }];

// Find the onclick handler generated in the HTML string for draftClientPick
const draftHtmlMatch = html.match(/onclick="draftClientPick\([^"]+\)"/g);
if (!draftHtmlMatch) throw new Error("No draftClientPick onclick found");
// Find the exact argument pattern. The code has `<div class="li" onclick="draftClientPick('${c.id}')">`
// We will manually execute what the browser would execute
let executed_local = false;
let executed_crm = false;

// Simulate clicking for local client id=1
S.draft = { source: 'tg', sourceRef: 'Елизавета:id6', cq: 'Bob' };
eval(`draftClientPick('1')`);
if (S.draft.client === 'Local Bob' && S.draft.clientId === 1) executed_local = true;

// Simulate clicking for CRM client crm:1
S.draft = { source: 'tg', sourceRef: 'Елизавета:id6', cq: 'Bob' };
eval(`draftClientPick('crm:1')`);
if (S.draft.client === 'CRM Bob' && S.draft.clientId === 'crm:1') executed_crm = true;

if (!executed_local || !executed_crm) throw new Error("Inline handlers simulation failed for draftClientPick");

// Do the same for editClientPick
S.deals = [{ id: 10, clientId: null, client: '', clientQ: 'Bob', clientPinned: false }];
eval(`editClientPick(10, '1')`);
if (S.deals[0].client !== 'Local Bob' || S.deals[0].clientId !== 1) throw new Error("editClientPick failed for local");

eval(`editClientPick(10, 'crm:1')`);
if (S.deals[0].client !== 'CRM Bob' || S.deals[0].clientId !== 'crm:1') throw new Error("editClientPick failed for CRM");

console.log("All UI tests passed.");
} catch (e) {
  console.error(e);
  process.exit(1);
}
