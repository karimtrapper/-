// Задачник: политика кошелька («Заводит»/«Подписывает»), «Передать», перехват, блок реквизитов только у claim.
// Реализация в tasks.html сверяется с той же таблицей, что и wallet_policy.py (tests/fixtures/wallet_policy_table.json).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const html = fs.readFileSync('static/stand/tasks.html', 'utf8');
const source = name => {
  const m = html.match(new RegExp('^(?:async )?function ' + name + '\\([^]*?^}', 'm'));
  assert.ok(m, 'нет функции ' + name);
  return m[0];
};
const consts = html.slice(html.indexOf('const POLICY_ROLE_ORDER'), html.indexOf('function policyInitiators'));
const names = ['hasPolicy', 'policyInitiators', 'policyInitiateTargets', 'policyInitiateRole', 'policySignRole',
  'policySignTargets', 'policyCanClaim', 'policyRoleNames', 'bkkTime', 'policyReleasedByMe', 'policyLastReleased',
  'policyLocked', 'policyOwnsSend', 'policyOwnsSign', 'policyNeedsApproval', 'policyApprovalActor',
  'handoffTargets', 'handoffBlock', 'handoffToggle', 'markSentBlock', 'transferMarkSent', 'policyActions', 'policyStatusLine', 'walletPolicyLine', 'transferHandoff',
  'transferClaim', 'walletRolesFields', 'txShort'];
const table = JSON.parse(fs.readFileSync('tests/fixtures/wallet_policy_table.json', 'utf8'));

// Массивы из vm-контекста другой realm: сравниваем через JSON.
const eq = (actual, expected, msg) => assert.equal(JSON.stringify(actual), JSON.stringify(expected), msg);
function makeCtx(overrides = {}) {
  const calls = [];
  const ctx = {calls,
    S: {role: 'manager'}, standMeId: 7, standVer: 11, wallet: null, deals: {},
    htmlText: s => String(s ?? ''), usd: n => '$' + n, render: () => {}, toast: () => {},
    cnvMembers: () => [], bkkLabel: null,
    dealWallet: () => ctx.wallet,
    standAction: async (path, body) => { calls.push({path, body}); return {success: true}; },
    deal: id => ctx.deals[id],
    window: {confirm: () => true}, document: {querySelectorAll: () => []},
    ...overrides,
  };
  vm.createContext(ctx);
  vm.runInContext(consts + names.map(source).join('\n'), ctx);
  return ctx;
}
const walletOf = row => ({name: row.purpose, initiator_roles: row.initiator_roles,
  confirmer_roles: row.confirmer_roles, owner_can_alone: row.owner_can_alone});
const run = (ctx, code) => vm.runInContext(code, ctx);

// ---- 1. Те же таблицы, что у Python: «завести», «передать», «подписать» — все 6 кошельков
for (const [address, row] of Object.entries(table)) {
  const ctx = makeCtx();
  const w = walletOf(row);
  assert.equal(ctx.hasPolicy(w), true, address);
  assert.equal(ctx.policyInitiateRole({}, w), row.initial_role, address);
  eq(ctx.policyInitiateTargets(w, row.initial_role), row.initiate_targets_from_start, address);
  for (const role of ['operator', 'findir', 'teodor']) {
    eq(ctx.policyInitiateTargets(w, role), row.initiate_targets[role], address + ' ' + role);
    assert.equal(ctx.policyCanClaim({}, w, role), row.can_claim[role], address + ' claim ' + role);
    const d = {transferClaim: {role, byId: 1, fingerprint: 'f'}};
    assert.equal(ctx.policySignRole(d, w), row.sign[role].default, address + ' sign ' + role);
    eq(ctx.policySignTargets(d, w), row.sign[role].targets, address + ' sign targets ' + role);
  }
}
assert.equal(makeCtx().hasPolicy({initiator_roles: ['operator'], confirmer_roles: []}), false);
assert.equal(makeCtx().hasPolicy({initiator_roles: [], confirmer_roles: ['teodor']}), false);
assert.equal(makeCtx().hasPolicy(null), false);
console.log('policy table (6 wallets) matches python: PASS');

// ---- 2. Видимость «Передать» и состав вариантов: роль × кошелёк × состояние
const REALTY = table['TDuDeRiwrLLN3hnnA57G5yM6ibg58A6wZk'], EXCHANGE = table['TA6S3RBEY57jq8fXEVVsU6H9JZ18inenG4'];
const MFSTR = table['TR68DHoj71Nz4FoTvqnBFQK2Fc6NkEK6nQ'], C99 = table['TQPv1GETKVjSWZymdMu5WbSSeS6JhL2KHt'];
function targets(roleOfViewer, row, d) {
  const ctx = makeCtx({S: {role: roleOfViewer}});
  ctx.wallet = walletOf(row);
  return ctx.handoffTargets(Object.assign({id: 1, step: 's23'}, d));
}
for (const viewer of ['operator', 'admin']) {
  eq(targets(viewer, REALTY, {}), ['findir', 'teodor'], 'Недвижимость: у оператора → фин/владелец');
  eq(targets(viewer, EXCHANGE, {}), ['teodor'], 'Обменник: заводит только оператор');
  eq(targets(viewer, MFSTR, {}), ['teodor'], 'Mfstr: у финансиста → владелец');
  eq(targets(viewer, C99, {}), ['teodor'], '99: только «Владельцу»');
  eq(targets(viewer, REALTY, {transferHandoff: {role: 'findir'}}), ['operator', 'teodor']);
}
for (const viewer of ['manager', 'findir', 'teodor']) {
  eq(targets(viewer, REALTY, {}), [], viewer + ' не передаёт');
}
// после claim — это перехват (те же варианты, кроме запрета при подтверждении/находке/тревоге)
const claimed = {transferClaim: {role: 'operator', byId: 3, byName: 'Настя', at: 1700000000000, fingerprint: 'f'}};
eq(targets('operator', REALTY, claimed), ['operator', 'findir', 'teodor']);
eq(targets('admin', REALTY, claimed), ['operator', 'findir', 'teodor']);
eq(targets('operator', REALTY, Object.assign({transferConfirmation: {ownerAlone: true}}, claimed)), []);
eq(targets('operator', REALTY, Object.assign({transferFound: {hashes: ['a']}}, claimed)), []);
eq(targets('operator', REALTY, Object.assign({transferAlarm: {hashes: ['a', 'b']}}, claimed)), []);
// свой перевод (держатель claim — этот сотрудник, id 7) перехватом не передают: у него «Я отправил»
eq(targets('operator', REALTY, {transferClaim: {role: 'operator', byId: 7, at: 1, fingerprint: 'f'}}), []);
// s24: переназначение подписи, пока нет подтверждения
eq(targets('operator', EXCHANGE, Object.assign({step: 's24'}, claimed)), ['teodor']);
eq(targets('manager', EXCHANGE, Object.assign({step: 's24'}, claimed)), [], 'клиентский менеджер не переназначает');
eq(targets('operator', REALTY, Object.assign({step: 's24'}, claimed)), []);
eq(targets('operator', EXCHANGE, {step: 's24', transferClaim: claimed.transferClaim,
  transferConfirmation: {byId: 9}}), []);
eq(targets('operator', EXCHANGE, {step: 's22'}), []);
eq(targets('operator', EXCHANGE, {step: 's23', outgoingReview: {requestedAt: 'x'}}), []);
// заводивший раунд оператор не назначает подпись на себя (кошелёк «оператор подписывает»)
{
  const both = {name: 'x', initiator_roles: ['operator', 'findir'], confirmer_roles: ['operator', 'teodor'], owner_can_alone: false};
  const ctx = makeCtx({S: {role: 'operator'}, standMeId: 7});
  ctx.wallet = both;
  const d = {id: 1, step: 's24', transferClaim: {role: 'findir', byId: 9, fingerprint: 'f'},
    signHandoff: {role: 'teodor', claimFingerprint: 'f'}, transferClaimHistory: [{byId: 7}]};
  eq(ctx.handoffTargets(d), ['teodor'].filter(() => false), 'прежний исполнитель раунда: «Операционисту» нет');
  d.transferClaimHistory = [{byId: 8}];
  eq(ctx.handoffTargets(d), ['operator']);
}
console.log('handoff targets by role/wallet/state: PASS');

// ---- 3. Кнопка «Передать» → выбор ролей → вызов сервера; перехват с подтверждением и claimAt
{
  const ctx = makeCtx({S: {role: 'operator'}});
  ctx.wallet = walletOf(REALTY);
  ctx.deals[1] = {id: 1, step: 's23'};
  let block = ctx.handoffBlock(ctx.deals[1]);
  assert.match(block, /data-handoff-open[^>]*>Передать<\/button>/);
  assert.doesNotMatch(block, /data-handoff-to/, 'варианты скрыты до нажатия');
  ctx.handoffToggle(1);
  block = ctx.handoffBlock(ctx.deals[1]);
  eq([...block.matchAll(/data-handoff-to="(\w+)"[^>]*>([^<]+)</g)].map(x => x[1] + ':' + x[2]),
    ['findir:Финансисту', 'teodor:Владельцу']);
  (async () => {
    await ctx.transferHandoff(1, 'findir');
    eq(ctx.calls[0], {path: '/api/stand/transfer/handoff',
      body: {dealId: 1, version: 11, toRole: 'findir'}});
    // перехват: confirm-диалог с именем и временем, takeover + claimAt
    const asked = [];
    ctx.window.confirm = text => { asked.push(text); return true; };
    ctx.deals[2] = Object.assign({id: 2, step: 's23'}, claimed);
    ctx.calls.length = 0;
    await ctx.transferHandoff(2, 'findir');
    assert.equal(asked.length, 1);
    assert.match(asked[0], /^Настя начал перевод в \d\d:\d\d\. Если транзакция уже заведена в кошельке, второй раз не заводите\./);
    eq(ctx.calls[0].body, {dealId: 2, version: 11, toRole: 'findir', takeover: true, claimAt: 1700000000000});
    // отказ в диалоге — ничего не уходит на сервер
    ctx.window.confirm = () => false;
    ctx.calls.length = 0;
    await ctx.transferHandoff(2, 'teodor');
    assert.equal(ctx.calls.length, 0);
    console.log('handoff / takeover requests: PASS');
  })().catch(e => { console.error(e); process.exitCode = 1; });
}

// ---- 3b. «Деньги отправлены»: поле хеша у операциониста/админа (не у держателя claim), подставляется найденный хеш
{
  const found = 'ab'.repeat(32);
  const block = (role, d, me = 7) => {
    const ctx = makeCtx({S: {role}, standMeId: me});
    ctx.wallet = walletOf(REALTY);
    ctx.val = id => 'https://tronscan.org/#/transaction/' + found;
    return ctx.markSentBlock(Object.assign({id: 1, step: 's23'}, d));
  };
  assert.match(block('operator', {}), /data-mark-sent-btn[^>]*>Деньги отправлены<\/button>/);
  assert.match(block('admin', {}), /Деньги отправлены/);
  assert.match(block('operator', {step: 's24', transferClaim: {byId: 3, role: 'operator'}}), /Деньги отправлены/);
  assert.match(block('operator', {transferFound: {hashes: [found]}}), new RegExp('value="' + found + '"'), 'найденный хеш подставлен');
  for (const role of ['manager', 'findir', 'teodor'])
    assert.equal(block(role, {}), '', role + ' кнопки не видит');
  assert.equal(block('operator', {transferClaim: {byId: 7, role: 'operator'}}), '', 'у держателя claim — «Я отправил»');
  assert.equal(block('operator', {transferAlarm: {hashes: ['a', 'b']}}), '', 'при тревоге кнопки нет');
  assert.equal(block('operator', {serverTransferComplete: true}), '');
  assert.equal(block('operator', {step: 's22'}), '');
  const ctx = makeCtx({S: {role: 'operator'}});
  ctx.val = () => 'https://tronscan.org/#/transaction/' + found;
  ctx.transferMarkSent(1).then(() => {
    eq(ctx.calls[0], {path: '/api/stand/transfer/mark-sent', body: {dealId: 1, version: 11, hash: found}});
    console.log('mark sent request: PASS');
  }).catch(e => { console.error(e); process.exitCode = 1; });
}

// ---- 4. Чья это задача: «завести» / «подписать»
function owns(kind, role, row, d) {
  const ctx = makeCtx({S: {role}, standMeId: 7});
  const w = walletOf(row);
  return kind === 'send' ? ctx.policyOwnsSend(d, w, role) : ctx.policyOwnsSign(d, w, role);
}
assert.equal(owns('send', 'operator', REALTY, {}), true);
assert.equal(owns('send', 'findir', REALTY, {}), false, 'до передачи финансист задачу не видит');
assert.equal(owns('send', 'findir', REALTY, {transferHandoff: {role: 'findir'}}), true);
assert.equal(owns('send', 'operator', REALTY, {transferHandoff: {role: 'findir'}}), false);
assert.equal(owns('send', 'teodor', REALTY, {}), true, 'владелец может сам');
assert.equal(owns('send', 'findir', EXCHANGE, {}), false);
assert.equal(owns('send', 'operator', MFSTR, {}), false, 'у Mfstr заводит финансист');
assert.equal(owns('send', 'findir', MFSTR, {}), true);
assert.equal(owns('send', 'operator', REALTY, {transferClaim: {byId: 7, role: 'operator'}}), true);
assert.equal(owns('send', 'operator', REALTY, {transferClaim: {byId: 8, role: 'operator'}}), false);
assert.equal(owns('send', 'operator', REALTY, {transferClaimHistory: [{byId: 7}]}), false, 'прежний исполнитель');
assert.equal(owns('send', 'operator', REALTY, {transferFound: {hashes: ['a']}}), false);
assert.equal(owns('send', 'operator', REALTY, {transferAlarm: {hashes: ['a']}}), false);
const claimBy = (role, byId) => ({transferClaim: {role, byId, fingerprint: 'f'}});
assert.equal(owns('sign', 'teodor', REALTY, claimBy('operator', 8)), true);
assert.equal(owns('sign', 'findir', REALTY, claimBy('operator', 8)), false);
assert.equal(owns('sign', 'findir', EXCHANGE, claimBy('operator', 8)), true);
assert.equal(owns('sign', 'teodor', EXCHANGE, claimBy('operator', 8)), false, 'подпись назначена финансисту');
assert.equal(owns('sign', 'teodor', EXCHANGE, Object.assign({signHandoff: {role: 'teodor', claimFingerprint: 'f'}},
  claimBy('operator', 8))), true);
assert.equal(owns('sign', 'findir', EXCHANGE, Object.assign({signHandoff: {role: 'teodor', claimFingerprint: 'f'}},
  claimBy('operator', 8))), false);
assert.equal(owns('sign', 'findir', REALTY, claimBy('findir', 7)), false, 'кто завёл — не подписывает');
console.log('task ownership (send/sign): PASS');

// ---- 5. Строка статуса и предупреждения
{
  const ctx = makeCtx({S: {role: 'operator'}});
  ctx.wallet = walletOf(REALTY);
  const at = 1700000000000;
  let out = ctx.policyStatusLine({id: 1, step: 's23'});
  assert.match(out, /Завести: операционист/);
  out = ctx.policyStatusLine({id: 1, step: 's23', transferHandoff: {role: 'findir', byName: 'Анна', at}});
  assert.match(out, /Завести: финансист · Передал Анна, \d\d:\d\d/);
  out = ctx.policyStatusLine({id: 1, step: 's23', transferClaim: {byName: 'Настя', at, role: 'operator'}});
  assert.match(out, /В работе у Настя с \d\d:\d\d/);
  out = ctx.policyStatusLine({id: 1, step: 's24', transferClaim: {role: 'operator', byId: 3, fingerprint: 'f'}});
  assert.match(out, /Подписать: владелец/);
  const released = {id: 1, step: 's23', transferHandoff: {role: 'findir', byName: 'Анна', at},
    transferClaimHistory: [{byId: 3, byName: 'Настя', at}]};
  out = ctx.policyStatusLine(released);
  assert.match(out, /data-takeover-warning[^]*Настя начал перевод в \d\d:\d\d\. Если транзакция уже заведена в кошельке, второй раз не заводите\./);
  ctx.standMeId = 3;                                           // прежний исполнитель
  out = ctx.policyStatusLine(released);
  assert.match(out, /Передана: финансист/);
  assert.doesNotMatch(out, /data-takeover-warning/);
  ctx.standMeId = 7;
  out = ctx.policyStatusLine({id: 1, step: 's23', transferClaim: {byName: 'Настя', at, role: 'operator'},
    transferAlarm: {hashes: ['aa', 'bb']}});
  assert.match(out, /data-transfer-alarm[^]*Найдено два перевода:<\/b> aa, bb\. Проверьте возврат\./);
  assert.doesNotMatch(out, /Снять тревогу/, 'оператор тревогу не снимает');
  ctx.S.role = 'teodor';
  assert.match(ctx.policyStatusLine({id: 1, step: 's23', transferClaim: {byName: 'Н', at, role: 'operator'},
    transferAlarm: {hashes: ['aa', 'bb']}}), /Снять тревогу/);
  out = ctx.policyStatusLine({id: 1, step: 's23', transferClaim: {byName: 'Н', at, role: 'operator'},
    transferFound: {hashes: ['f'.repeat(64)]}});
  assert.match(out, /Перевод найден в сети/);
  assert.equal(makeCtx().policyStatusLine({id: 1, step: 's23'}), '', 'без политики строки нет');
  assert.match(ctx.walletPolicyLine(walletOf(REALTY)), /Заводит: <b>operator|Заводит: <b>операционист \/ финансист<\/b> · Подписывает: <b>владелец<\/b> · владелец может отправить сам/);
  assert.match(ctx.walletPolicyLine(walletOf(MFSTR)), /Заводит: <b>финансист<\/b> · Подписывает: <b>владелец<\/b>/);
  console.log('status line, takeover warning, alarm: PASS');
}

// ---- 6. s23: блок «завести в кошельке» рендерится только держателю claim
{
  const body = html.slice(html.indexOf('  s23:()=>{'), html.indexOf('  s24:()=>{'));
  const render = 'function renderS23(d,ap){return (' + body.trim().slice('s23:'.length).replace(/,$/, '') + ')();}';
  function s23(role, d, me = 7) {
    const ctx = makeCtx({S: {role}, standMeId: me});
    ctx.val = () => '';
    ctx.wallet = walletOf(REALTY);
    Object.assign(ctx, {num: () => 0, avgUsdt: () => 30, SOURCES_PAY: {coins: {cur: 'thb'}}, convOf: () => null,
      policySignerCards: () => '', packTasks: () => 'PACK_BLOCK', transferModeBlock: () => '',
      outgoingReviewBlock: () => '', personalSend: () => false, isCrypto: () => true, trow: () => '',
      money: String, moneyKop: String, hashSum: () => 0, payinHashRows: () => '', plural: () => '',
      walletSends: () => 'по правилам кошелька', walletSigner: () => 'фин дир',
      jsLiteralAttr: String, addressDisclosure: String, copyAsk: () => {}, ippsPayoutOrder: null,
      transferApprove: () => {}, policyApprovalActor: () => false});
    vm.runInContext(render, ctx);
    return ctx.renderS23(Object.assign({id: 1, step: 's23', rates: {}, pay: {}, transfer: {amount: 5000}}, d), {thb: 0});
  }
  const mine = {transferClaim: {byId: 7, byName: 'Я', role: 'operator', at: 1700000000000, fingerprint: 'f'}};
  const theirs = {transferClaim: {byId: 8, byName: 'Настя', role: 'operator', at: 1700000000000, fingerprint: 'f'}};
  const claimerCard = s23('operator', mine);
  assert.match(claimerCard, /PACK_BLOCK/, 'держатель claim видит реквизиты');
  assert.match(claimerCard, /onclick="act\(1,'s23'\)">Я отправил<\/button>/, 'кнопка исполнителя называется «Я отправил»');
  assert.doesNotMatch(claimerCard, /Передать на подтверждение|Проверить перевод в сети|Деньги отправлены/);
  const other = s23('findir', theirs);
  assert.doesNotMatch(other, /PACK_BLOCK/, 'остальные блок реквизитов не получают');
  assert.match(other, /В работе у Настя с \d\d:\d\d/);
  assert.doesNotMatch(other, /data-claim/);
  const before = s23('operator', {});
  assert.doesNotMatch(before, /PACK_BLOCK/, 'до claim блока нет даже у назначенной роли');
  assert.match(before, /data-claim[^>]*>Начать работу<\/button>/);
  assert.match(s23('operator', {}), /Деньги отправлены/, 'операционисту без claim доступно «Деньги отправлены»');
  assert.match(s23('teodor', {}), /data-claim[^>]*>Отправить<\/button>/, 'владелец, отправляющий один — «Отправить»');
  assert.doesNotMatch(s23('findir', {}), /data-claim/, 'до передачи финансисту кнопки нет');
  assert.doesNotMatch(s23('operator', {transferClaimHistory: [{byId: 7, byName: 'Я', at: 1}]}), /data-claim/,
    'прежний исполнитель после перехвата');
  assert.doesNotMatch(s23('operator', {transferFound: {hashes: ['a']}}), /data-claim/);
  console.log('s23 claim-only requisites block: PASS');
}

// ---- 7. Форма нового кошелька: роли задаёт только админ
{
  const admin = makeCtx({S: {role: 'admin'}}).walletRolesFields();
  assert.equal((admin.match(/data-nw-roles="initiator"/g) || []).length, 3);
  assert.equal((admin.match(/data-nw-roles="confirmer"/g) || []).length, 3);
  assert.match(admin, /Владелец может отправить сам/);
  const operator = makeCtx({S: {role: 'operator'}}).walletRolesFields();
  assert.doesNotMatch(operator, /data-nw-roles/);
  assert.match(operator, /задаёт админ/);
  console.log('new wallet form roles (admin only): PASS');
}
