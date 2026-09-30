// Аудитор (28.09, п.4) + QA перепроверка (FAIL №7): /api/stand/prod-agents выключен
// T1 (403 stand_blocked) — справочник агентов стенда переведён на GET /api/referrers
// (локальная таблица, после заливки прод-копии там будут те же рефереры). Ручные
// агенты задачника («own», записи в базе нет) получили отдельное пространство id
// ('m:<n>') — раньше оба вида делили простые числовые id, и после refsSync() чужой
// прод-агент мог получить тот же id, что и ручной: сделка слала бы referrer_id
// чужого человека под именем своего агента. crmPayload дополнительно проверяет,
// что имя агента в сделке совпадает с именем найденной записи, прежде чем слать id.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../static/stand/tasks.html'), 'utf8');
// Извлекаем функцию по балансу скобок — обычный regex до "^}" ломается на
// однострочных функциях вида function refs(){...}: закрывающая скобка не в
// начале строки, поиск уезжает далеко вниз по файлу и хватает лишний код.
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
  const source = names.map(fn).join('\n');
  vm.createContext(context);
  vm.runInContext(source, context);
  return context;
}

// ---------- refAdd: ручные агенты получают id 'm:<n>', не число ----------
{
  const S = {refs: []};
  const ctx = run(['refAdd', 'refs'], {S, refsInit: () => [], save: () => {}});
  const a = ctx.refAdd({name: 'Первый ручной'});
  const b = ctx.refAdd({name: 'Второй ручной'});
  assert.equal(a.id, 'm:1');
  assert.equal(b.id, 'm:2');
  assert.equal(typeof a.id, 'string');
  console.log('refAdd: id вида m:<n> — 3 проверки PASS');
}

// ---------- migrate: старые числовые id ручных агентов переносятся на 'm:<n>',
// ссылки в deal.refId / deal.agents[].refId / client.refId идут следом ----------
{
  const ctx = run(['migrate', 'refsInit', 'clientsInit', 'balInit', 'isCrypto'], {
    Date, Math, Array, WALLETS: [],
    isCrypto: () => false,
  });
  const st = {
    refs: [
      {id: 1, name: 'Свой агент стенда', code: 'GR-OWN'},          // легаси: число, не prod
      {id: 501, name: 'Ромка', code: 'GR-ROMAN', prod: true},      // из базы — трогать нельзя
    ],
    clients: [{id: 1, name: 'Клиент', refId: 1}],
    deals: [{id: 1, refId: 1, agents: [{refId: 1, name: 'Свой агент стенда'}]}],
  };
  const out = ctx.migrate(st);
  const own = out.refs.find(r => r.code === 'GR-OWN');
  assert.equal(own.id, 'm:1', 'легаси-id ручного агента переносится на m:<n>');
  const roman = out.refs.find(r => r.code === 'GR-ROMAN');
  assert.equal(roman.id, 501, 'запись из базы миграция не трогает');
  assert.equal(out.clients[0].refId, 'm:1', 'ссылка клиента на ручного агента мигрирует следом');
  assert.equal(out.deals[0].refId, 'm:1', 'refId сделки мигрирует следом');
  assert.equal(out.deals[0].agents[0].refId, 'm:1', 'refId агента сделки мигрирует следом');
  console.log('migrate: перенос легаси-id ручных агентов — 4 проверки PASS');
}

// ---------- refsSync: /api/referrers → refs() с id из настоящей таблицы ----------
(async () => {
  const S = {};
  const toasts = [];
  const ctx = run(['refsSync', 'refs', 'refById'], {
    S, save: () => {}, render: () => {}, toast: s => toasts.push(s),
    refsInit: () => [],
    fetch: async (url) => {
      assert.equal(url, '/api/referrers');
      return {json: async () => ({success: true, referrers: [
        {id: 501, name: 'Ромка', code: 'GR-ROMAN', lang: 'ru', comp_model: 'revshare',
          default_percent: 15, markup_percent: 0, payout_currency: 'USDT', telegram: '@roman', active: true},
        {id: 502, name: 'TEST фикстура', code: 'GR-TEST', comp_model: 'revshare',
          default_percent: 10, active: true},
        {id: 1, name: 'Markup Partner', code: 'GR-MARKUP', comp_model: 'markup',
          markup_percent: 2.5, default_percent: 0, active: true},
      ]})};
    },
  });
  // Ручной агент уже в новом формате id (как после migrate) — refsSync его не трогает.
  S.refs = [{id: 'm:1', name: 'Свой агент стенда', code: 'GR-OWN', prod: undefined}];

  const ok = await ctx.refsSync(true);
  assert.equal(ok, true);
  const roman = ctx.refs().find(r => r.code === 'GR-ROMAN');
  assert.ok(roman, 'реферер из /api/referrers должен попасть в справочник');
  assert.equal(roman.id, 501, 'id должен быть настоящим id из таблицы referrers, а не отдельным prodId');
  assert.equal(roman.prod, true);
  assert.equal(roman.percent, 15, 'revshare берёт default_percent');
  assert.ok(!ctx.refs().some(r => r.code === 'GR-TEST'), 'TEST-строки фильтруются как раньше');
  const markup = ctx.refs().find(r => r.code === 'GR-MARKUP');
  assert.equal(markup.percent, 2.5, 'markup берёт markup_percent, а не default_percent');
  const own = ctx.refs().find(r => r.code === 'GR-OWN');
  assert.ok(own, 'свой агент стенда не должен теряться');
  assert.equal(own.id, 'm:1', 'ручной агент в своём пространстве id — refsSync его не переименовывает');

  console.log('refsSync: 6 проверок PASS');
})().catch(e => { console.error(e.stack); process.exitCode = 1; });

// ---------- crmPayload: referrer_id только для агентов из настоящей таблицы,
// и только если имя в сделке совпадает с именем найденной записи ----------
{
  const S = {refs: [
    {id: 501, name: 'Ромка', code: 'GR-ROMAN', prod: true},
    {id: 'm:9', name: 'Свой агент стенда', code: 'GR-OWN'}, // не prod — id из задачника, не из БД
    {id: 1, name: 'Чужой реферер', code: 'GR-OTHER', prod: true}, // коллизия по СТАРОМУ числовому id
  ]};
  const d = {
    client: 'Клиент', manager: 'Елизавета', payType: 'По реквизитам', type: 'Обмен', kind: '',
    object: '', payerWallet: '', incomeAmount: 100000, amountRub: null,
    rates: {broker: '2,5'}, payinHashes: [], payout: {thb: 30000, hashes: []}, paySrc: 'cash',
    agents: [
      {refId: 501, name: 'Ромка', tier: 1, comp: 'revshare', percent: 15, fixed: 0},
      {refId: 'm:9', name: 'Свой агент стенда', tier: 2, comp: 'fixed', percent: 0, fixed: 20},
      {refId: null, name: 'Без профиля', tier: 3, comp: 'revshare', percent: 5, fixed: 0},
      // Легаси: до миграции refId ручного агента совпадал с id, который теперь занят
      // настоящей записью 'Чужой реферер' — имя в сделке всё ещё старое.
      {refId: 1, name: 'Мой старый агент', tier: 4, comp: 'revshare', percent: 5, fixed: 0},
    ],
  };
  const ctx = run(['crmPayload', 'refById', 'refs'], {
    S, refsInit: () => [],
    econ: () => ({payin: 100, cost: 50, sentThb: null}),
    payinParts: () => [{usdt: 100}],
    mfList: () => [], num: v => { const n = parseFloat(String(v).replace(',', '.')); return isNaN(n) ? null : n; },
    isCrypto: () => false, crmNet: n => String(n || 'TRC20').toLowerCase(),
    PAYIN_CRM: {}, PAYOUT_CRM: {},
  });
  const p = ctx.crmPayload(d);
  const [roman, own, none, stale] = p.agents;
  assert.equal(roman.referrer_id, 501, 'агент из настоящей таблицы referrers шлётся с id, имя совпадает');
  assert.equal(own.referrer_id, undefined, 'агент задачника без записи в БД не должен слать чужой/выдуманный id');
  assert.equal(none.referrer_id, undefined, 'агент без привязки (refId=null) — тоже без id');
  assert.equal(stale.referrer_id, undefined,
    'легаси refId=1 указывает на «Чужой реферер», а не на «Мой старый агент» — id не шлём, имя не совпало');
  assert.equal(roman.name, 'Ромка');
  assert.equal(own.name, 'Свой агент стенда');
  assert.equal(stale.name, 'Мой старый агент');
  console.log('crmPayload referrer_id: 7 проверок PASS (включая защиту от коллизии по имени)');
}
