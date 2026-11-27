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
assert.deepEqual({...summary}, {all:4,open:1,won:1,lost:2,unknown:0,rateLost:1,turnover:45000.25});
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

const manualDeals = [
  {id:10, manual:true, closed:false, createdAt:'2026-11-21', source:'tg', inquiryType:'client', amountRub:900},
  {id:11, originMode:'manual', createdAt:'2026-11-21', closedAt:'2026-11-22',
    closeReason:' не устроил  курс ', source:'tg', inquiryType:'agent', amountRub:600},
  {id:12, step:'manual', createdAt:'2026-11-21', closeReason:'Успешно завершена',
    log:[{text:'Закрыта: Успешно завершена',at:eventAt}], source:'wa', inquiryType:'client', amountRub:500},
  {id:13, manual:true, manualNew:true, createdAt:'2026-11-21', closedAt:'2026-11-22',
    closeReason:'Успешно завершена', source:'wa', inquiryType:'client', amountRub:1500},
  {id:14, manual:true, closed:true, createdAt:'2026-11-21', closedAt:'2026-11-22',
    closeReason:'Комментарий менеджера', source:'tg', inquiryType:'client', amountRub:1500},
  {id:15, isTask:true, step:'manual', createdAt:'2026-11-21', source:'tg', inquiryType:'client'},
  {id:16, closed:true, createdAt:'2026-11-21', closedAt:'2026-11-22', source:'tg', inquiryType:'agent'},
];
const manualData = stand.analyticsData(manualDeals, filters, period);
assert.deepEqual({...stand.analyticsSummary(manualData.rows)},
  {all:6,open:2,won:1,lost:2,unknown:1,rateLost:1,turnover:500});
assert.equal(stand.analyticsOutcome(manualDeals[0]), 'open');
assert.equal(stand.analyticsOutcome({...manualDeals[0],closed:true}), 'unknown');
assert.equal(stand.analyticsOutcome({...manualDeals[0],closedTs:eventAt}), 'unknown');
assert.equal(manualData.reasons.get('Не устроил курс')[0].d.id, 11);
assert.equal(manualData.reasons.get('')[0].d.id, 16, 'previous behavior for ordinary closed records');
assert.equal(manualData.reasons.has('Комментарий менеджера'), false);
assert.equal(stand.analyticsDealDate(manualDeals[0], 'closed'), '', 'creation date is not a closing date');
assert.equal(stand.analyticsDealDate(manualDeals[2], 'closed'), '2026-11-22');
const recordedExchange = {
  id:1556, manual:true, originMode:'manual', step:'manual', closed:false,
  createdAt:'2026-11-26', amountRub:56749.48, amountUsdt:631,
  payinHashes:[{hash:'incoming',amount:631}], payout:{usdt:619.24,hashes:[{hash:'outgoing',amount:619.24}]},
};
assert.equal(stand.analyticsOutcome(recordedExchange), 'won');
assert.equal(stand.analyticsOutcome({...recordedExchange,closeReason:'Ушёл к конкуренту'}), 'lost');
assert.equal(stand.analyticsOutcome({...recordedExchange,payout:{usdt:619.24}}), 'open');
assert.equal(stand.analyticsOutcome({...recordedExchange,payinHashes:[{hash:'incoming',amount:null}]}), 'open');
assert.equal(stand.analyticsOutcome({...recordedExchange,manual:false,originMode:null,step:'s4'}), 'open');
assert.equal(stand.analyticsDealDate(recordedExchange, 'closed'), '');
const recordedRows = stand.analyticsData([recordedExchange,{...recordedExchange,manualNew:true}], filters, {from:'',to:''});
assert.deepEqual({...stand.analyticsSummary(recordedRows.rows)},
  {all:1,open:0,won:1,lost:0,unknown:0,rateLost:0,turnover:56749.48});
assert.deepEqual({...stand.analyticsSummary(
  stand.analyticsData(manualDeals, {...filters,source:'tg',inquiry:'client'}, period).rows)},
  {all:3,open:2,won:0,lost:0,unknown:1,rateLost:0,turnover:0});
const closedFilters = {...filters,basis:'closed'};
const manualClosedWindow = stand.analyticsData(manualDeals, closedFilters, period);
assert.equal(manualClosedWindow.unknownDates, 0);
assert.deepEqual({...stand.analyticsSummary(manualClosedWindow.rows)},
  {all:4,open:0,won:1,lost:2,unknown:1,rateLost:1,turnover:500});
const manualClosedAll = stand.analyticsData(manualDeals, closedFilters, {from:'',to:''});
assert.equal(manualClosedAll.unknownDates, 0);
assert.deepEqual({...stand.analyticsSummary(manualClosedAll.rows)},
  {all:4,open:0,won:1,lost:2,unknown:1,rateLost:1,turnover:500});

stand.S.deals = manualDeals;
vm.runInContext("Object.assign(analyticsFilters,{period:'all',basis:'created'})", stand);
const renderedManual = stand.viewAnalytics();
assert.match(renderedManual, /Закрыто всего<\/div><div class="stat-value num">4<\/div>/);
assert.match(renderedManual, /data-outcome="unknown"[^>]+>Итог не указан · 1<\/button>/);
assert.match(renderedManual, /1 из 3 закрытых с известным итогом/);
assert.match(renderedManual, /Итог не указан">1<\/td>/);
vm.runInContext("analyticsFilters.reason=ANALYTICS_OUTCOME_FILTERS.unknown", stand);
const unknownResults = stand.viewAnalytics();
assert.match(unknownResults, /Сделки без указанного итога/);
assert.deepEqual([...unknownResults.matchAll(/data-deal="(\d+)"/g)].map(match => match[1]), ['14']);
vm.runInContext("analyticsFilters.reason=ANALYTICS_OUTCOME_FILTERS.open", stand);
const openResults = stand.viewAnalytics();
assert.match(openResults, /Открытые сделки/);
assert.match(openResults, /Создана 21\.11\.2026 · Открыта/);
assert.doesNotMatch(openResults, /Дата закрытия неизвестна/);
assert.deepEqual([...openResults.matchAll(/data-deal="(\d+)"/g)].map(match => match[1]), ['15', '10']);
stand.S.deals = [...manualDeals,recordedExchange];
vm.runInContext("analyticsFilters.reason=ANALYTICS_OUTCOME_FILTERS.won", stand);
const wonResults = stand.viewAnalytics();
assert.match(wonResults, /Успешно закрытые сделки/);
assert.deepEqual([...wonResults.matchAll(/data-deal="(\d+)"/g)].map(match => match[1]), ['12', '1556']);
vm.runInContext("Object.assign(analyticsFilters,{period:'custom',basis:'closed',from:'2026-11-20',to:'2026-11-22'})", stand);
assert.match(stand.viewAnalytics(), /Исключено из периода: 1 сделка без точной даты закрытия/);
vm.runInContext("analyticsFilters.period='all'", stand);
assert.match(stand.viewAnalytics(), /Учтено за всё время: 1 сделка без точной даты закрытия/);
console.log('PASS analytics calendar, filters, metrics, escaping, and exact conversation links');
