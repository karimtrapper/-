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
function divTree(markup) {
  const root={tag:'root',classes:[],children:[]}, stack=[root];
  for(let i=0;i<markup.length;){
    if(markup[i]!=='<'){i++;continue;}
    let j=i+1,quote=null;
    for(;j<markup.length;j++){
      const ch=markup[j];
      if(quote){if(ch===quote)quote=null;}
      else if(ch==='"'||ch==="'")quote=ch;
      else if(ch==='>')break;
    }
    if(j===markup.length)throw new Error('unterminated HTML tag');
    const tag=markup.slice(i,j+1);
    if(/^<div\b/i.test(tag)){
      const match=tag.match(/\bclass\s*=\s*(["'])(.*?)\1/i);
      const node={tag:'div',classes:match?match[2].split(/\s+/).filter(Boolean):[],children:[]};
      stack.at(-1).children.push(node);stack.push(node);
    }else if(/^<\/div\s*>/i.test(tag)){
      if(stack.length===1)throw new Error('closing div without an open parent');
      stack.pop();
    }
    i=j+1;
  }
  if(stack.length!==1)throw new Error(`${stack.length-1} unclosed div wrapper(s)`);
  return root;
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
    isCrypto: () => false,
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
    isCrypto: () => false,
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

  // Крипто-фрихолд: сумма клиента вводится явно, курс не нужен.
  const dc = { type: 'Оплата недвижимости', kind: 'Фрихолд', invoiceUsd: 45000,
    ippsTariff: 'soft', payType: 'Крипта', curBase: 'usdt', rates: {}, amountUsdt: null,
    freeholdMarkupPct: 100475 };
  const absent = ctx.approx(dc);
  assert.equal(absent.pay, null, 'старый процент не становится суммой клиента');
  const apc = ctx.approx(Object.assign({}, dc, { amountUsdt: 46000 }));
  approxEq(apc.pay, 46000);
  assert.equal(apc.cur, 'usdt'); assert.equal(apc.sign, 'USDT');
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
    isCrypto: () => false,
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
      payinParts: () => [{usdt: 45500}],
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

// ── draftValid()/draftAmounts(): план обязателен до создания сделки ──
{
  const toasts = [];
  const ctx = run(['draftValid', 'draftAmounts'], [], {
    toast: t => toasts.push(t),
    num: x => (x == null || x === '' ? null : parseFloat(String(x).replace(',', '.'))),
    cleanNum: x => String(x).replace(/[^\d.,]/g, ''),
  });
  const D = { clientId: 1, type: 'Оплата недвижимости', kind: 'Фрихолд', payType: 'Крипта',
    sum: '45000', cur: 'fhusd', ippsTariff: 'bank', amountUsdt: null };
  ctx.S = { draft: D };
  assert.equal(ctx.draftValid(), false, 'положительная сумма нужна перед созданием');
  assert.equal(ctx.draftAmounts(D).amountUsdt, null);

  D.amountUsdt = '46000';
  assert.equal(ctx.draftValid(), true);
  const amounts = ctx.draftAmounts(D);
  assert.equal(amounts.amountUsdt, 46000);
  assert.equal(amounts.freeholdMarkupPct, undefined);
  assert.equal(amounts.invoiceUsd, 45000);

  ctx.S.draft = Object.assign({}, D, { payType: 'По реквизитам' });
  assert.equal(ctx.draftValid(), true, 'рублёвый фрихолд не меняется');
  assert.equal(ctx.draftAmounts(ctx.S.draft).amountUsdt, null);
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

// Direct crypto-freehold amount: X=97500, bank S=98330, plan=98800, income=470.
{
  const d={id:9101,type:'Оплата недвижимости',kind:'Фрихолд',payType:'Крипта',
    curBase:'fhusd',invoiceUsd:97500,ippsTariff:'bank',amountUsdt:98800,rates:{},
    invoiceCurrency:'usd'};
  const ctx=run(['freeholdInvoiceTariffBlock','freeholdInvoiceSet','freeholdLossFingerprint','draftFreeholdPreview',
    'freeholdApprox','ippsTariff','freeholdFee','freeholdSend'],['IPPS_TARIFFS'],{
    isCrypto:()=>true,deal:()=>d,save:()=>{},render:()=>{},log:()=>{},toast:()=>{},
    usd:x=>`${Number(x).toFixed(2)} USDT`,num:x=>x==null||x===''?null:Number(String(x).replace(',','.')),
    money:(x,c)=>`${Number(x).toFixed(2)} ${c}`,
    cleanNum:x=>String(x).replace(/[\s\u00a0]/g,'').replace(',','.'),
  });
  assert.equal(ctx.freeholdSend(97500,ctx.IPPS_TARIFFS.bank),98330);
  assert.equal(ctx.freeholdApprox(d).pay,98800);
  let html=ctx.freeholdInvoiceTariffBlock(d);
  assert.ok(html.includes('Клиент отправит, USDT'));
  assert.ok(html.includes('В IPPS уйдёт, USDT'));
  assert.ok(html.includes('Сумму клиента, USDT, операционист может уточнить'));
  assert.ok(html.includes('470.00'));
  assert.ok(!html.includes('Сделка в минус'));
  assert.ok(!html.includes('fh_mk_'));
  assert.ok(ctx.draftFreeholdPreview({sum:'97500',ippsTariff:'bank',payType:'Крипта',amountUsdt:'98800'}).includes('470.00'));
  ctx.freeholdInvoiceSet(9101,'ippsTariff','soft');
  assert.equal(d.amountUsdt,98800,'смена тарифа не меняет введённую сумму');
  assert.equal(ctx.freeholdSend(97500,ctx.IPPS_TARIFFS.soft),99012.5);
  html=ctx.freeholdInvoiceTariffBlock(d);
  assert.ok(html.includes('Сделка в минус'));
  assert.ok(html.includes('-212.50'));
  // Legacy percent cannot make 98.9m the planned contract amount.
  d.freeholdMarkupPct=100475;
  d.amountUsdt=null;
  assert.equal(ctx.freeholdApprox(d).pay,null);
  assert.ok(ctx.freeholdInvoiceTariffBlock(d).includes('сумму клиента нужно ввести явно'));
}

// CRM Pay-In is the verified hash fact, while the planned contract amount stays 98800.
{
  const ctx=run(['crmPayload','crmNet','ippsTariff','freeholdFee','freeholdSend'],
    ['IPPS_TARIFFS','PAYIN_CRM'],{
      econ:()=>({payin:98799.5,invoiceUsd:97500}),
      payinParts:()=>[{usdt:98799.5,fact:98799.5}],
      num:x=>x==null?null:Number(x),mfList:()=>[],refById:()=>null,isCrypto:()=>true,
    });
  const d={client:'Synthetic',type:'Оплата недвижимости',kind:'Фрихолд',payType:'Крипта',
    amountUsdt:98800,invoiceUsd:97500,ippsTariff:'bank',rates:{},agents:[],payTo:{},
    payinHashes:[{hash:'a'.repeat(64),network:'TRC20',amount:98799.5,verified:true}]};
  const p=ctx.crmPayload(d);
  assert.equal(p.payin_amount_usdt,98799.5);
  assert.equal(p.invoice_amount_usd,97500);
  assert.equal(p.transfer_sent_usd,98330);
}

// New-deal form: one direct crypto action, live economics, and safe payType toggling.
{
  const D={source:'none',sourceRef:'',client:'Synthetic',clientId:null,cq:'',type:'Оплата недвижимости',
    kind:'Фрихолд',payType:'Крипта',mode:'need',cur:'fhusd',sum:'97500',ippsTariff:'bank',
    invoiceCurrency:'usd',amountUsdt:'98800',agents:[],rq:'',note:''};
  let rendered='';
  const ctx=run(['viewCreateBody','draftSet','draftFreeholdPreview','draftValid','draftAmounts',
    'freeholdSend','freeholdFee','askModes','ippsTariff','pairOf'],['IPPS_TARIFFS','PAIRS','PAIR_PAYCUR'],{
    STAND:true,S:{draft:D},SOURCES:{none:'Без переписки'},clientFind:()=>[],clientById:()=>null,
    payWays:()=>['Крипта','По реквизитам'],draftAgentsBlock:()=>'',refFind:()=>[],
    htmlText:s=>String(s||''),
    save:()=>{},render:()=>{rendered=ctx.viewCreateBody(D,'');},toast:()=>{},
    usd:x=>Number(x).toFixed(2),num:x=>x==null||x===''?null:Number(String(x).replace(',','.')),
    money:(x,c)=>`${Number(x).toFixed(2)} ${c}`,
    cleanNum:x=>String(x).replace(/[\s\u00a0]/g,'').replace(',','.'),
  });
  rendered=ctx.viewCreateBody(D,'');
  assert.ok(rendered.includes('Клиент отправит, USDT'));
  assert.ok(rendered.includes('98330.00'));
  assert.ok(rendered.includes('470.00'));
  assert.ok(rendered.includes('Наш доход 470.00 USDT'));
  assert.ok(!rendered.includes('посчитаем после курса'));
  assert.equal((rendered.match(/onclick="createGo\(\)"/g)||[]).length,1);
  assert.ok(rendered.includes('>Создать сделку</button>'));
  assert.ok(!rendered.includes('Создать заявку — курс спросит операционист'));
  assert.ok(!rendered.includes('Курс знаю — сам'));
  assert.ok(!rendered.includes('посчитаем после курса'));
  assert.match(rendered,/class="cols cols-create-compact"/);
  assert.ok(!rendered.includes('class="card side"'));
  assert.ok(rendered.includes('Далее: загрузить паспорт и инвойс → передать Насте'));
  assert.ok(rendered.includes('>Создать сделку</button>'));
  // The real tasks.html template keeps other flows in the two-column layout.
  const otherFlow=ctx.viewCreateBody(Object.assign({},D,{payType:'По реквизитам'}),'');
  assert.match(otherFlow,/class="cols"/);
  assert.ok(!otherFlow.includes('cols-create-compact'));
  assert.ok(otherFlow.includes('class="card side"'));
  assert.match(html,/\.cols\.cols-create-compact\{grid-template-columns:minmax\(0,1fr\)\}/);
  assert.match(html,/\.fh\.create-next\{font-size:12\.5px;line-height:1\.4;color:var\(--navy-600\)/);
  assert.match(html,/@media\(max-width:900px\)\{\.cols\{grid-template-columns:1fr\}/);
  const variants=[
    {type:'Оплата недвижимости',kind:'Фрихолд',payType:'Крипта',compact:true},
    {type:'Оплата недвижимости',kind:'Фрихолд',payType:'По реквизитам'},
    {type:'Оплата недвижимости',kind:'Лизхолд',payType:'По реквизитам'},
    {type:'Обмен валюты',kind:'',payType:'Крипта'}
  ];
  const desktopColumns=html.match(/\.cols\{display:grid;grid-template-columns:([^;]+);/)[1];
  for(const viewport of [1280,390]){
    for(const variant of variants){
      const markup=ctx.viewCreateBody(Object.assign({},D,variant),'');
      const root=divTree(markup);
      const find=(node,predicate)=>[...(predicate(node)?[node]:[]),...node.children.flatMap(x=>find(x,predicate))];
      const grid=find(root,node=>node.classes.includes('cols'))[0];
      assert.ok(grid,`${variant.type}/${variant.kind}/${variant.payType}: missing grid`);
      const left=grid.children[0];
      assert.ok(left,`${variant.type}/${variant.kind}: missing left column`);
      if(variant.compact){
        assert.ok(grid.classes.includes('cols-create-compact'));
        assert.equal(grid.children.length,1,'crypto freehold has no side card or empty grid column');
        assert.ok(!find(left,node=>node.classes.includes('side')).length);
      }else{
        assert.equal(grid.children.length,2,'side card is the second grid sibling');
        assert.ok(grid.children[1].classes.includes('side'));
        assert.ok(!find(left,node=>node.classes.includes('side')).length);
      }
      const columns=grid.classes.includes('cols-create-compact')?'minmax(0,1fr)':
        (viewport<=900?'1fr':desktopColumns);
      assert.equal(columns,variant.compact?'minmax(0,1fr)':(viewport<=900?'1fr':'1fr 310px'));
    }
  }
  assert.equal(ctx.draftValid(),true);
  ctx.draftSet('payType','По реквизитам');
  assert.equal(D.sum,'97500');assert.equal(D.ippsTariff,'bank');
  assert.ok(rendered.includes('Создать заявку — курс спросит операционист'));
  assert.ok(rendered.includes('Курс знаю — сам'));
  assert.ok(!rendered.includes('id="d_amount_usdt"'));
  assert.equal(ctx.draftAmounts(D).amountUsdt,null);
  ctx.draftSet('payType','Крипта');
  assert.equal(D.sum,'97500');assert.equal(D.ippsTariff,'bank');
  assert.equal(D.amountUsdt,'98800');
  assert.ok(rendered.includes('>Создать сделку</button>'));
  assert.equal((rendered.match(/onclick="createGo\(\)"/g)||[]).length,1);
  D.amountUsdt='98000';
  assert.ok(ctx.draftFreeholdPreview(D).includes('Сделка в минус'));
}

// New crypto-freehold action starts at documents, preserving the direct plan.
{
  const D={clientId:1,client:'Synthetic',type:'Оплата недвижимости',kind:'Фрихолд',
    payType:'Крипта',cur:'fhusd',sum:'97500',ippsTariff:'bank',amountUsdt:'98800'};
  let created;
  const ctx=run(['createGo','draftValid','draftAmounts'],[],{
    S:{draft:D},ensureClient:()=>{},clientById:()=>({docs:false}),
    newDeal:o=>(created={...o,id:9101}),log:()=>{},save:()=>{},render:()=>{},toast:()=>{},
    num:x=>x==null||x===''?null:Number(String(x).replace(',','.')),
    cleanNum:x=>String(x).replace(/[\s\u00a0]/g,'').replace(',','.'),
  });
  ctx.createGo();
  assert.equal(created.step,'s8');
  assert.equal(created.amountUsdt,98800);
  assert.equal(created.invoiceUsd,97500);
  assert.equal(created.ippsTariff,'bank');
}

// The read-only clause previews the next issued crypto-freehold appendix.
{
  const approved='Вознаграждение агента включено в сумму платежа, отдельно не взимается / The Agent’s fee is included in the payment amount and is not charged separately';
  const old='Комиссия включена в курс, отдельно не взимается';
  const d={kind:'Фрихолд',payType:'Крипта',amountUsdt:98800,code:'SYN',rates:{},docFields:null};
  const ctx=run(['docFields'],[],{fake:()=>({}),approx:()=>({thb:97500,pay:98800}),
    prevPassport:()=>({}),parsed:()=>'',isCrypto:x=>x.payType==='Крипта',
    MF:{name:'MF',reg:'1',dir:'Director'},payToCrypto:()=>'',payinWallet:()=>null});
  assert.equal(ctx.docFields(d).feeNote,approved);
  d.docFields={feeNote:old};
  assert.equal(ctx.docFields(d).feeNote,approved,'unissued saved old default is replaced');
  d.docFields={feeNote:'Индивидуальная оговорка клиента'};
  assert.equal(ctx.docFields(d).feeNote,approved);
  const saveCtx=run(['docFieldSave'],['DOC_SRC'],{deal:()=>d,docFields:()=>ctx.docFields(d),
    document:{getElementById:()=>null}});
  saveCtx.docFieldSave(9101);
  assert.equal(d.docFields.feeNote,approved,
    'hidden s11 field must use the legal clause for the next issue');
  d.docFields={feeNote:old};d.docPack={version:1};d.docVersion=1;
  assert.equal(ctx.docFields(d).feeNote,approved,'reissue preview uses the legal clause');
  assert.equal(d.docFields.feeNote,old,'reading does not mutate an issued package');
  d.docPack=null;d.docVersion=0;d.payType='По реквизитам';d.docFields=null;
  assert.equal(ctx.docFields(d).feeNote,old,'RUB freehold keeps previous default');
  d.kind='Лизхолд';d.payType='Крипта';
  assert.equal(ctx.docFields(d).feeNote,old,'crypto leasehold keeps previous default');
}

// Executable s11 template: legacy percent-only deal has no invented loss,
// and the amount field is editable before the first document package.
{
  const start=html.indexOf('  s11:()=>{');
  const end=html.indexOf('\n  s11b:()=>{',start);
  assert.ok(start>0&&end>start);
  const s11='var renderS11='+html.slice(start+'  s11:'.length,end).trim().replace(/,$/,';');
  const d={id:9101,kind:'Фрихолд',payType:'Крипта',invoiceUsd:97500,
    ippsTariff:'bank',amountUsdt:null,freeholdMarkupPct:100475,docs:{},docMiss:[]};
  const ctx={d,ap:{sign:'USDT'},S:{},DOC_SRC:{},DOC_LABEL:{},
    docFields:()=>({amountPay:d.amountUsdt==null?'':String(d.amountUsdt),amountThb:'97500',
      feeNote:'Вознаграждение агента включено в сумму платежа, отдельно не взимается / The Agent’s fee is included in the payment amount and is not charged separately'}),
    docParseLine:()=>'',isCrypto:x=>x.payType==='Крипта',ippsTariff:()=>({percent:0.8,fixed:50}),
    usd:x=>String(x),num:x=>x==null||x===''?null:Number(x),cleanNum:x=>String(x).replace(/\s/g,''),
    docReq:()=>[],fioHint:()=>'',payinWalletSelect:()=>'',htmlText:x=>String(x),
    money:(x,c)=>`${Number(x).toFixed(2)} ${c}`};
  vm.createContext(ctx);
  vm.runInContext(functions(['freeholdFee','freeholdSend','freeholdLossFingerprint','payinS11Fields'])+'\n'+s11,ctx);
  let rendered=ctx.renderS11();
  assert.match(rendered,/id="df_amountPay"[^>]*onchange="freeholdDocAmountSave/);
  assert.match(rendered,/Курс сделки<\/label><input class="fc" readonly value="—"/);
  assert.match(rendered,/В IPPS уйдёт, USDT/);
  assert.match(rendered,/Наш доход, USDT/);
  assert.match(rendered,/ГЛАВНОЕ · СУММА<\/div>/);
  assert.doesNotMatch(rendered,/ГЛАВНОЕ · СУММА И КУРС|Курс зафиксирован|id="df_rateAt"/);
  assert.match(rendered,/Оговорка о комиссии в приложении: Вознаграждение агента включено в сумму платежа, отдельно не взимается \/ The Agent’s fee is included in the payment amount and is not charged separately/);
  assert.doesNotMatch(rendered,/id="df_feeNote"|<textarea[^>]*id="df_feeNote"/);
  assert.match(rendered,/Укажите сумму клиента/);
  assert.doesNotMatch(rendered,/Сделка в минус|Подтвердить сделку в минус|-98330\.00/);
  d.amountUsdt=98800;
  rendered=ctx.renderS11();
  assert.match(rendered,/value="470\.00"/);
  assert.match(rendered,/id="df_amountPay"[^>]*value="98 ?800"|id="df_amountPay"[^>]*value="98 800"/);
  d.payType='По реквизитам';
  rendered=ctx.renderS11();
  assert.match(rendered,/ГЛАВНОЕ · СУММА И КУРС/);
  assert.match(rendered,/Курс зафиксирован|id="df_rateAt"/);
  assert.doesNotMatch(rendered,/id="df_feeNote"|<textarea[^>]*id="df_feeNote"/);
}

// Manager card shows the saved plan and verified fact, without rate promises.
{
  const d={id:9101,client:'Synthetic',type:'Оплата недвижимости',kind:'Фрихолд',
    payType:'Крипта',amountUsdt:98800,rates:{},docs:{},log:[],pay:{},payout:{},
    step:'s11',source:'test'};
  const ctx=run(['overview','money'],[],{S:{role:'manager'},ROLES:{},SOURCES:{test:'Тест'},
    approx:()=>({thb:97500,pay:98800,sign:'USDT',thbSign:'$'}),
    fake:()=>({}),econ:()=>({parts:[{fact:98799.5}],ready:false,multi:false,payin:98799.5}),
    docListRows:()=>({issued:[],client:[]}),isCrypto:x=>x.payType==='Крипта',
    apMoney:(ap,k)=>k==='pay'?ap.pay+' USDT':ap.thb+' $',
    usd:v=>'$'+v,stepTitle:()=>'',refSignal:()=>null,
    cnvRow:()=>'',fillNote:()=>'',fixCard:()=>'',signedBlock:()=>''});
  const rendered=ctx.overview(d,{},true,{i:1,n:10},'manager').replace(/\u00a0/g,' ');
  assert.match(rendered,/Клиент отправит<\/th><td>98800 USDT/);
  assert.match(rendered,/План клиента<\/th><td>98 800 USDT/);
  assert.match(rendered,/Фактически пришло<\/th><td>98 799,5 USDT/);
  assert.doesNotMatch(rendered,/План клиента<\/th><td>\$|Фактически пришло<\/th><td>\$/);
  assert.match(rendered,/Фактическую прибыль покажем после подтверждения прихода USDT по хешам/);
  assert.doesNotMatch(rendered,/курс партнёра USDT→THB и приход/);
  assert.doesNotMatch(rendered,/Курс клиенту — ещё не проставлен|суммы подтверждены курсом|98895397/);
  d.payType='По реквизитам';
  const rub=ctx.overview(d,{},true,{i:1,n:10},'manager');
  assert.match(rub,/курс партнёра USDT→THB и приход/);
}

// Payin s11 — выпадающий список из реестра CRM, легаси walletId 'grusha'
// резолвится через тот же адрес и выбирает тот же <option> (wallet-registry).
{
  const addr='TKkeEVf2zySaWTLyX2qPwvi6kcdHRuPxkJ';
  const ctx=run(['payinWalletSelect','crmPayinChoices','payinWallet','payinWalletView',
    'payinDefaultWallet','crmWalletNet','crmWalletById','payinNet','payinCanRemember','addrValid'],
    ['ADDR_RE','LEGACY_PAYIN_ADDR','PAYIN_OWNERS'],
    {S:{},CRM_WALLETS:[{id:1,address:addr,blockchain:'TRON',owner:'компания',
      is_multisig:true,accepts_payin:true,label:'Груша'}],htmlText:x=>String(x)});
  const choices=ctx.crmPayinChoices('TRC-20');
  assert.equal(choices.length,1);
  assert.equal(choices[0].id,1);
  const rendered=ctx.payinWalletSelect({id:9101,step:'s11',walletId:'grusha'},false);
  assert.equal((rendered.match(/<option value="1"/g)||[]).length,1);
  assert.match(rendered,/<option value="1"[^>]* selected/);
  assert.doesNotMatch(rendered,/value="vitaly"/);
}

// Click-equivalent s11 issue: board PUT with the edited amount precedes docs POST.
(async()=>{
  const d={id:9101,kind:'Фрихолд',payType:'Крипта',amountUsdt:98800,rates:{},docVersion:0};
  const events=[];
  const ctx=run([],[],{STAND:true,S:{docIssuing:null},standBusy:false,standPush:false,
    standVer:17,standBase:{deals:[{id:9101,amountUsdt:98800}]},
    deal:()=>d,isCrypto:()=>true,
    standWaitSaved:async()=>events.push('wait'),
    standSave:async()=>{events.push('put');ctx.standBase={deals:[{id:9101,amountUsdt:d.amountUsdt}]};ctx.standVer=18;},
    fetch:async()=>{events.push('docs');return {status:200,json:async()=>({success:true,version:19,data:{deals:[d]}})};},
    standApply:()=>{},render:()=>{},toast:()=>{},save:()=>{},log:()=>{},
    go:()=>events.push('next'),num:x=>Number(x),cleanNum:x=>String(x).replace(/\s/g,'')});
  const docIssueSource=html.match(/^async function docIssue\([^]*?^}/m);
  assert.ok(docIssueSource);
  vm.runInContext(docIssueSource[0],ctx);
  await ctx.docIssue(9101,{amountPay:'98900',amountThb:'97500',rate:''},[],'');
  assert.equal(d.amountUsdt,98900);
  assert.ok(events.indexOf('put')<events.indexOf('docs'));
  assert.ok(events.includes('next'));
  events.length=0;
  d.amountUsdt=98800;
  ctx.standBase={deals:[{id:9101,amountUsdt:98800}]};
  ctx.standSave=async()=>{events.push('denied-put');};
  await ctx.docIssue(9101,{amountPay:'98900'},[],'');
  assert.ok(events.includes('denied-put'));
  assert.ok(!events.includes('docs'),'refused board save must prevent document issuance');
})().catch(e=>{console.error(e);process.exitCode=1;});
