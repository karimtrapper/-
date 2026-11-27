// QA перепроверка T7, FAIL №6–7: после перехода ручных агентов задачника на id
// вида 'm:<n>' (см. tests/test_stand_referrer_id.js) голый Number(v)/parseInt(v)
// на выбор такого агента в черновике/сделке превращал refId в NaN, а голая
// интерполяция ${r.id} в onclick="refEdit(${r.id})" без кавычек рождала
// SyntaxError в атрибуте (onclick="refEdit(m:1)" не парсится). Единая точка
// нормализации на чтение — refIdNorm(); единая точка вставки в onclick —
// refIdLit() (число как есть, строка — в кавычках, апостроф экранирован).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../static/stand/tasks.html'), 'utf8');
function fn(name) {
  const m = html.match(new RegExp(`(?:^|\\n)((?:async )?function ${name}\\()`));
  assert.ok(m, `нет функции ${name}`);
  const start = m.index + m[0].indexOf(m[1]);
  let i = html.indexOf('{', start), depth = 0, q = '', esc = false;
  for (; i < html.length; i++) {
    const c = html[i];
    if (q) { if (esc) { esc = false; continue; } if (c === '\\') { esc = true; continue; } if (c === q) q = ''; continue; }
    if (c === '\'' || c === '"' || c === '`') { q = c; continue; }
    if (c === '{') depth++;
    if (c === '}' && --depth === 0) return html.slice(start, i + 1);
  }
  throw new Error(`не нашли конец функции ${name}`);
}
function run(names, context) {
  vm.createContext(context);
  vm.runInContext(names.map(fn).join('\n'), context);
  return context;
}

// ---------- выбор агента в черновике и в открытой сделке ----------
{
  const manual = {id: 'm:1', name: 'Свой агент', code: 'GR-M001', comp: 'revshare', percent: 15, active: true};
  const numeric = {id: 501, name: 'Ромка', code: 'GR-ROMAN', comp: 'revshare', percent: 20, active: true};
  const d = {id: 3, agents: [{refId: null, name: '', tier: 1}]};
  const S = {refs: [manual, numeric], draft: {agents: [{refId: null, name: '', tier: 1}]}, deals: [d]};
  const ctx = run(['refs', 'refById', 'refIdNorm', 'dAgentSet', 'agentSet'], {
    S, refsInit: () => [], deal: () => d, syncRef: () => {}, save: () => {}, render: () => {},
  });

  ctx.dAgentSet(0, 'refId', 'm:1');
  assert.equal(S.draft.agents[0].refId, 'm:1', 'выбор ручного агента в черновике — refId не NaN');
  assert.equal(S.draft.agents[0].name, 'Свой агент');
  assert.ok(!Number.isNaN(S.draft.agents[0].refId));

  ctx.dAgentSet(0, 'refId', '501');
  assert.equal(S.draft.agents[0].refId, 501, 'выбор агента из базы в черновике — id остаётся числом');
  assert.equal(S.draft.agents[0].name, 'Ромка');

  ctx.agentSet('card', 3, 0, 'refId', 'm:1');
  assert.equal(d.agents[0].refId, 'm:1', 'выбор ручного агента в открытой сделке — refId не NaN');
  assert.equal(d.agents[0].name, 'Свой агент');

  ctx.agentSet('card', 3, 0, 'refId', '501');
  assert.equal(d.agents[0].refId, 501, 'выбор агента из базы в сделке — id остаётся числом');

  console.log('dAgentSet/agentSet: ручной и базовый агент — 6 проверок PASS');
}

// ---------- создание сделки (agentsDefault через refIdNorm) ----------
{
  const manual = {id: 'm:2', name: 'Ручной при создании', code: 'GR-M002', comp: 'revshare', percent: 10, parentId: null, l2: 10};
  const S = {refs: [manual]};
  const ctx = run(['refs', 'refById', 'refIdNorm', 'agentsDefault'], {S, refsInit: () => []});
  const D = {};
  // Тот же путь, что draftSourceSet использует при выборе агента на шаге создания сделки.
  const v = 'm:2';
  D.agents = ctx.agentsDefault(ctx.refIdNorm(v));
  assert.equal(D.agents.length, 1);
  assert.equal(D.agents[0].refId, 'm:2', 'создание сделки с ручным агентом — refId не NaN');
  console.log('agentsDefault при создании сделки: 2 проверки PASS');
}

// ---------- выбор ручного родителя (второй уровень) в форме реферера ----------
{
  const manual = {id: 'm:1', name: 'Свой агент', code: 'GR-M001', comp: 'revshare', percent: 15, active: true, parentId: null, l2: 10};
  const parent = {id: 'm:2', name: 'Родитель', code: 'GR-M002', active: true};
  const S = {refs: [manual, parent], refEdit: 'm:1'};
  const fields = {rf_name: 'Свой агент', rf_code: 'GR-M001', rf_tg: '', rf_comp: 'revshare',
    rf_pct: '15', rf_cur: 'USDT', rf_parent: 'm:2', rf_l2: '10', rf_lang: 'ru', rf_active: '1'};
  const ctx = run(['refs', 'refById', 'refIdNorm', 'refEditSave'], {
    S, refsInit: () => [], val: id => fields[id], toast: () => {}, save: () => {}, render: () => {},
  });
  ctx.refEditSave();
  assert.equal(manual.parentId, 'm:2', 'выбор ручного родителя — parentId не NaN');
  console.log('refEditSave: ручной родитель — 1 проверка PASS');
}

// ---------- onclick-обработчики карточки реферера компилируются как JS ----------
{
  const source = html;
  const m = source.match(/onclick="refEdit\(\$\{refIdLit\(r\.id\)\}\)"/);
  assert.ok(m, 'refEdit в карточке должен идти через refIdLit(r.id)');
  for (const name of ['refDeals', 'refToggle', 'refPay']) {
    assert.ok(new RegExp(`onclick="${name}\\(\\$\\{refIdLit\\(r\\.id\\)\\}\\)"`).test(source),
      `${name} в карточке должен идти через refIdLit(r.id)`);
  }

  const litCtx = run(['refIdLit'], {});
  for (const [id, expected] of [[501, '501'], ['m:1', "'m:1'"], ["m:o'brien", "'m:o\\'brien'"]]) {
    assert.equal(litCtx.refIdLit(id), expected);
    assert.doesNotThrow(() => new Function(`refEdit(${litCtx.refIdLit(id)})`),
      `refEdit(${litCtx.refIdLit(id)}) должен компилироваться как валидный JS`);
  }
  console.log('refIdLit: карточка реферера — 5 проверок PASS');
}
