const assert = require('node:assert/strict');
const fs = require('node:fs');
const js = fs.readFileSync('static/calculator/calculator.js', 'utf8');
const body = js.match(/function initB2Layout\(\)\s*\{[^]*?\n\}/m)[0];
const idx = s => body.indexOf(s);
// Порядок левой колонки: Тип сделки → Метод → Направление → Сумма (решение Карима 2026-10-29).
assert.ok(idx('dealtype-switcher') >= 0 && idx('methodSwitcher') >= 0 && idx('directionSwitcher') >= 0,
  'тип сделки, метод и направление должны присутствовать');
assert.ok(idx('dealtype-switcher') < idx('methodSwitcher'),
  'тип сделки должен группироваться первым, перед методом');
assert.ok(idx('methodSwitcher') < idx('directionSwitcher'),
  'метод должен группироваться перед направлением');
assert.ok(idx('directionSwitcher') < idx('exchangeCard'),
  'направление должно группироваться раньше карточки с суммой (exchangeCard)');

// methodCaption и подпись «Тип сделки» делят класс .switcher-caption — если тип сделки
// снова возьмут через querySelector('.switcher-caption'), он после переноса методCaption
// в начало DOM молча утащит чужую подпись «Метод обмена» (поймано на QA-скриншоте 2026-10-29).
assert.ok(body.includes("getElementById('dealtypeCaption')"),
  'подпись типа сделки должна браться по id, а не по общему классу .switcher-caption (иначе утащит methodCaption)');
assert.ok(!body.includes("querySelector('.switcher-caption')"),
  'container.querySelector(\'.switcher-caption\') неоднозначен — у methodCaption тот же класс');

const html = fs.readFileSync('static/calculator/index.html', 'utf8');
assert.ok(/id="dealtypeCaption"/.test(html), 'в разметке должен быть id="dealtypeCaption" на подписи типа сделки');

console.log('layout order: PASS');
