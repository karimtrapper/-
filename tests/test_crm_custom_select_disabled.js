// Независимый QA (19.10) нашёл: кастомный выпадающий список в crm.html
// (upgradeSelect/renderOptions) игнорировал disabled/hidden у <option> —
// менеджер мог кликнуть по непроверенному способу/типу сделки без всякой
// видимой подсказки (сервер всё равно отклонял при сабмите, но сам
// UI-гейт не работал). customSelectOptMarkup() теперь переносит
// disabled/title/hidden на сгенерированный div.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../static/crm/crm.html'), 'utf8');

function fn(name) {
  const oneLine = html.match(new RegExp(`^\\s*function ${name}\\([^\\n]*\\)\\{[^\\n]*\\}$`, 'm'));
  if (oneLine) return oneLine[0];
  const found = html.match(new RegExp(`^\\s*function ${name}\\([^]*?^        }`, 'm'));
  assert.ok(found, `Функция ${name} отсутствует`);
  return found[0];
}

function ctx() {
  const context = { escapeHtml: (s) => String(s) };
  vm.createContext(context);
  vm.runInContext(fn('customSelectOptMarkup'), context);
  return context;
}

{
  const c = ctx();
  const markup = c.customSelectOptMarkup({ value: 'crypto_direct', text: 'Крипта напрямую', disabled: true,
    title: 'Флоу в проверке — пока проводите через Карима' }, 3, 'crypto_direct');
  assert.match(markup, /class="custom-select-opt[^"]*\bdisabled\b/, 'disabled option должна нести класс disabled');
  assert.match(markup, /title="Флоу в проверке/, 'тултип должен перенестись на div');
}
{
  const c = ctx();
  const markup = c.customSelectOptMarkup({ value: 'sber_reqs', text: 'Сбер (реквизиты)', disabled: false }, 1, 'sber_reqs');
  assert.doesNotMatch(markup, /\bdisabled\b/, 'обычная опция не должна получать класс disabled');
  assert.match(markup, /\bselected\b/, 'выбранная сейчас опция должна остаться selected');
}
{
  const c = ctx();
  const markup = c.customSelectOptMarkup({ value: 'spp_doverka', text: 'СБП (Доверка, архив)', disabled: false, hidden: true }, 5, 'sber_wl');
  assert.match(markup, /display:\s*none/, 'hidden-опция (архивный spp_doverka) не должна показываться в кастомном списке');
}
console.log('ALL OK');
