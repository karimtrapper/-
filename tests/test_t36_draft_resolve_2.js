const fs = require('fs');
const html = fs.readFileSync('static/stand/tasks.html', 'utf8');

let S = { draft: {}, clients: [], deals: [], chatClientMap: {} };
let CRM_CLIENTS = [];
let TG_CHATS = [{ key: 'Елизавета:id6', account: 'Елизавета', id: 'id6', name: 'Chat 6' }, { key: 'Елизавета:id7', account: 'Елизавета', id: 'id7', name: 'Chat 7' }];
let WA_CHATS = [];
let BX_DEALS = [];
let toast = () => {};
let render = () => {};
let save = () => {};
let bxRefCode = () => null;
let refByCode = () => null;
let refOfClient = () => null;
let clientsInit = () => [];
let clientById = (id) => null;
function knownBy(src, ref) { return []; }

const getChatObjStr = html.match(/function getChatObj\(.*?\n}/s)[0];
const isKnownRefStr = html.match(/function isKnownRef\(.*?\n}/s)[0];
const draftResolveStr = html.match(/function draftResolve\(\).*?\n}/s)[0];
const draftClientClearStr = html.match(/function draftClientClear\(\).*?\n}/s)[0];

eval(getChatObjStr);
eval(isKnownRefStr);
eval(draftResolveStr);
eval(draftClientClearStr);

// Scenario 1: Select Chat 6 (Unknown, strict mode)
S.draft = { source: 'tg', sourceRef: 'Елизавета:id6', clientManual: false, client: '', cq: '' };
draftResolve();
if (S.draft.client !== '') throw new Error("Expected empty client, got " + S.draft.client);
if (S.draft.cq !== 'Chat 6') throw new Error("Expected prefilled cq=Chat 6, got " + S.draft.cq);

// Scenario 2: Change mind, select Chat 7
S.draft.sourceRef = 'Елизавета:id7';
draftResolve();
if (S.draft.client !== '') throw new Error("Expected empty client, got " + S.draft.client);
if (S.draft.cq !== 'Chat 7') throw new Error("Expected prefilled cq=Chat 7, got " + S.draft.cq);

// Scenario 3: Manually type name
S.draft.clientManual = true;
S.draft.client = 'Ivan';
S.draft.sourceRef = 'Елизавета:id6';
draftResolve();
if (S.draft.client !== 'Ivan') throw new Error("Expected Ivan, got " + S.draft.client);

// Scenario 4: Change mind AGAIN after manual type - name should NOT change
S.draft.sourceRef = 'Елизавета:id7';
draftResolve();
if (S.draft.client !== 'Ivan') throw new Error("Expected Ivan, got " + S.draft.client);

// Scenario 5: User clears manual client, then resolves
draftClientClear();
if (S.draft.clientManual !== false) throw new Error("Expected clientManual false after clear");
S.draft.sourceRef = 'Елизавета:id6';
draftResolve();
if (S.draft.client !== '') throw new Error("Expected empty client after clear, got " + S.draft.client);
if (S.draft.cq !== 'Chat 6') throw new Error("Expected cq=Chat 6, got " + S.draft.cq);

console.log("All scenarios passed.");
