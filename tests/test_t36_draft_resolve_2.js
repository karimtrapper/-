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
  fetchResponses['/api/clients'] = { success: true, clients: [] };
  fetchResponses['/api/stand/channels'] = { success: true, data: { tg: [{ id: 'id6', account: 'Елизавета', name: 'Chat 6' }, { id: 'id7', account: 'Елизавета', name: 'Chat 7' }] } };

  await fetchChannels();
  await fetchCrmClients();

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
  process.exit(0);
} catch(e) {
  console.error(e);
  process.exit(1);
}
})();
`

eval(evalPrefix + jsCode + assertions);
