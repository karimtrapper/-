// Продовые подписи должны сохраняться, когда роли стенда не загружены.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../static/crm/crm.html'), 'utf8');
assert.match(html, /<button class="nav-tab" data-section="admins">🔐 Админы<\/button>/);

const start = html.indexOf('async function loadAdmins() {');
const end = html.indexOf('/* Роли живут только на стенде:', start);
assert.ok(start > 0 && end > start, 'функция списка админов найдена');
const source = html.slice(start, end);
const box = {innerHTML: ''};
const context = {
    API_URL: '',
    document: {getElementById: id => id === 'adminsList' ? box : null},
    fetch: async () => ({ok: true, json: async () => ({success: true, admins: [{
        id: 1, display_name: 'Сотрудник', username: 'user', telegram: '@user', bound: false,
    }]})}),
    escapeHtml: value => value,
};

(async () => {
    await vm.runInNewContext(`let STAND_ROLES = null; ${source}\nloadAdmins()`, context);
    assert.match(box.innerHTML, /· ⚪ ждёт входа/);
    assert.doesNotMatch(box.innerHTML, /Telegram не привязан/);
    console.log('crm prod labels: PASS');
})().catch(error => { console.error(error); process.exitCode = 1; });
