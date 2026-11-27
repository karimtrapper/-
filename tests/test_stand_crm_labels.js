// Рендер списка админов: продовые подписи из main и поля стенда.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../static/crm/crm.html'), 'utf8');
// Эмодзи убраны из вкладки (находка №6 аудита ui-2026-10-17) — текст и так
// совпадает с data-shell-label, который nav-shell.js подставляет после mount.
assert.match(html, /<button class="nav-tab" data-section="admins" data-shell-label="Сотрудники">Админы<\/button>/);

const start = html.indexOf('async function loadAdmins() {');
const end = html.indexOf('/* Роли живут только на стенде:', start);
assert.ok(start > 0 && end > start, 'функция списка админов найдена');
const source = html.slice(start, end);
const escapeStart = html.indexOf('function escapeHtml(value) {');
const escapeEnd = html.indexOf('\n        }', escapeStart);
const escapeHtml = html.slice(escapeStart, escapeEnd + '\n        }'.length);
async function render(bound, stand, employee = {}) {
    const box = {innerHTML: ''};
    const calls = [];
    const context = {
        API_URL: '',
        document: {getElementById: id => id === 'adminsList' ? box : null},
        fetch: async url => {
            calls.push(url);
            if (url === '/api/admins') return {ok: true, json: async () => ({success: true, admins: [{
                id: 1, display_name: 'Сотрудник', username: 'user', telegram: '@user',
                telegram_user_id: '12345', role: 'admin', bound, ...employee,
            }]})};
            if (url === '/api/stand/tg-status') return {ok: true, json: async () => ({
                profile: 'stand_bot', employees: [{id: 1, notify_enabled: true}],
            })};
            throw new Error(`unexpected fetch: ${url}`);
        },
    };
    const roles = stand ? '{admin: "Админ", operator: "Операционист"}' : 'null';
    await vm.runInNewContext(`let STAND_ROLES = ${roles}; ${escapeHtml} ${source}\nloadAdmins()`, context);
    return {html: box.innerHTML, calls};
}

(async () => {
    for (const bound of [false, true]) {
        for (const stand of [false, true]) {
            const {html: rendered, calls} = await render(bound, stand);
            const status = rendered.match(/<div style="font-size:12px;color:#64748b;">(.*?)<\/div>/)?.[1];
            // CRM status labels lost their decorative emoji in the October UI cleanup.
            const expected = stand
                ? `логин <b>user</b> · @user ${bound ? '· Telegram ID задан' : '· Telegram ID не задан'}`
                : `@user ${bound ? '· привязан' : '· ждёт входа'}`;
            assert.equal(status, expected, `bound=${bound}, stand=${stand}`);
            assert.deepEqual(calls, stand ? ['/api/admins', '/api/stand/tg-status'] : ['/api/admins']);
            for (const marker of ['placeholder="Telegram ID"', 'setAdminRole(', 'setAdminNotify(', 'testAdminNotify(']) {
                assert.equal(rendered.includes(marker), stand, `${marker}: bound=${bound}, stand=${stand}`);
            }
            assert.equal(rendered.includes('copyAdminInvite('), !stand);
            assert.doesNotMatch(rendered, /Изменить имя/);
        }
    }
    const operator = {role: 'operator', display_name: 'Ирина <img src=x onerror=alert(1)>', telegram: '"test"'};
    const active = await render(true, true, operator);
    assert.match(active.html, /Изменить имя/);
    assert.match(active.html, /Ирина &lt;img src=x onerror=alert\(1\)&gt;/);
    assert.doesNotMatch(active.html, /<img/);
    const disabled = await render(true, true, {...operator, login_disabled: true});
    assert.doesNotMatch(disabled.html, /Изменить имя/);
    const prod = await render(true, false, operator);
    assert.doesNotMatch(prod.html, /Изменить имя/);

    const renameStart = html.indexOf('async function setAdminName(id, name) {');
    const renameEnd = html.indexOf('async function setAdminPassword', renameStart);
    const updateCalls = [];
    const rename = {
        API_URL: '',
        prompt: () => '  Ирина Петрова  ',
        fetch: async (url, options) => {
            updateCalls.push([url, options.method, JSON.parse(options.body)]);
            return {json: async () => ({success: true})};
        },
        showToast: () => {},
        loadAdmins: () => {},
    };
    await vm.runInNewContext(html.slice(renameStart, renameEnd) + 'setAdminName(42, "Ирина")', rename);
    assert.deepEqual(updateCalls, [['/api/admins/42', 'PUT', {display_name: 'Ирина Петрова'}]]);
    console.log('crm employee labels, stand controls and name update: PASS');
})().catch(error => { console.error(error); process.exitCode = 1; });
