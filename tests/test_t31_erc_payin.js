const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const html = fs.readFileSync('static/stand/tasks.html', 'utf8');
const start = html.indexOf('const WALLETS=[');
const end = html.indexOf('function walletSends(', start);
assert.ok(start > 0 && end > start);
const ctx = vm.createContext({S: {wallets: [{id:'teodor-erc',
  name:'подменённый кошелёк',owner:'компания',net:'ERC-20',addr:'0x'+'3'.repeat(40)}]}});
vm.runInContext(html.slice(start, end), ctx);
const evalIn = source => vm.runInContext(source, ctx);
const fixed = evalIn("walletById('teodor-erc')");
assert.equal(fixed.addr, '0x68aEA0F5386a57b48953F6fFF2f22D29D00D9ba9');
assert.equal(fixed.owner, 'Теодор');
assert.equal(fixed.multisig, false);
assert.equal(fixed.role, 'teodor');
assert.equal(evalIn("walletById('grusha').addr"), 'TKkeEVf2zySaWTLyX2qPwvi6kcdHRuPxkJ');
assert.equal(evalIn("payToCrypto(payinWallet({walletId:'teodor-erc'}))"),
  'USDT ERC-20, 0x68aEA0F5386a57b48953F6fFF2f22D29D00D9ba9');
assert.equal(evalIn("payToCrypto(payinWallet({walletId:'custom',payinCustom:{network:'TRC-20',addr:'TKkeEVf2zySaWTLyX2qPwvi6kcdHRuPxkJ'}}))"),
  'USDT TRC-20, TKkeEVf2zySaWTLyX2qPwvi6kcdHRuPxkJ');
assert.equal(evalIn("addrValid('0x'+'2'.repeat(40),'TRC-20')"), false);
assert.equal(evalIn("addrValid('0x'+'2'.repeat(40),'ERC-20')"), true);
assert.equal(ctx.S.wallets[0].addr, '0x'+'3'.repeat(40)); // persisted state untouched
console.log('ERC stand wallet mapping OK');
