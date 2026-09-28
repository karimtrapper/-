// Рендер списка админов: продовые подписи из main и поля стенда.
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
async function render(bound, stand) {
    const box = {innerHTML: ''};
    const calls = [];
    const context = {
        API_URL: '',
        document: {getElementById: id => id === 'adminsList' ? box : null},
        fetch: async url => {
            calls.push(url);
            if (url === '/api/admins') return {ok: true, json: async () => ({success: true, admins: [{
                id: 1, display_name: 'Сотрудник', username: 'user', telegram: '@user',
                telegram_user_id: '12345', role: 'admin', bound,
            }]})};
            if (url === '/api/stand/tg-status') return {ok: true, json: async () => ({
                profile: 'stand_bot', employees: [{id: 1, notify_enabled: true}],
            })};
            throw new Error(`unexpected fetch: ${url}`);
        },
        escapeHtml: value => value,
    };
    const roles = stand ? '{admin: "Админ"}' : 'null';
    await vm.runInNewContext(`let STAND_ROLES = ${roles}; ${source}\nloadAdmins()`, context);
    return {html: box.innerHTML, calls};
}

(async () => {
    for (const bound of [false, true]) {
        for (const stand of [false, true]) {
            const {html: rendered, calls} = await render(bound, stand);
            const status = rendered.match(/<div style="font-size:12px;color:#64748b;">(.*?)<\/div>/)?.[1];
            const expected = stand
                ? `логин <b>user</b> · @user ${bound ? '· 🟢 Telegram ID задан' : '· ⚪ Telegram ID не задан'}`
                : `@user ${bound ? '· 🟢 привязан' : '· ⚪ ждёт входа'}`;
            assert.equal(status, expected, `bound=${bound}, stand=${stand}`);
            assert.deepEqual(calls, stand ? ['/api/admins', '/api/stand/tg-status'] : ['/api/admins']);
            for (const marker of ['placeholder="Telegram ID"', 'setAdminRole(', 'setAdminNotify(', 'testAdminNotify(']) {
                assert.equal(rendered.includes(marker), stand, `${marker}: bound=${bound}, stand=${stand}`);
            }
            assert.equal(rendered.includes('copyAdminInvite('), !stand);
        }
    }
    console.log('crm admin labels and stand controls: PASS (4 rendered fixtures)');
})().catch(error => { console.error(error); process.exitCode = 1; });
