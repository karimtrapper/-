// Фрихолд без батов (спека docs/specs/2026-09-28-freehold-no-baht.md).
// Формулы против контрольного примера спеки: X=45000 $, курс 82,4531,
// тариф банк 0,8%+50$ / софт-счёт 1,5%+50$. Регрессия: лизхолд/обмен не меняются.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../static/stand/tasks.html'), 'utf8');
function functions(names) {
  // Однострочные функции (закрывающая } на той же строке, не с новой) не ловятся
  // многострочным шаблоном ниже — пробуем сначала их, потом обычный вариант.
  return names.map(name => {
    const oneLine = html.match(new RegExp(`^function ${name}\\([^\\n]*\\)\\{[^\\n]*\\}$`, 'm'));
    if (oneLine) return oneLine[0];
    const found = html.match(new RegExp(`^function ${name}\\([^]*?^}`, 'm'));
    assert.ok(found, `Функция ${name} отсутствует`);
    return found[0];
  }).join('\n');
}
function consts(names) {
  // const в vm-скрипте не становится свойством контекста (в отличие от var
  // и объявлений function) — переобъявляем через var, чтобы ctx.NAME работал.
  return names.map(name => {
    const found = html.match(new RegExp(`^const ${name}\\s*=[\\s\\S]*?;`, 'm'));
    assert.ok(found, `Константа ${name} отсутствует`);
    return found[0].replace(/^const /, 'var ');
  }).join('\n');
}
function run(fnNames, constNames, context) {
  vm.createContext(context);
  vm.runInContext(consts(constNames) + '\n' + functions(fnNames), context);
  return context;
}
const round2 = x => Math.round(x * 100) / 100;
const approxEq = (a, b, eps = 0.005) => assert.ok(Math.abs(a - b) < eps, `${a} !~ ${b}`);

// ── Тариф и формула S = X·(1+p)+F ────────────────────────────────────────
{
  const ctx = run(['freeholdFee', 'freeholdSend'], ['IPPS_TARIFFS'], {});
  const { bank, soft } = ctx.IPPS_TARIFFS;
  assert.equal(bank.percent, 0.8); assert.equal(bank.fixed, 50);
  assert.equal(soft.percent, 1.5); assert.equal(soft.fixed, 50);
  // Контрольный пример спеки §4.4: X=45000 → банк 45410,00, софт-счёт 45725,00
  approxEq(ctx.freeholdSend(45000, bank), 45410.00);
  approxEq(ctx.freeholdSend(45000, soft), 45725.00);
  approxEq(ctx.freeholdFee(45000, bank), 410.00);
  approxEq(ctx.freeholdFee(45000, soft), 725.00);
}

// ── econ(): фрихолд без батов, без зависимости от курса покупки ─────────
{
  const ctx = run(['econ', 'ippsTariff', 'freeholdFee', 'freeholdSend'], ['IPPS_TARIFFS'], {
    payinParts: () => [{ usdt: 45500, calc: 45500, fact: 45500, kept: 0, ctrl: 0 }],
    mfList: () => [], hashSum: () => null, pcAmount: () => null, refAgents: () => [],
    num: x => (x == null ? null : parseFloat(String(x).replace(',', '.'))),
    cleanNum: x => String(x).replace(/[^\d.,]/g, ''), Math,
  });
  const d = { type: 'Оплата недвижимости', kind: 'Фрихолд', invoiceUsd: 45000,
    ippsTariff: 'bank', rates: {}, agents: [] };
  const e = ctx.econ(d);
  assert.equal(e.invoiceUsd, 45000);
  assert.equal(e.feePercent, 0.8); assert.equal(e.feeFixed, 50);
  approxEq(e.bankFee, 410.00);
  approxEq(e.sentUsd, 45410.00);
  approxEq(e.cost, 45410.00);
  approxEq(e.crypto, 45500 - 45410.00);
  approxEq(e.gross, e.crypto);
  assert.equal(e.pockets, 'один', 'у фрихолда один карман — не как у лизхолда');
  assert.equal(e.sentThb, null, 'батов быть не должно вообще');
  assert.equal(e.feeThb, null);
  assert.equal(e.ready, true, 'готовность не зависит от курса покупки батов — его просто нет');

  // Софт-счёт — другой тариф, другая сумма к отправке
  const d2 = Object.assign({}, d, { ippsTariff: 'soft' });
  const e2 = ctx.econ(d2);
  approxEq(e2.sentUsd, 45725.00);
  assert.equal(e2.feePercent, 1.5);

  // Без инвойса — не готова, но не падает
  const e3 = ctx.econ({ type: 'Оплата недвижимости', kind: 'Фрихолд', rates: {}, agents: [] });
  assert.equal(e3.ready, false);
  assert.equal(e3.invoiceUsd, 0);
}

// ── Регресс: лизхолд считается как раньше (тот же фикстур, что в
//    test_stand_leasehold.js) — рефактор econ() не должен его тронуть ─────
{
  const ctx = run(['econ'], [], {
    payinParts: () => [{ usdt: 12000, calc: 11990, fact: 12000, kept: 0, ctrl: 0 }],
    mfList: x => x.mfPayout, mfSum: x => round2(x.mfPayout.reduce((s, t) => s + t.amount, 0)),
    hashSum: () => null, pcAmount: x => x.transfer.amount,
    refAgents: () => [], num: x => (x == null ? null : parseFloat(String(x).replace(',', '.'))),
    cleanNum: x => String(x).replace(/[^\d.,]/g, ''), Math,
  });
  const d = { type: 'Оплата недвижимости', kind: 'Лизхолд', amountThb: 350000,
    rates: { usdtThb: '31,20', broker: '81,40' }, postConv: 'coins', companyPct: 1,
    transfer: { amount: 11217.95, rate: '31,20', thb: 353500 },
    mfPayout: [{ hash: 'tx-a', amount: 7000 }, { hash: 'tx-b', amount: 4217.95 }],
    payout: {}, pay: { coinsCredit: { thb: 353000, ref: 'scb-1' } }, agents: [] };
  const e = ctx.econ(d);
  assert.equal(e.cost, 11217.95);
  assert.equal(e.sentThb, 353000);
  assert.equal(e.feeThb, 3000);
  approxEq(e.crypto, 782.05);
  assert.equal(e.ready, true);
  assert.equal(e.invoiceUsd, null, 'у лизхолда фрихолдовых полей нет');
}

// ── freeholdApprox()/approx(): рубли = X × курс, 4 знака, курс первичен ──
{
  const ctx = run(['approx', 'freeholdApprox', 'ippsTariff', 'freeholdFee', 'freeholdSend', 'isCrypto', 'payCur'],
    ['IPPS_TARIFFS'], {
      num: x => (x == null ? null : parseFloat(String(x).replace(',', '.'))),
      avgRate: () => 2.85, avgUsdt: () => 31.2,
    });
  const d = { type: 'Оплата недвижимости', kind: 'Фрихолд', invoiceUsd: 45000,
    ippsTariff: 'bank', payType: 'По реквизитам', rates: { client: '82.4531' } };
  const ap = ctx.approx(d);
  assert.equal(ap.thbSign, '$', 'получателю — доллары, не баты');
  approxEq(ap.thb, 45000);
  // Контрольный пример спеки §4.3: курс 82,4531 и X=45000 $ → рубли 3 710 389,50
  approxEq(ap.pay, 3710389.50);
  assert.equal(ap.sign, '₽');
  assert.equal(ap.cur, 'rub');

  // Без курса клиенту рубли не считаются, а не падают в approx() по батам
  const noRate = ctx.approx(Object.assign({}, d, { rates: {} }));
  assert.equal(noRate.pay, null);
  assert.equal(noRate.approx, 'pay');

  // Крипто-фрихолд: сумма клиенту = S + наценка, курса не спрашиваем вообще.
  // Наценка без дефолта (Карим, 28.09) — без неё сумма клиенту не считается.
  const dc = { type: 'Оплата недвижимости', kind: 'Фрихолд', invoiceUsd: 45000,
    ippsTariff: 'soft', payType: 'Крипта', curBase: 'usdt', rates: {}, freeholdMarkupPct: null };
  const apcNoMarkup = ctx.approx(dc);
  assert.equal(apcNoMarkup.cur, 'usdt'); assert.equal(apcNoMarkup.sign, 'USDT');
  approxEq(apcNoMarkup.thb, 45000);
  assert.equal(apcNoMarkup.pay, null, 'без наценки сумма клиенту не считается — нет дефолта');
  assert.equal(apcNoMarkup.approx, 'pay');

  const apc = ctx.approx(Object.assign({}, dc, { freeholdMarkupPct: 2 }));
  approxEq(apc.pay, 45725.00 * 1.02);
}

// ── apMoney(): формат суммы застройщику — $, не ฿ ────────────────────────
{
  const ctx = run(['apMoney'], [], { money: (v, c) => (v == null ? '—' : `${v} ${c}`) });
  const ap = { thb: 45000, thbSign: '$', pay: 3710389.5, sign: '₽', approx: null };
  assert.equal(ctx.apMoney(ap, 'thb'), '45000 $');
  assert.equal(ctx.apMoney(ap, 'pay'), '3710389.5 ₽');
  const leasehold = { thb: 350000, pay: 931000, sign: '₽', approx: null };
  assert.equal(ctx.apMoney(leasehold, 'thb'), '350000 ฿', 'без thbSign — как раньше, баты');
}

// ── ippsApplicationText(): формат заявки, Amount = X (не S), POBO только у софт-счёта ──
{
  const ctx = run(['ippsApplicationText', 'econ', 'ippsTariff', 'freeholdFee', 'freeholdSend'], ['IPPS_TARIFFS'], {
    payinParts: () => [], hashSum: () => null, pcAmount: () => null, refAgents: () => [],
    num: x => (x == null ? null : parseFloat(String(x).replace(',', '.'))),
    cleanNum: x => String(x).replace(/[^\d.,]/g, ''), mfList: () => [], Math,
  });
  const pt = { dev: 'Sansiri Public Co., Ltd.', bank: 'Kasikornbank', branch: 'Phuket',
    bankAddr: 'Bangkok', swift: 'KASITHBK', acc: '123-4-56789-0', purpose: 'Invoice INV-1, unit A101' };
  const dBank = { kind: 'Фрихолд', invoiceUsd: 45000, ippsTariff: 'bank', payTo: pt, rates: {}, agents: [] };
  const textBank = ctx.ippsApplicationText(dBank, pt);
  assert.ok(!textBank.includes('POBO'), 'у банковского тарифа POBO нет');
  assert.ok(textBank.includes('Amount: 45,000.00 USD'), 'Amount — это X, не S');
  assert.ok(textBank.includes('To: Sansiri Public Co., Ltd.'));
  assert.ok(textBank.includes('SWIFT: KASITHBK'));
  assert.ok(textBank.includes('Payment Description: Invoice INV-1, unit A101'));

  const dSoft = Object.assign({}, dBank, { ippsTariff: 'soft' });
  const textSoft = ctx.ippsApplicationText(dSoft, Object.assign({ pobo: 'IVANOV IVAN' }, pt));
  assert.ok(textSoft.startsWith('POBO: IVANOV IVAN'), 'POBO — первой строкой у софт-счёта');
}

// ── flowOf(): крипто-фрихолд без s5/s6; рублёвый фрихолд с s25 (IPPS) ────
{
  const ctx = run(['stepTitle'], ['STEPS'], {});
  assert.equal(ctx.stepTitle({step:'s25', kind:'Фрихолд', postConv:'ipps_swift'}),
    'Отправить заявку в IPPS');
  assert.equal(ctx.stepTitle({step:'s25', kind:'Лизхолд', postConv:'coins'}), 'Известить Coins');
}

{
  const ctx = run(['flowOf', 'isCrypto', 'payCur'], ['FLOW_RUB', 'FLOW_USDT', 'FLOW_ALIAS'], {
    dealWallet: () => null, needsSecondSign: () => true, SOURCES_PAY: {},
  });
  const cryptoFreehold = { type: 'Оплата недвижимости', kind: 'Фрихолд', payType: 'Крипта',
    curBase: 'usdt', step: 's8' };
  const F1 = ctx.flowOf(cryptoFreehold);
  assert.ok(!F1.includes('s5'), 'крипто-фрихолд: без «Ответить курс»');
  assert.ok(!F1.includes('s6'), 'крипто-фрихолд: без «Расчёт клиенту»');

  const rubFreehold = { type: 'Оплата недвижимости', kind: 'Фрихолд', payType: 'По реквизитам',
    step: 's22', postConv: 'ipps_swift' };
  const F2 = ctx.flowOf(rubFreehold);
  assert.ok(F2.includes('s5') && F2.includes('s6'), 'рублёвый фрихолд: курс всё равно спрашиваем у брокера');
  assert.ok(F2.includes('s25'), 'IPPS-маршрут — s25 в пути остаётся, это «Отправить заявку в IPPS»');

  // Регресс: лизхолд с postConv!=='coins' всё ещё теряет s25, как раньше
  const leaseKeep = { type: 'Оплата недвижимости', kind: 'Лизхолд', step: 's22', postConv: 'keep' };
  const F3 = ctx.flowOf(leaseKeep);
  assert.ok(!F3.includes('s25'), 'лизхолд без Coins — s25 всё ещё выпадает');
}

// ── crmPayload(): invoice_amount_usd = X, transfer_fee_percent = тариф сделки ──
{
  const ctx = run(['crmPayload', 'crmNet', 'ippsTariff', 'freeholdFee', 'freeholdSend'],
    ['IPPS_TARIFFS', 'PAYIN_CRM'], {
      econ: () => ({ payin: 45500, invoiceUsd: 45000 }),
      num: x => (x == null ? null : parseFloat(String(x).replace(',', '.'))),
      mfList: () => [], refById: () => null, isCrypto: () => false,
    });
  const d = { client: 'Freehold Client', type: 'Оплата недвижимости', kind: 'Фрихолд',
    invoiceUsd: 45000, ippsTariff: 'soft', payType: 'По реквизитам', rates: {},
    agents: [], object: 'Layan B12', payTo: {} };
  const p = ctx.crmPayload(d);
  assert.equal(p.deal_kind, 'mf_freehold');
  assert.equal(p.invoice_amount_usd, 45000);
  assert.equal(p.transfer_fee_percent, 1.5, 'тариф сделки — софт-счёт, не зашитые 0,8%');
  assert.equal(p.transfer_fee_fixed_usd, 50);
  approxEq(p.transfer_sent_usd, 45725.00);

  const dBank = Object.assign({}, d, { ippsTariff: 'bank' });
  const pBank = ctx.crmPayload(dBank);
  assert.equal(pBank.transfer_fee_percent, 0.8, 'банк — другой тариф той же сделки');

  // Регресс: лизхолд по-прежнему уходит в mf_realty, фрихолдовые поля не подмешиваются
  const lease = { client: 'Lease', type: 'Оплата недвижимости', kind: 'Лизхолд',
    amountThb: 350000, rates: { usdtThb: '31,20' }, agents: [], payTo: {}, companyPct: 1 };
  const pLease = ctx.crmPayload(lease);
  assert.equal(pLease.deal_kind, 'mf_realty');
  assert.equal(pLease.invoice_amount_usd, undefined);
}

// ── freeholdInvoiceSet(): правка инвойса/тарифа до договора (s6/s8) ─────
// Карим, 28.09: тариф ставится при заявке, правится до s11, дальше только
// чтение (сама блокировка на s11 — в UI, readonly-инпут, здесь не тестируется).
// Если курс клиенту уже назван, смена задним числом пишет в журнал разницу
// по S, но не блокирует и не откатывает правку.
{
  const logged = [];
  const d = { id: 1, kind: 'Фрихолд', invoiceUsd: 45000, ippsTariff: 'bank', rates: {} };
  const ctx = run(['freeholdInvoiceSet', 'ippsTariff', 'freeholdFee', 'freeholdSend'], ['IPPS_TARIFFS'], {
    num: x => (x == null ? null : parseFloat(String(x).replace(',', '.'))),
    cleanNum: x => String(x).replace(/[^\d.,]/g, ''), usd: x => `$${x}`,
    toast: () => {}, save: () => {}, render: () => {},
    log: (dd, t) => logged.push(t),
    deal: () => d, isCrypto: () => false,
  });

  // Правка до курса клиенту — тихая, без предупреждения
  ctx.freeholdInvoiceSet(1, 'invoiceUsd', '40000');
  assert.equal(d.invoiceUsd, 40000);
  assert.equal(logged.length, 0, 'курса клиенту ещё нет — предупреждать не о чем');

  // Курс назвали, потом сменили тариф — предупреждение и запись в журнал обязательны
  d.rates.client = '82,4531';
  logged.length = 0;
  ctx.freeholdInvoiceSet(1, 'ippsTariff', 'soft');
  assert.equal(d.ippsTariff, 'soft');
  assert.equal(logged.length, 1, 'смена тарифа после курса клиенту пишется в журнал');
  assert.ok(/маржа сдвинулась/.test(logged[0]));

  // Инвойс <= 0 отклоняется, прежнее значение остаётся
  ctx.freeholdInvoiceSet(1, 'invoiceUsd', '0');
  assert.equal(d.invoiceUsd, 40000, 'нулевой инвойс не принимается');
}

// ── draftValid()/draftAmounts(): наценка крипто-фрихолда обязательна на заявке ──
{
  const toasts = [];
  const ctx = run(['draftValid', 'draftAmounts'], [], {
    toast: t => toasts.push(t),
    num: x => (x == null || x === '' ? null : parseFloat(String(x).replace(',', '.'))),
    cleanNum: x => String(x).replace(/[^\d.,]/g, ''),
  });
  const D = { clientId: 1, type: 'Оплата недвижимости', kind: 'Фрихолд', payType: 'Крипта',
    sum: '45000', cur: 'fhusd', ippsTariff: 'bank', freeholdMarkupPct: null };
  ctx.S = { draft: D };
  assert.equal(ctx.draftValid(), false, 'без наценки заявку на крипто-фрихолд не создать');
  assert.ok(toasts.some(t => t.includes('наценку')));

  D.freeholdMarkupPct = 2;
  assert.equal(ctx.draftValid(), true);
  const amounts = ctx.draftAmounts(D);
  assert.equal(amounts.freeholdMarkupPct, 2);
  assert.equal(amounts.invoiceUsd, 45000);

  // Рублёвый фрихолд наценку не спрашивает вообще
  ctx.S.draft = Object.assign({}, D, { payType: 'По реквизитам', freeholdMarkupPct: null });
  assert.equal(ctx.draftValid(), true, 'у рублёвого фрихолда наценки нет — не блокирует');
}

// ── syncFreeholdRate(): курс клиенту — ровно 4 знака, округление, не отказ ──
// QA №4/№5, 28.09: 82.45319 округляется до 82,4531 (4 знака), а не отклоняется —
// курс называют голосом/в переписке, лишний знак — не ошибка менеджера.
{
  const inputs = {};
  const d = { id: 1, invoiceUsd: 45000, rates: {} };
  const ctx = run(['syncFreeholdRate'], [], {
    deal: () => d, val: k => inputs[k] || '',
    cleanNum: x => String(x).replace(/[^\d.,]/g, ''),
    num: x => (x == null || x === '' ? null : parseFloat(String(x).replace(',', '.'))),
    save: () => {}, render: () => {},
  });
  inputs.r3 = '82.4531';
  ctx.syncFreeholdRate(1);
  assert.equal(d.rates.client, '82,4531');
  // Контрольный пример спеки §4.3: 82,4531 × 45000 = 3 710 389,50
  approxEq(d.amountRub, 3710389.50);

  inputs.r3 = '82.45319';
  ctx.syncFreeholdRate(1);
  assert.equal(d.rates.client, '82,4532', 'округлено до 4 знаков (9 на пятом → вверх), не отклонено');

  inputs.r3 = '82.453149';
  ctx.syncFreeholdRate(1);
  assert.equal(d.rates.client, '82,4531', 'округление вниз на пятом знаке');

  inputs.r3 = '82.453151';
  ctx.syncFreeholdRate(1);
  assert.equal(d.rates.client, '82,4532', 'округление вверх на пятом знаке (0,5 в большую сторону)');
}

// ── Инвойс застройщика в THB (Карим, 28.09): переключатель на заявке ────
// Сделка всё равно считается от X — суммы в USD, подтверждённой застройщиком;
// сумма в ฿ только хранится (не идёт в CRM — для неё там нет поля).
{
  const toasts = [];
  const ctx = run(['draftValid', 'draftAmounts'], [], {
    toast: t => toasts.push(t),
    num: x => (x == null || x === '' ? null : parseFloat(String(x).replace(',', '.'))),
    cleanNum: x => String(x).replace(/[^\d.,]/g, ''),
  });
  const D = { clientId: 1, type: 'Оплата недвижимости', kind: 'Фрихолд', payType: 'По реквизитам',
    sum: '45000', cur: 'fhusd', ippsTariff: 'bank', invoiceCurrency: 'thb', invoiceThbAmount: '' };
  ctx.S = { draft: D };

  toasts.length = 0;
  assert.equal(ctx.draftValid(), false, 'в режиме THB без суммы в ฿ заявку не создать');
  assert.ok(toasts.some(t => t.includes('฿')));

  D.invoiceThbAmount = '1500000';
  assert.equal(ctx.draftValid(), true);
  const amounts = ctx.draftAmounts(D);
  assert.equal(amounts.invoiceUsd, 45000, 'X = подтверждённая сумма в USD, а не в ฿');
  assert.equal(amounts.invoiceCurrency, 'thb');
  assert.equal(amounts.invoiceThb, 1500000, 'сумма в ฿ хранится отдельно');

  // Режим USD (по умолчанию) — поле ฿ не требуется вообще
  const D2 = Object.assign({}, D, { invoiceCurrency: 'usd', invoiceThbAmount: '' });
  ctx.S.draft = D2;
  assert.equal(ctx.draftValid(), true, 'при USD-инвойсе поле ฿ не обязательно');
  const amounts2 = ctx.draftAmounts(D2);
  assert.equal(amounts2.invoiceCurrency, 'usd');
  assert.equal(amounts2.invoiceThb, null, 'при USD-инвойсе сумма в ฿ не хранится');
}

// ── freeholdInvoiceSet(): переключатель валюты инвойса правится до s11 ──
{
  const d = { id: 1, kind: 'Фрихолд', invoiceUsd: 45000, ippsTariff: 'bank', rates: {},
    invoiceCurrency: 'usd', invoiceThb: null };
  const ctx = run(['freeholdInvoiceSet', 'ippsTariff', 'freeholdFee', 'freeholdSend'], ['IPPS_TARIFFS'], {
    num: x => (x == null ? null : parseFloat(String(x).replace(',', '.'))),
    cleanNum: x => String(x).replace(/[^\d.,]/g, ''), usd: x => `$${x}`,
    toast: () => {}, save: () => {}, render: () => {}, log: () => {},
    deal: () => d, isCrypto: () => false,
  });

  ctx.freeholdInvoiceSet(1, 'invoiceCurrency', 'thb');
  assert.equal(d.invoiceCurrency, 'thb');
  assert.equal(d.invoiceUsd, 45000, 'переключение валюты инвойса не трогает X');

  ctx.freeholdInvoiceSet(1, 'invoiceThb', '1500000');
  assert.equal(d.invoiceThb, 1500000);
  assert.equal(d.invoiceUsd, 45000, 'сумма в ฿ не влияет на X — X ведёт всю сделку');

  ctx.freeholdInvoiceSet(1, 'invoiceCurrency', 'usd');
  assert.equal(d.invoiceCurrency, 'usd');
}

console.log('test_stand_freehold.js: OK');
