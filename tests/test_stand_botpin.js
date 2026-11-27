const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const path = require('path');

const html = fs.readFileSync(path.join(__dirname, '../static/crm/crm.html'), 'utf8');
const source = html.match(/^        async function connectStandTelegram\([^]*?^        }/m);
assert(source, 'connectStandTelegram отсутствует');

async function check(response) {
    const opened = [];
    const messages = [];
    const context = {
        API_URL: '',
        fetch: async () => ({json: async () => response}),
        window: {open: url => opened.push(url)},
        showToast: message => messages.push(message),
    };
    vm.createContext(context);
    vm.runInContext(source[0], context);
    await context.connectStandTelegram();
    return {opened, messages};
}

(async () => {
    const nonce = 'A'.repeat(24);
    const valid = `https://t.me/grusha_stand_bot?start=bind_${nonce}`;
    assert.deepStrictEqual((await check({success: true, bot_username: 'grusha_stand_bot', url: valid})).opened, [valid]);
    for (const url of [
        `https://t.me/grusha_lk_bot?start=bind_${nonce}`,
        `https://t.me/grusha_stand_bot?start=bind_${nonce}&next=evil`,
        `http://t.me/grusha_stand_bot?start=bind_${nonce}`,
        `https://t.me/grusha_stand_bot?start=bind_short`,
    ]) {
        const result = await check({success: true, bot_username: 'grusha_stand_bot', url});
        assert.deepStrictEqual(result.opened, []);
        assert(result.messages.length);
    }
    assert.deepStrictEqual((await check({success: true, bot_username: 'grusha_lk_bot', url: valid})).opened, []);
    console.log('stand botpin CRM: passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
