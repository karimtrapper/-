// Задачник стенда не должен содержать боевых Telegram-ссылок на брокеров/Coins,
// боевого бота рефералов и прод-домен калькулятора (Карим, 27.09 — T7).
// Допустимы подсказки, нормализация ручного ввода (cpLink остаётся отключён)
// и открытие подтверждённого личного чата из отчёта по сделкам.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const html = fs.readFileSync(path.join(__dirname, '../static/stand/tasks.html'), 'utf8');
const lines = html.split('\n');
const conversationStart = lines.findIndex(line => line === 'function standDealConversation(d){');
const conversationEnd = lines.findIndex((line, i) => i > conversationStart && line === '}');

const ALLOWED_SUBSTRINGS = [
  "placeholder=\"t.me/название, @username или ссылка-приглашение\"",
  "if(u[0]==='@') return 'https://t.me/'+u.slice(1);",
  "if(/^[A-Za-z0-9_]{4,}$/.test(u)) return 'https://t.me/'+u;",
  '/* Публичный чат открывается с уже вписанным вопросом: t.me/name?text=…',
  '   В приватной группе (t.me/c/…) и по ссылке-приглашению Telegram текст не принимает —',
];

function isAllowed(line, i) {
  const isDealConversationLink = conversationStart >= 0 && i > conversationStart && i < conversationEnd
    && line.trim() === "if(phone)href='https://wa.me/'+phone;";
  return isDealConversationLink || ALLOWED_SUBSTRINGS.some(s => line.includes(s));
}

const patterns = [/wa\.me/, /t\.me\//, /grusha\.up\.railway\.app/, /Grushath_bot/, /grusha_lk_bot/];
const offenders = [];
lines.forEach((line, i) => {
  if (isAllowed(line, i)) return;
  for (const re of patterns) {
    if (re.test(line)) { offenders.push(`${i + 1}: ${line.trim()}`); break; }
  }
});

assert.equal(offenders.length, 0, 'найдены не разрешённые боевые ссылки:\n' + offenders.join('\n'));

// CALC_URL должен быть относительным путём стенда, не прод-доменом
const calc = html.match(/const CALC_URL='([^']*)'/);
assert.ok(calc, 'не найден CALC_URL');
assert.equal(calc[1], '/', 'CALC_URL должен быть относительным путём стенда');

// cpLink всегда должен возвращать null — переход в чат контрагента на стенде выключен
const cpLink = html.match(/^function cpLink\([^]*?^}/m);
assert.ok(cpLink, 'нет функции cpLink');
assert.match(cpLink[0], /return null/, 'cpLink должен быть отключён на стенде');

console.log('stand no-prod-links: PASS (' + lines.length + ' строк проверено, разрешённых мест: ' + ALLOWED_SUBSTRINGS.length + ')');
