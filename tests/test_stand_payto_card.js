const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../static/stand/tasks.html'), 'utf8');
const names = ['payToReady', 'payToConfirmed', 'payToCardStatus', 'payToCardFields', 'payToCard', 'payToCopy'];
const source = names.map(name => {
  const found = html.match(new RegExp(`^function ${name}\\([^]*?^}`, 'm'));
  assert.ok(found, name);
  return found[0];
}).join('\n');

const filled = {
  id: 1484, type: 'Оплата недвижимости', kind: 'Фрихолд', step: 's22', reqTask: 'done',
  pay: {}, log: [{text: 'Реквизиты для оплаты заполнены', ts: '12.10 14:25', role: 'manager', by: 'Елизавета'}],
  payTo: {dev: 'Sansiri Public Company Limited', bank: 'Kasikornbank', swift: 'KASITHBK',
    acc: '012-3-45678-9', branch: 'Siam Branch', bankAddr: '123 Bangkok Road, Thailand',
    inv: 'INV-1484', amount: 11300, purpose: 'Payment for unit 1484'},
  stepNotes: {s15: 'Оплату проводим наперёд'},
};
const empty = {
  id: 1485, type: 'Оплата недвижимости', kind: 'Фрихолд', step: 's14',
  reqTask: null, pay: {}, log: [], payTo: {}, stepNotes: {},
};

function run(role) {
  let copied = '';
  const ctx = {
    S: {role}, ROLES: {manager: {t: 'менеджер'}},
    htmlText: value => String(value == null ? '' : value).replace(/&/g, '&amp;').replace(/</g, '&lt;'),
    logWhen: entry => entry.ts, usd: value => '$' + value.toFixed(2),
    money: (value, sign) => `${value} ${sign}`, reqOpen: deal => deal.reqTask === 'open',
    deal: id => id === 1484 ? filled : empty, copyAsk: value => { copied = value; },
  };
  vm.createContext(ctx);
  vm.runInContext(source, ctx);
  return {ctx, getCopied: () => copied};
}

for (const role of ['manager', 'operator', 'admin', 'teodor']) {
  const {ctx, getCopied} = run(role);
  const card = ctx.payToCard(filled);
  for (const value of ['Sansiri Public Company Limited', 'Kasikornbank', 'KASITHBK',
    '012-3-45678-9', 'Siam Branch', '123 Bangkok Road, Thailand', 'INV-1484',
    '$11300.00', 'Из заявки', 'Payment for unit 1484', 'Оплату проводим наперёд',
    '12.10 14:25', 'Елизавета']) assert.ok(card.includes(value), `${role}: ${value}`);
  assert.equal(card.includes('>Изменить</button>'), role === 'manager');
  if (role === 'manager') assert.match(card, /reqReopen\(1484,'правка реквизитов из карточки'\)/);
  const compact = ctx.payToCard(filled, true);
  assert.match(compact, /Копировать реквизиты/);
  assert.doesNotMatch(compact, />Изменить<\/button>/);
  ctx.payToCopy(1484);
  assert.match(getCopied(), /Адрес банка: 123 Bangkok Road, Thailand/);
  assert.match(getCopied(), /Комментарий менеджера: Оплату проводим наперёд/);
}

{
  const {ctx} = run('manager');
  assert.match(ctx.payToCard(empty), /Ещё не заполнены — задача у менеджера/);
  assert.doesNotMatch(ctx.payToCard(empty), />Заполнить<\/button>/);
  empty.reqTask = 'open';
  assert.match(ctx.payToCard(empty), /openTask\(1485\).*?>Заполнить<\/button>/);
  assert.doesNotMatch(run('operator').ctx.payToCard(empty), />Заполнить<\/button>/);
  empty.reqTask = null;
  empty.step = 's15';
  assert.match(ctx.payToCard(empty), />Заполнить<\/button>/);
  empty.step = 's14';
  empty.reqTask = null;
  filled.payToConfirm = {payTo: {...filled.payTo}, at: '13.10 09:00'};
  assert.match(ctx.payToCard(filled), /Подтверждены перед IPPS · 13.10 09:00/);
  filled.payTo.purpose = 'Updated purpose';
  assert.match(ctx.payToCard(filled), /Изменены после подтверждения/);
  filled.pay.invoicePaid = true;
  assert.doesNotMatch(ctx.payToCard(filled), />Изменить<\/button>/);
}

assert.match(html, /\$\{view==='deal'\?payToCard\(d\):''\}\s*<div class="cols">/);
assert.match(html, /view==='task'&&S\.role==='operator'&&\['s22','s23','s24','s25','s26'\]\.includes\(d\.step\)&&branch!=='conversion'\?payToCard\(d,true\)/);
console.log('payTo card: roles, full fields, status, old deals, copy and placement OK');
