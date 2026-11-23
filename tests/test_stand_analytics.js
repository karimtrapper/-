const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const html = fs.readFileSync('static/stand/tasks.html', 'utf8');
const functions = html.slice(html.indexOf('/* ---------- аналитика ---------- */'),
  html.indexOf('/* ---------- рефералы ---------- */'));
const chat = (account, id, name) => ({account, id, name, key: account + ':' + id});
const channels = {
  tg: [chat('Команда', '-1005111122233', 'Рабочий чат'), chat('Команда', '92544321', 'Частный чат')],
  wa: [chat('Команда', '66812345678@s.whatsapp.net', 'Личный номер'),
    chat('Команда', '66812345678@g.us', 'Группа'), chat('Команда', '66812345678@lid', 'Внутренний ID'),
    chat('Команда', '66812345678', 'Неоднозначный ID')],
  bitrix: [chat('Grusha', '354', 'Карточка сделки'), chat('Другая воронка', '354', 'Карточка сделки')],
};
const stand = {
  CLOSE_REASONS: ['Не устроил курс', 'Ушёл к конкуренту'],
  SOURCES: {tg:'Telegram', wa:'WhatsApp', bitrix:'Битрикс', none:'Без переписки'},
  INQUIRY_TYPES: {agent:'Агент', client:'Клиент'},
  validInquiryType: value => value === 'agent' || value === 'client',
  PAIRS: ['RUB → THB'],
  chatList: channel => channels[channel] || [],
  dealDisplayKind: d => d.type,
  moneyKop: (number, currency) => number + ' ' + currency,
  plural: (count, one, two, many) => count === 1 ? one : count === 2 ? two : many,
  htmlText: vm.runInNewContext(html.match(/^function htmlText.+$/m)[0] + '\nhtmlText'),
  STAND: false,
  standLoadError: false,
  S: {deals: [], role:'manager'},
};
vm.createContext(stand);
vm.runInContext(functions, stand);
stand.analyticsIndexChannels();

assert.equal(stand.analyticsDateKey('2026-11-22T17:00:00'), '2026-11-23', 'naive server ISO is UTC');
assert.equal(stand.analyticsDateKey('22.11.2026, 08:00'), '2026-11-22');
assert.equal(stand.analyticsDateKey('2026-02-30'), '', 'invalid explicit date never normalizes forward');
const eventAt = Date.parse('2026-11-21T18:45:00Z');
const legacy = {createdAt:'22.11, 01:45', log:[
  {kind:'comment', role:'manager', text:'Комментарий · Менеджер: Сделка создана · Telegram', at:eventAt},
  {kind:'comment', role:'manager', text:'Комментарий · Менеджер: Запрос курса ушёл операционисту', at:eventAt},
  {text:'Шаг передан дальше', role:'manager', at:eventAt + 1},
]};
assert.equal(stand.analyticsDealDate(legacy, 'created'), '2026-11-22');
assert.equal(stand.analyticsDealDate({...legacy, log:[
  ...legacy.log.slice(0,2), {...legacy.log[2],role:'operator'}
]}, 'created'), '');
const historicalHandoff = {role:'system',text:'Переход новая заявка → s4 · manager',at:eventAt + 2};
const historical = {...legacy,log:[...legacy.log.slice(0,2),historicalHandoff]};
assert.equal(stand.analyticsDealDate(historical, 'created'), '2026-11-22');
assert.equal(stand.analyticsDealDate({...historical,createdAt:'22.11, 01:44'}, 'created'), '');
assert.equal(stand.analyticsDealDate({...historical,log:[
  ...historical.log.slice(0,2), {...historicalHandoff,kind:'comment'}
]}, 'created'), '');
assert.equal(stand.analyticsDealDate({...historical,log:[
  ...historical.log.slice(0,2), {...historicalHandoff,at:eventAt + 10001}
]}, 'created'), '');
assert.equal(stand.analyticsDealDate({createdTs:eventAt,log:[{at:eventAt,text:'Заметка'}]},
  'created'), '2026-11-22');
assert.equal(stand.analyticsDealDate({...legacy, log:legacy.log.slice(0,2)}, 'created'), '');
assert.equal(stand.analyticsDealDate({createdAt:'22.11, 01:45', log:[{at:eventAt,text:'Заметка'}]}, 'created'), '');
const legacyLost = {closed:true, closedAt:'22.11, 01:45', closeReason:'Не устроил курс'};
assert.equal(stand.analyticsDealDate({...legacyLost, log:[
  {kind:'comment',text:'Комментарий · Менеджер: Закрыта: Не устроил курс',at:eventAt},
]}, 'closed'), '');
assert.equal(stand.analyticsDealDate({...legacyLost, log:[
  {text:'Закрыта: Не устроил курс',at:eventAt},
]}, 'closed'), '2026-11-22');
assert.equal(stand.analyticsDealDate({...legacyLost,closedTs:eventAt}, 'closed'), '2026-11-22');
const window = stand.analyticsPeriod({period:'last7'}, '2026-01-03');
assert.equal(window.from, '2025-12-28');
assert.equal(window.to, '2026-01-03');
assert.equal(stand.analyticsPeriod({period:'custom', from:'2026-11-23', to:'2026-11-22'}).invalid, true);

const escaped = '<img src=x onerror=alert(1)>';
const deals = [
  {id:1, client:'Клиент', createdAt:'2026-11-20', closed:true, closedAt:'2026-11-22',
    closeReason:' не устроил  курс ', inquiryType:'agent', source:'tg',
    sourceRef:'Команда:-1005111122233', type:'Обмен валюты', pair:'RUB → THB', curBase:'rub', amountRub:54000},
  {id:2, client:escaped, createdAt:'2026-11-22', closed:true, closedAt:'2026-11-22',
    closeReason:escaped, inquiryType:'client', source:'wa', sourceRef:'Команда:66812345678@s.whatsapp.net'},
  {id:3, createdAt:'2026-11-22', closed:true, closeReason:'Успешно завершена', amountRub:'45000.25', refId:99},
  {id:4, createdAt:'2026-11-22', closed:false, refKnown:true},
  {id:5, createdAt:'22.11, 02:00', closed:false, refId:54},
  {id:6, createdAt:'2026-11-22', manualNew:true},
];
const filters = {basis:'created', inquiry:'all'};
const period = {from:'2026-11-20',to:'2026-11-22'};
const data = stand.analyticsData(deals, filters, period);
assert.equal(data.rows.length, 4);
assert.equal(data.unknownDates, 1);
const summary = stand.analyticsSummary(data.rows);
assert.deepEqual(Object.values(summary), [4, 1, 2, 1, 45000.25, 1]);
assert.equal(data.reasons.get('Не устроил курс')[0].d.id, 1);
assert.equal(stand.analyticsData(deals, {...filters,inquiry:'unknown'}, period).rows.length, 2);
assert.equal(stand.analyticsData(deals, {...filters,basis:'closed'}, period).rows.length, 2);
assert.equal(stand.analyticsData(deals, {...filters,source:'tg'}, period).rows.length, 1);
const all = stand.analyticsData(deals, filters, {from:'',to:''});
assert.equal(all.rows.length, 5);
assert.equal(all.firstDate, '2026-11-20');
assert.equal(all.lastDate, '2026-11-22');
assert.equal(all.unknownDates, 1);

const reasons = stand.analyticsReasonDeals(data.reasons, 'Не устроил курс');
assert.match(reasons, /\/tasks\?section=analytics&deal=1/);
assert.match(reasons, /Обмен валюты · RUB → THB · 54000 ₽/);
assert.match(reasons, /Создана 20\.11\.2026 · Закрыта 22\.11\.2026/);
assert.equal(stand.standDealConversation(deals[0]).href, 'https://web.telegram.org/a/#-1005111122233');
assert.equal(stand.standDealConversation({...deals[0],sourceRef:'Команда:92544321'}).href,
  'https://web.telegram.org/a/#92544321');
assert.equal(stand.standDealConversation(deals[1]).href, 'https://wa.me/66812345678');
for (const sourceRef of ['Команда:66812345678@g.us','Команда:66812345678@lid','Команда:66812345678']) {
  assert.equal(stand.standDealConversation({source:'wa',sourceRef}).href, '');
}
assert.equal(stand.standDealConversation({...deals[0],srefOther:true}), null);
assert.equal(stand.standDealConversation({...deals[0],sourceRef:'Чужой аккаунт:-1005111122233'}).href, '');
assert.equal(stand.standDealConversation({source:'bitrix',sourceRef:'Другая воронка:354'}).href, '');
assert.equal(stand.standDealConversation({source:'bitrix',sourceRef:'Grusha:197',
  bitrixSync:{bitrix_deal_id:197}}).href, 'https://b24-1tgrla.bitrix24.com/crm/deal/details/197/');
const unsafeReason = stand.analyticsReasonDeals(data.reasons, escaped);
assert.doesNotMatch(unsafeReason, /<img/);
assert.match(unsafeReason, /&lt;img/);


assert.equal(stand.analyticsInquiry({refId:42, source:'tg', sourceRef:'Команда:-1005111122233'}), 'unknown');
assert.equal(stand.analyticsInquiry({refKnown:true, inquiryType:'client'}), 'client');
assert.equal(stand.analyticsInquiry({inquiryType:'mixed'}), 'unknown');
assert.equal(stand.standDealConversation({source:'bitrix',sourceRef:'Grusha:197'}).href, '');
assert.equal(stand.standDealConversation({source:'bitrix',sourceRef:'Grusha:333',
  bitrixSync:{bitrix_deal_id:197}}).href, '');
assert.equal(stand.standDealConversation({source:'bitrix',sourceRef:'Grusha:354'}).href,
  'https://b24-1tgrla.bitrix24.com/crm/deal/details/354/');

channels.tg.push(chat('Один:два','123','Неоднозначный ключ'),chat('Один','два:123','Другая пара'));
stand.analyticsIndexChannels();
assert.equal(stand.standDealConversation({source:'tg',sourceRef:'Один:два:123'}).href, '');

stand.S.deals = deals;
const report = stand.viewAnalytics();
assert.match(report, /Сделок в задачнике/);
assert.match(report, /Конверсия закрытых/);
assert.match(report, /Отказы из-за курса/);
assert.match(report, /время Таиланда/);
assert.match(report, /<option value="agent">Агент<\/option>/);
assert.match(report, /<option value="client">Клиент<\/option>/);
assert.match(report, /<option value="unknown">Не указано<\/option>/);
assert.doesNotMatch(report, /saveStandChatType|setDealInquiryType|<img/);
console.log('PASS analytics calendar, filters, metrics, escaping, and exact conversation links');
