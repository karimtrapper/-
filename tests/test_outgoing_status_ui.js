// Подтверждённые исходящие переводы видны в задаче и карточке без открытия секций.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync('static/stand/tasks.html', 'utf8');
function source(name) {
  const match = html.match(new RegExp('^(?:async )?function ' + name + '\\([^\\n]*\\)\\{[^\\n]*\\}$', 'm')) ||
    html.match(new RegExp('^function ' + name + '\\([^]*?^}', 'm'));
  assert.ok(match, name);
  return match[0];
}
const H = 'ab'.repeat(32), OTHER = 'cd'.repeat(32);
const ctx = {S: {role: 'admin', view: 'task', deals: []},
  moneyKop: (n, unit) => `${n} ${unit}`,
  STEPS: {s24: {title: 'Одобрить перевод', n: 24}},
  ROLES: {admin: {t: 'Админ'}, findir: {t: 'Финансист'}, teodor: {t: 'Владелец'}},
  stepWho: () => 'teodor', stepTitle: () => 'Одобрить перевод', progress: () => ({i: 10, n: 15}),
  dealWallet: () => ({initiator_roles: ['operator', 'findir'], confirmer_roles: ['teodor']}),
  hasPolicy: () => true, policyOwnsVerification: () => false,
  policyStatusLine: () => '<div>Подписать: владелец</div>', policyActions: () => '',
  needsPayConfirm: () => false, prepayPanel: () => '', prepayCloseReason: () => null,
  docSide: () => '', dealTaskPathCard: () => '', payToCard: () => '',
  dealTaskPath: () => ({steps: [], active: 's24', index: 0}),
  overview: () => '<div>Карточка сделки</div>', quotesCard: () => '', ownerSummary: () => '',
  clientPayinSummarySupported: () => false,
  isCrypto: () => false, expectOf: () => ({}),
};
vm.createContext(ctx);
for (const name of ['htmlText', 'sendList', 'explorer', 'outgoingStatusSummaryData',
                    'outgoingStatusSummary', 'viewDeal']) vm.runInContext(source(name), ctx);
const base = () => ({id: 1501, code: 'СД-1501', client: 'Синтетика',
  step: 's24', type: 'Оплата недвижимости', kind: 'Фрихолд',
  pay: {}, log: [], transfer: {amount: 100, sends: []}, transferProposal: {at: 1}});
const confirmed = () => ({status: 'confirmed', hash: H, verifiedAmount: 100,
  net: 'TRC-20', timestampMs: Date.UTC(2026, 10, 9, 9, 30)});

let d = base();
let out = ctx.outgoingStatusSummary(d);
assert.match(out, /Поручение на подписи — ждём перевод в сети/);
assert.doesNotMatch(out, /class="outgoing-status-summary complete"/);
d.transfer.sends = [confirmed()];
d.serverTransferComplete = true;
out = ctx.outgoingStatusSummary(d);
assert.match(out, /class="outgoing-status-summary complete"/);
assert.match(out, /Перевод отправлен/);
assert.match(out, /Подтверждён в сети/);
assert.match(out, /100 USDT из 100 USDT/);
assert.match(out, new RegExp(H));
assert.match(out, new RegExp('https://tronscan.org/#/transaction/' + H));
assert.match(out, /Копировать хеш/);
assert.doesNotMatch(out, new RegExp(OTHER));
d.transfer.sends = [{...confirmed(), hash: '0x' + H, net: undefined}];
d.transfer.net = 'ERC-20';
out = ctx.outgoingStatusSummary(d);
assert.match(out, /class="outgoing-status-summary complete"/);
assert.match(out, new RegExp('https://etherscan.io/tx/0x' + H));
delete d.transfer.net;

d.transfer.sends = [{...confirmed(), verifiedAmount: 40}];
out = ctx.outgoingStatusSummary(d);
assert.match(out, /class="outgoing-status-summary partial"/);
assert.match(out, /40 USDT из 100 USDT/);
assert.doesNotMatch(out, /Перевод отправлен/);
d.serverTransferComplete = false;
d.transfer.sends = [{...confirmed(), beforeOrder: true}];
assert.doesNotMatch(ctx.outgoingStatusSummary(d), /class="outgoing-status-summary complete"/);
d.transfer.sends = [{...confirmed(), timeUnverified: true}];
assert.doesNotMatch(ctx.outgoingStatusSummary(d), /class="outgoing-status-summary complete"/);
d.transfer.sends = [confirmed()];
d.outgoingReview = {requestedAt: 1};
assert.doesNotMatch(ctx.outgoingStatusSummary(d), /class="outgoing-status-summary complete"/);
delete d.outgoingReview;
d.serverTransferComplete = true;
d.transfer.sends = [{...confirmed(), beforeOrder: true, timeUnverified: true}];
assert.match(ctx.outgoingStatusSummary(d), /class="outgoing-status-summary complete"/);
d.transfer.sends = [{status: 'pending', hash: H, amount: 100}];
assert.match(ctx.outgoingStatusSummary(d), /Ожидает подтверждения/);
assert.doesNotMatch(ctx.outgoingStatusSummary(d), /class="outgoing-status-summary complete"/);
d.transfer.sends = [{status: 'mismatch', hash: H, amount: 100}];
assert.match(ctx.outgoingStatusSummary(d), /Реквизиты перевода не совпали/);
d.transfer.sends = [{status: 'failed', hash: H, amount: 100}];
assert.match(ctx.outgoingStatusSummary(d), /Проверка перевода не прошла/);
d.transfer.sends = [{...confirmed(), hash: '<img src=x onerror=alert(1)>'}];
out = ctx.outgoingStatusSummary(d);
assert.match(out, /Проверьте данные подтверждения/);
assert.doesNotMatch(out, /<img|class="outgoing-status-summary complete"/);
d.transfer.sends = [];
d.transferSentReport = {at: 1};
assert.match(ctx.outgoingStatusSummary(d), /Отправку отметили — ждём проверки в сети/);
delete d.transferSentReport;
ctx.S.policyEarlyReviews = {1501: {hash: H, amount: 100}};
out = ctx.outgoingStatusSummary(d);
assert.match(out, /Ранний перевод требует подтверждения поручения/);
assert.match(out, new RegExp(H));
assert.doesNotMatch(out, /class="outgoing-status-summary complete"/);
delete ctx.S.policyEarlyReviews;

// Один и тот же статус расположен выше вкладок и закрытых блоков у всех читателей.
d = base(); d.transfer.sends = [confirmed()]; d.serverTransferComplete = true;
for (const role of ['admin', 'findir', 'teodor']) {
  ctx.S.role = role;
  ctx.S.view = 'task';
  out = ctx.viewDeal(d);
  assert.ok(out.indexOf(H) > 0 && out.indexOf(H) < out.indexOf('class="vtabs"'), role);
  assert.match(out, /Перевод отправлен/);
  ctx.S.view = 'deal';
  out = ctx.viewDeal(d);
  assert.ok(out.indexOf(H) > 0 && out.indexOf(H) < out.indexOf('class="vtabs"'), role + ' карточка');
  ctx.S.view = 'card';
  out = ctx.viewDeal(d);
  assert.ok(out.indexOf(H) > 0 && out.indexOf(H) < out.indexOf('class="vtabs"'), role + ' ссылка');
}
ctx.S.role = 'manager';
ctx.S.view = 'card';
out = ctx.viewDeal(d);
assert.ok(out.indexOf(H) > 0 && out.indexOf(H) < out.indexOf('class="vtabs"'), 'менеджер по ссылке');
d.step = 's26';
assert.match(ctx.outgoingStatusSummary(d), /Перевод отправлен/);
assert.equal(ctx.outgoingStatusSummary({id: 7, step: 's11', transfer: {sends: []}}), '');
console.log('outgoing status summary and composed read-only views: PASS');
