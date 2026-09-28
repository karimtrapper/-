const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, '../static/auth/login.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];

function element() {
    const listeners = {};
    return {style: {display: 'none'}, textContent: '', innerHTML: '', value: '',
        classList: {add() {}, remove() {}},
        addEventListener: (name, fn) => { listeners[name] = fn; },
        click: async () => { if (listeners.click) await listeners.click({preventDefault() {}}); }};
}
async function scenario({stand, setup = 403, me = 401, login = 401, healthError = false,
                         healthMalformed = false, healthStatus = 200, healthBody,
                         loginError = 'unauthorized', telegramAvailable = true} = {}) {
    const ids = ['loginMode', 'setupMode', 'pwForm', 'tgControls', 'tgLoginBtn',
        'tgBotLoginBtn', 'pwToggle', 'botLoginStatus', 'loginError', 'loginBtn',
        'loginUsername', 'loginPassword'];
    const els = Object.fromEntries(ids.map(id => [id, element()]));
    const calls = [], opened = [], scripts = [], intervals = [];
    const response = (status, body) => ({ok: status >= 200 && status < 300, status,
        json: async () => body});
    const ctx = {
        document: {getElementById: id => els[id], createElement: () => ({}),
            head: {appendChild: s => scripts.push(s.src)}},
        window: {location: {href: ''}, open: url => opened.push(url),
            Telegram: telegramAvailable ? {Login: {auth: (_cfg, callback) => callback({id: 1})}} : null},
        fetch: async (url, options) => {
            calls.push({url, options});
            if (url === '/api/health') {
                if (healthError) throw Error('network');
                if (healthMalformed) return {ok: true, json: async () => { throw Error('JSON'); }};
                return response(healthStatus, healthBody === undefined ? {stand} : healthBody);
            }
            if (url === '/api/auth/me') return response(me, {success: me === 200});
            if (url === '/api/auth/setup') return response(setup, {success: setup === 200});
            if (url === '/api/auth/tg-config') return response(200, {bot_id: 1});
            if (url === '/api/auth/login') {
                if (login === 'network') throw Error('network');
                return response(login, {success: login === 200, error: loginError});
            }
            if (url === '/api/auth/tg-login') return response(200, {success: true});
            if (url === '/api/auth/tg-start') return response(200, {success: true,
                link: 'https://t.me/fakebot?start=login_test', nonce: 'test'});
            if (url.startsWith('/api/auth/tg-poll')) return response(200, {status: 'pending'});
            throw Error(`unexpected ${url}`);
        },
        setInterval: fn => { intervals.push(fn); return intervals.length; },
        clearInterval() {}, Date, encodeURIComponent
    };
    vm.runInNewContext(script, ctx);
    for (let i = 0; i < 6; i++) await new Promise(resolve => setImmediate(resolve));
    return {els, calls, opened, scripts, intervals, ctx};
}
const tgCalls = result => result.calls.filter(c => /\/api\/auth\/tg-/.test(c.url));

(async () => {
    for (const setup of [400, 401, 403, 500]) {
        const r = await scenario({stand: true, setup});
        assert.equal(r.els.loginMode.style.display, 'block');
        assert.equal(r.els.setupMode.style.display, 'none');
        assert.equal(r.els.pwForm.style.display, 'block');
        assert.equal(r.els.tgControls.style.display, 'none');
        assert.equal(r.els.loginError.textContent, '');
        assert.equal(tgCalls(r).length, 0);
        assert.equal(r.calls.find(c => c.url === '/api/auth/setup').options.method, 'POST');
    }
    for (const opts of [{healthError: true}, {healthMalformed: true},
        {healthStatus: 500, stand: false}, {healthBody: {}}, {healthBody: null},
        {healthBody: {stand: 'false'}}]) {
        const r = await scenario({...opts, setup: 403});
        assert.equal(r.els.pwForm.style.display, 'block');
        assert.equal(r.els.tgControls.style.display, 'none');
        assert.equal(tgCalls(r).length, 0);
        assert.equal(r.opened.length, 0);
        assert.equal(r.scripts.length, 0);
    }
    const setup = await scenario({stand: false, setup: 200});
    assert.equal(setup.els.loginMode.style.display, 'none');
    assert.equal(setup.els.setupMode.style.display, 'block');
    assert.equal(tgCalls(setup).length, 0);
    const authed = await scenario({stand: true, me: 200});
    assert.equal(authed.ctx.window.location.href, '/crm');
    assert.equal(authed.calls.some(c => c.url === '/api/auth/setup'), false);
    const prodAuthed = await scenario({stand: false, me: 200});
    assert.equal(prodAuthed.ctx.window.location.href, '/crm');
    assert.equal(tgCalls(prodAuthed).length, 0);
    const wrong = await scenario({stand: true});
    await wrong.ctx.doLogin({preventDefault() {}});
    assert.equal(wrong.els.loginError.textContent, 'Неверный логин или пароль');
    assert.equal(tgCalls(wrong).length, 0);
    const network = await scenario({stand: true, login: 'network'});
    await network.ctx.doLogin({preventDefault() {}});
    assert.equal(network.els.loginError.textContent, 'Ошибка сети');
    for (const [status, expected] of [[403, 'Доступ к входу закрыт'],
        [500, 'Временная ошибка сервера. Попробуйте позже']]) {
        const r = await scenario({stand: true, login: status, loginError: 'internalerror'});
        await r.ctx.doLogin({preventDefault() {}});
        assert.equal(r.els.loginError.textContent, expected);
    }
    const success = await scenario({stand: true, login: 200});
    await success.ctx.doLogin({preventDefault() {}});
    assert.equal(success.ctx.window.location.href, '/crm');
    const prod = await scenario({stand: false});
    assert.equal(prod.els.tgControls.style.display, 'block');
    assert.equal(prod.els.pwForm.style.display, 'none');
    assert.equal(tgCalls(prod).filter(c => c.url === '/api/auth/tg-config').length, 1);
    await prod.els.pwToggle.click();
    assert.equal(prod.els.pwForm.style.display, 'block');
    await prod.els.tgBotLoginBtn.click();
    assert.equal(prod.opened[0], 'https://t.me/fakebot?start=login_test');
    await prod.intervals[0]();
    assert.ok(prod.calls.some(c => c.url.startsWith('/api/auth/tg-poll')));
    await prod.els.tgLoginBtn.click();
    assert.ok(prod.calls.some(c => c.url === '/api/auth/tg-login'));
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(prod.ctx.window.location.href, '/crm');
    const widget = await scenario({stand: false, telegramAvailable: false});
    assert.equal(widget.scripts.length, 1);
    assert.ok(widget.scripts[0].startsWith('https://telegram.org/js/telegram-widget.js'));
    console.log('login setup/stand/prod modes: PASS');
})().catch(error => { console.error(error); process.exitCode = 1; });
