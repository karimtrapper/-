const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../static/auth/login.html'), 'utf8');
const init = html.match(/\(async function init\(\) \{[\s\S]*?\n        \}\)\(\);/);
assert.ok(init, 'init() найден в login.html');

async function check(status, expectedLogin, expectedSetup) {
    const elements = {
        loginMode: {style: {display: 'none'}},
        setupMode: {style: {display: 'none'}}
    };
    const calls = [];
    const context = {
        document: {getElementById: id => elements[id]},
        window: {location: {href: ''}},
        fetch: async (url, options) => {
            calls.push({url, options});
            return url === '/api/auth/me'
                ? {ok: false, status: 401}
                : {ok: status >= 200 && status < 300, status};
        }
    };
    vm.runInNewContext(init[0], context);
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(calls[1].url, '/api/auth/setup');
    assert.equal(calls[1].options.method, 'POST');
    assert.equal(elements.loginMode.style.display, expectedLogin, `loginMode при ${status}`);
    assert.equal(elements.setupMode.style.display, expectedSetup, `setupMode при ${status}`);
}

(async () => {
    for (const status of [400, 401, 403, 500]) {
        await check(status, 'block', 'none');
    }
    await check(200, 'none', 'block');
    console.log('login setup mode: 4 отказа и успешный ответ PASS');
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
