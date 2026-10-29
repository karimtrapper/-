const assert = require('node:assert/strict');
const fs = require('node:fs');
const js = fs.readFileSync('static/calculator/calculator.js', 'utf8');
const body = js.match(/function initB2Layout\(\)\s*\{[^]*?\n\}/m)[0];
const idx = s => body.indexOf(s);
assert.ok(idx('directionSwitcher') >= 0 && idx('methodSwitcher') >= 0, 'направление и метод должны присутствовать');
assert.ok(Math.max(idx('directionSwitcher'), idx('methodSwitcher')) < idx('exchangeCard'),
  'метод+направление должны группироваться раньше карточки с суммой (exchangeCard)');
assert.ok(idx('exchangeCard') < idx('dealtype-switcher'),
  'тип сделки должен группироваться после суммы, а не первым');

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
