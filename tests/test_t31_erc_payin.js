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

const legacyWallets = [
  {id:'vitaly',name:'Кошелёк Виталия',addr:'TKkeEVf2zySaWTLyX2qPwvi6kcdHRuPxkJ',multisig:true},
  {id:'grusha',name:'Кошелёк Груши',addr:'TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn',multisig:true},
  {id:'teodor-erc',name:'подменённый кошелёк',net:'ERC-20',addr:'0x'+'3'.repeat(40)},
  {id:'andrey',name:'Кошелёк Андрея',addr:'адрес уточнить',multisig:false},
  {id:'same-address',name:'Дополнительная запись',addr:' TKkeEVf2zySaWTLyX2qPwvi6kcdHRuPxkJ '},
];
const deal = {id:1478,step:'s11',walletId:'vitaly'};
const beforeWallets = JSON.stringify(legacyWallets);
const beforeDeal = JSON.stringify(deal);
const legacyCtx = vm.createContext({S:{wallets:legacyWallets},htmlText:value=>String(value)});
vm.runInContext(html.slice(start,end),legacyCtx);
assert.equal(vm.runInContext("walletById('vitaly').addr",legacyCtx),
  'TKkeEVf2zySaWTLyX2qPwvi6kcdHRuPxkJ');
assert.equal(vm.runInContext("walletById('vitaly').owner",legacyCtx),'компания');
const picker = vm.runInContext(`payinWalletSelect(${JSON.stringify(deal)},false)`,legacyCtx);
const options = [...picker.matchAll(/<option value="([^"]+)"([^>]*)>/g)];
assert.equal(options.filter(([,id])=>id==='grusha').length,1);
assert.equal(options.filter(([,id])=>id==='vitaly').length,0);
assert.equal(options.filter(([,id])=>id==='same-address').length,0);
assert.equal(options.filter(([,id])=>id==='teodor-erc').length,1);
assert.equal(options.filter(([,id])=>id==='custom').length,1);
assert.match(options.find(([,id])=>id==='grusha')[2],/ selected/);
assert.match(picker,/Кошелёк Груши \(мультисиг\) · TRC-20 · TKkeEVf2zySaWTLyX2qPwvi6kcdHRuPxkJ/);
assert.match(picker,/Кошелёк Теодора · ERC-20 · 0x68aEA0F5386a57b48953F6fFF2f22D29D00D9ba9/);
assert.equal(JSON.stringify(legacyWallets),beforeWallets);
assert.equal(JSON.stringify(deal),beforeDeal);
console.log('ERC stand wallet mapping OK');
