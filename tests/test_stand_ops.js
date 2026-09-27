// Операционист и деньги: брокер на отправке, адрес получателя, журнал (Карим, 27.09).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../static/stand/tasks.html'), 'utf8');
function functions(names) {
  return names.map(name => {
    const found = html.match(new RegExp(`^function ${name}\\([^]*?^}`, 'm'));
    assert.ok(found, `Функция ${name} отсутствует`);
    return found[0];
  }).join('\n');
}
function run(names, context, extra) {
  vm.createContext(context);
  vm.runInContext((extra || '') + '\n' + functions(names), context);
  return context;
}
const num = x => (x == null || x === '') ? null : parseFloat(String(x).replace(',', '.'));

// Брокер по умолчанию — тот, чей курс взят в расчёт, а не Tradex; смена брокера
// подставляет его курс, а без ответа оставляет поле пустым.
{
  const d = {id: 7, brokerDraft: null, rates: {}, quotes: [
    {cpId: 'kripta', name: 'Крипта-Платежи · Екатерина', dir: 'rub', rate: '81,40'},
    {cpId: 'asia', name: 'Asia Capital', dir: 'rub', rate: '82,10'},
    {cpId: 'coins', name: 'Coins.co.th', dir: 'thb', rate: '31,20'},
  ]};
  const ctx = run(['brokerName', 'brokerOpts', 'brokerQuote', 'brokerPicked', 'brokerRate',
    'brokerPickSet', 'brokerDraft', 'quotes', 'quoteBest', 'quoteUsed'], {
    deal: () => d, num, save: () => {}, render: () => {},
    cleanNum: v => String(v == null ? '' : v).replace(/[^\d.,]/g, ''),
    cps: () => [{id: 'kripta', name: 'Крипта-Платежи · Екатерина', dirs: ['rub']},
      {id: 'asia', name: 'Asia Capital', dirs: ['rub']}, {id: 'tradex', name: 'Tradex', dirs: ['rub']}],
    cpDir: (c, dir) => c.dirs.includes(dir),
  }, "const BROKERS=['Tradex','Крипта-Платежи','Asia Capital','IPPS','Другой'];");
  assert.equal(ctx.brokerPicked(d), 'Крипта-Платежи');
  assert.equal(ctx.brokerRate(d), '81,40');
  assert.ok(ctx.brokerOpts().includes('Крипта-Платежи'));
  assert.equal(ctx.brokerOpts().at(-1), 'Другой');
  ctx.brokerPickSet(7, 'Asia Capital');
  assert.equal(ctx.brokerPicked(d), 'Asia Capital');
  assert.equal(ctx.brokerRate(d), '82,10');
  ctx.brokerPickSet(7, 'Tradex');
  assert.equal(ctx.brokerRate(d), '', 'Tradex курс не давал — поле пустое');
  ctx.brokerDraft(7, '82,50');
  assert.equal(ctx.brokerRate(d), '82,50', 'курс можно переписать руками');
  // менеджер взял в расчёт не лучший — по умолчанию тот, что в расчёте
  const d2 = Object.assign({}, d, {brokerPick: null, brokerDraft: null, ratePick: {rub: 'asia'}});
  assert.equal(ctx.brokerPicked(d2), 'Asia Capital');
}

// Адрес получателя проверяется по сети: «4490404» не адрес (фидбэк 27.09).
{
  const ctx = run(['addrValid'], {},
    "const ADDR_RE={'TRC-20':/^T[1-9A-HJ-NP-Za-km-z]{33}$/,'ERC-20':/^0x[0-9a-fA-F]{40}$/};");
  assert.equal(ctx.addrValid('TZG8xz2sSvtge3WXaD5acYvVBN1t9kjpcX', 'TRC-20'), true);
  assert.equal(ctx.addrValid('4490404', 'TRC-20'), false);
  assert.equal(ctx.addrValid('TZG8xz2sSvtge3WXaD5acYvVBN1t9kjpcX', 'ERC-20'), false);
  assert.equal(ctx.addrValid('0x' + 'a'.repeat(40), 'ERC-20'), true);
  assert.equal(ctx.addrValid('0x' + 'a'.repeat(39), 'ERC-20'), false);
}

// s22 не пускает дальше с адресом не той сети — подсветка и тост.
{
  const d = {id: 1, code: 'СД-1', step: 's22', closed: false, postConv: 'coins', log: [], pay: {},
    transfer: {amount: '100,00', addr: '4490404', net: 'TRC-20'}};
  const toasts = [], marked = [];
  const ctx = run(['act', 'addrValid'], {
    deal: () => d, cnvMembers: () => [d], saveNote: () => {},
    document: {getElementById: id => ({id, scrollIntoView() {}, focus() {},
      classList: {add: c => marked.push(id + ':' + c)}})},
    pcSends: () => true, pcInside: () => false, pcNet: x => x.transfer.net,
    pcAmount: x => num(String(x.transfer.amount).replace(/\s/g, '')),
    toast: t => toasts.push(t), go: (x, s) => { x.step = s; }, log: () => {},
    packSettle: () => {}, flowOf: () => ['s22', 's23'], POST_CONV: [], usd: String, pcOut: () => 100,
    Number, String, Math,
  }, "const ADDR_RE={'TRC-20':/^T[1-9A-HJ-NP-Za-km-z]{33}$/,'ERC-20':/^0x[0-9a-fA-F]{40}$/};");
  ctx.act(1, 's22');
  assert.equal(d.step, 's22', 'невалидный адрес не пропускает');
  assert.ok(toasts.at(-1).includes('не адрес TRC-20'), toasts.at(-1));
  assert.ok(marked.includes('cad_1:bad'));
  d.transfer.addr = 'TZG8xz2sSvtge3WXaD5acYvVBN1t9kjpcX';
  ctx.act(1, 's22');
  assert.equal(d.step, 's23');
}

// Удаление перевода фин диром пишется в журнал (аудит 27.09 №6).
{
  const x = {id: 3, log: [], transfer: {sends: [{ref: 'demo:3:1', amount: 50, status: 'pending'}]}};
  const ctx = run(['sendDel', 'sendList'], {
    deal: () => x, toast: () => {}, save: () => {}, render: () => {},
    usd: v => '$' + v, log: (d, t) => d.log.push(t),
  });
  ctx.sendDel(3, 0);
  assert.equal(x.transfer.sends.length, 0);
  assert.ok(x.log[0].startsWith('Перевод убран: $50 · demo:3:1'), x.log[0]);
  const y = {id: 4, log: [], transfer: {sends: [{ref: 'h', amount: 5, status: 'confirmed'}]}};
  ctx.deal = () => y;
  ctx.sendDel(4, 0);
  assert.equal(y.transfer.sends.length, 1, 'подтверждённый не удаляется');
  assert.equal(y.log.length, 0);
}

// Числа пакета сравниваются как числа: «650000» и «650 000» — не правка (аудит №22).
{
  const d = {id: 1};
  const fields = {df_amountThb: '650 000', df_amountPay: '1 729 000', df_fio: 'Иванов Сергей', df_rate: '2,66'};
  const ctx = run(['docFieldSave'], {
    deal: () => d, DOC_SRC: {amountThb: 1, amountPay: 1, fio: 1, rate: 1},
    docFields: () => ({amountThb: 650000, amountPay: '1729000', fio: 'Иванов Сергей', rate: '2,66'}),
    document: {getElementById: id => fields[id] != null ? {value: fields[id]} : null},
  });
  assert.equal(JSON.stringify(ctx.docFieldSave(1)), '[]');
  fields.df_amountThb = '651 000';
  fields.df_fio = 'Иванов С.';
  assert.equal(JSON.stringify(ctx.docFieldSave(1)), JSON.stringify(['amountThb', 'fio']));
}

// Текст задачи Coins: адреса целиком, сеть, назначение, без имени клиента.
{
  const x = {code: 'СД-1472', client: 'Иванов Сергей', amountThb: 650000,
    payTo: {amount: 650000, dev: 'Test Development Co., Ltd.'},
    transfer: {amount: '21 041,67', thb: '656500', rate: '31,20', net: 'TRC-20',
      addr: 'TZG8xz2sSvtge3WXaD5acYvVBN1t9kjpcX'}};
  const w = {name: 'Кошелёк Груши', addr: 'TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn'};
  const ctx = run(['pcTaskText', 'pcNet'], {
    approx: () => ({thb: 650000}), num, cleanNum: v => String(v).replace(/[^\d.,]/g, ''),
    money: (v, c) => Number(v).toLocaleString('ru-RU') + (c ? ' ' + c : ''),
  });
  const t = ctx.pcTaskText(x, 'coins', w).replace(/ /g, ' ');
  assert.ok(t.startsWith('Сделка СД-1472. Отправляем 21 041,67 USDT с кошелька Кошелёк Груши (TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn) на кошелёк Coins (TZG8xz2sSvtge3WXaD5acYvVBN1t9kjpcX), сеть TRC-20, на конвертацию.'), t);
  assert.ok(t.includes('Нужно 656 500 ฿ на счёт MF Corporation Co., Ltd. в SCB — для оплаты инвойса застройщику (650 000 ฿, Test Development Co., Ltd.)'), t);
  assert.ok(t.includes('Курс 31,20. Оплата от MF Corporation.'), t);
  assert.ok(!t.includes('Иванов'), 'имени клиента в тексте для Coins нет');
  x.transfer.addr = '';
  assert.ok(ctx.pcTaskText(x, 'coins', w).includes('на кошелёк Coins — впишите адрес'));
}

// Дательный падеж на кнопке «Передать … на отправку».
{
  const ctx = run(['toWhom'], {});
  assert.equal(ctx.toWhom('Теодор'), 'Теодору');
  assert.equal(ctx.toWhom('Андрей'), 'Андрею');
  assert.equal(ctx.toWhom('Виталий'), 'Виталию');
  assert.equal(ctx.toWhom(''), 'владельцу');
}

console.log('stand ops: broker default, address validation, sendDel log, numeric diff, Coins text PASS');

// После Coins в CRM уходит факт SCB и курс Coins, а не процент от номинала:
// иначе прибыль CRM расходилась с карточкой ($343,23 против $295,16, QA 27.09).
{
  const E = {payin: 21300, sentThb: 655000};
  const base = {code: 'СД-1472', type: 'Оплата недвижимости', kind: 'Лизхолд', client: 'Тест',
    payType: 'По реквизитам', amountThb: 650000, rates: {usdtThb: '31,20', broker: '81,40'},
    payTo: {purpose: 'Lease payment'}, companyPct: 1, payinHashes: [], agents: []};
  const ctx = run(['crmPayload'], {
    econ: () => E, isCrypto: () => false, num, mfList: () => [], crmNet: n => n,
  }, "const PAYIN_CRM={}; const PAYOUT_CRM={};");
  const p = ctx.crmPayload(Object.assign({}, base, {postConv: 'coins', transfer: {rate: '31,5'}}));
  assert.equal(p.company_sent_thb, 655000, 'факт SCB уходит в CRM');
  assert.equal(p.buy_rate_thb_usdt, 31.5, 'курс покупки — тот, по которому Coins выдал баты');
  assert.ok(!('company_percent' in p), 'процент CRM посчитает из факта сама');
  // без конвертации через Coins — прежний процент компании
  const q = ctx.crmPayload(Object.assign({}, base, {postConv: 'ipps'}));
  assert.equal(q.company_percent, 1);
  assert.equal(q.buy_rate_thb_usdt, 31.2);
  assert.ok(!('company_sent_thb' in q));
}
