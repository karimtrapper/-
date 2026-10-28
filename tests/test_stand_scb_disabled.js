// SCB временно выключен (Imperva режет серверные IP Railway) — чип неактивен,
// не участвует в выборе/усреднении курса, рядом «?»-подсказка и ссылка на банк.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../static/stand/tasks.html'), 'utf8');

function func(name) {
  const oneLine = html.match(new RegExp(`^(?:async )?function ${name}\\([^\\n]*\\)\\{[^\\n]*\\}$`, 'm'));
  if (oneLine) return oneLine[0];
  const found = html.match(new RegExp(`^(?:async )?function ${name}\\([^]*?^}`, 'm'));
  assert.ok(found, `Функция ${name} отсутствует`);
  return found[0];
}
function konst(name) {
  const found = html.match(new RegExp(`^const ${name}\\s*=[\\s\\S]*?;`, 'm'));
  assert.ok(found, `Константа ${name} отсутствует`);
  return found[0].replace(/^const /, 'var ');
}

function makeCtx(disabled) {
  const ctx = { S: { thbRates: { disabled } } };
  vm.createContext(ctx);
  const src = [
    konst('THB_REFERENCE_BANKS'),
    konst('BANK_RATE_SOURCE_URL'),
    func('htmlText'),
    func('disabledBanks'),
    func('activeBanks'),
    func('disabledBankRows'),
    func('thbBankRate'),
  ].join('\n');
  vm.runInContext(src, ctx);
  return ctx;
}

// activeBanks() исключает выключенный банк, не трогая список для будущего включения.
{
  const ctx = makeCtx(['SCB']);
  assert.equal(JSON.stringify(ctx.activeBanks()), JSON.stringify(['Kasikornbank', 'Bangkok Bank']));
  assert.equal(JSON.stringify(ctx.THB_REFERENCE_BANKS), JSON.stringify(['Kasikornbank', 'SCB', 'Bangkok Bank']));
}

// Строка выключенного банка: приглушённый чип без цифры, подсказка (title + onclick=toast
// для тапа на мобильном) с точным текстом, видимая ссылка target=_blank rel=noopener.
{
  const ctx = makeCtx(['SCB']);
  const row = ctx.disabledBankRows();
  assert.match(row, /SCB\s*—/);
  assert.match(row, /cursor:not-allowed/);
  assert.ok(!/onclick="freeholdDealSet|onclick="draftSet/.test(row), 'выключенный чип не выбирается');
  assert.match(row, /title="Курс SCB сейчас не обновляется автоматически\. Посмотрите его на сайте банка\."/);
  assert.match(row, /onclick="toast\(/);
  assert.match(row, /cursor:help/);
  assert.match(
    row,
    /<a href="https:\/\/www\.scb\.co\.th\/en\/personal-banking\/foreign-exchange-rates" target="_blank" rel="noopener"[^>]*>Курсы SCB<\/a>/
  );
}

// Ничего не выключено — disabledBankRows() пуст, строка не рисуется.
{
  const ctx = makeCtx([]);
  assert.equal(ctx.disabledBankRows(), '');
}

// thbBankRate: «Другой банк»/«Не знаю» считаются по активным банкам (без SCB),
// выключенный банк не обязателен и не участвует в усреднении/минимуме.
{
  const ctx = makeCtx(['SCB']);
  const rates = { Kasikornbank: 33, 'Bangkok Bank': 35 };
  assert.equal(ctx.thbBankRate(rates, 'Другой банк'), 34);
  assert.equal(ctx.thbBankRate(rates, 'Не знаю'), 33);
  assert.equal(ctx.thbBankRate(rates, 'SCB'), null, 'SCB нельзя выбрать напрямую, если его нет в rates');
}

// Регрессия: когда ничего не выключено, старое поведение («все три нужны») сохраняется.
{
  const ctx = makeCtx([]);
  const rates = { Kasikornbank: 33, 'Bangkok Bank': 35 }; // SCB отсутствует
  assert.equal(ctx.thbBankRate(rates, 'Другой банк'), null);
}

console.log('test_stand_scb_disabled.js: OK');
