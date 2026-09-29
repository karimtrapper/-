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
const deal = {id:1478,step:'s11',walletId:'vitaly',
  docFields:{payTo:'USDT TRC-20, TKkeEVf2zySaWTLyX2qPwvi6kcdHRuPxkJ'},
  amountUsdt:1000,rates:{client:36}};
const beforeWallets = JSON.stringify(legacyWallets);
const beforeDeal = JSON.stringify(deal);
let saves=0;
const inputs={};
const messages=[];
const legacyCtx = vm.createContext({S:{wallets:legacyWallets,deals:[deal]},
  htmlText:value=>String(value),deal:id=>id===deal.id?deal:null,
  isCrypto:d=>d.payType==='Крипта',save:()=>{saves++;},render:()=>{},
  log:()=>{},toast:message=>messages.push(message),val:id=>inputs[id]});
vm.runInContext(html.slice(start,end),legacyCtx);
const run = source => vm.runInContext(source,legacyCtx);
assert.equal(vm.runInContext("walletById('vitaly').addr",legacyCtx),
  'TKkeEVf2zySaWTLyX2qPwvi6kcdHRuPxkJ');
assert.equal(vm.runInContext("walletById('vitaly').owner",legacyCtx),'компания');
const radios = markup => [...markup.matchAll(/<input type="radio" name="payin_1478" value="([^"]+)"([^>]*)>/g)];
let picker = run('payinWalletSelect(S.deals[0],false)');
let choices = radios(picker);
assert.equal(choices.filter(([,id])=>id==='grusha').length,1);
assert.equal(choices.filter(([,id])=>id==='vitaly').length,0);
assert.equal(choices.filter(([,id])=>id==='same-address').length,0);
assert.equal(choices.filter(([,id])=>id==='teodor-erc').length,0);
assert.equal(choices.filter(([,id])=>id==='custom').length,1);
assert.match(choices.find(([,id])=>id==='grusha')[2],/ checked/);
assert.match(picker,/TKkeEVf2zySaWTLyX2qPwvi6kcdHRuPxkJ<\/span><span class="wc-o">TRC-20 · владелец: компания/);
assert.doesNotMatch(picker,/мультисиг|личный|копировать|wc-f|df_payTo/);
assert.doesNotMatch(picker.split('<div class="wcards"')[1],/<button|<b>|<p/);
assert.equal(saves,0);
assert.equal(JSON.stringify(legacyWallets),beforeWallets);
assert.equal(JSON.stringify(deal),beforeDeal);

run("payinNetworkSet(1478,'ERC-20')");
assert.equal(deal.walletId,'teodor-erc');
assert.equal(deal.docFields.payTo,'USDT ERC-20, 0x68aEA0F5386a57b48953F6fFF2f22D29D00D9ba9');
picker = run('payinWalletSelect(S.deals[0],false)');
choices = radios(picker);
assert.equal(choices.filter(([,id])=>id==='teodor-erc').length,1);
assert.match(choices.find(([,id])=>id==='teodor-erc')[2],/ checked/);
assert.equal(choices.filter(([,id])=>id==='grusha').length,0);
assert.match(picker,/0x68aEA0F5386a57b48953F6fFF2f22D29D00D9ba9<\/span><span class="wc-o">ERC-20 · владелец: Теодор/);
run("payinNetworkSet(1478,'TRC-20')");
assert.equal(deal.walletId,'grusha');
assert.equal(deal.docFields.payTo,'USDT TRC-20, TKkeEVf2zySaWTLyX2qPwvi6kcdHRuPxkJ');
assert.equal(saves,2);
assert.equal(deal.amountUsdt,1000);
assert.deepEqual(deal.rates,{client:36});

run('payinCustomEdit(1478)');
picker = run('payinWalletSelect(S.deals[0],false)');
assert.match(radios(picker).find(([,id])=>id==='custom')[2],/ checked/);
assert.match(picker,/id="pcn_1478"/);
assert.match(picker,/id="pca_1478"/);
assert.equal(saves,2); // opening the form does not change the saved receiver
deal.step='s12';
picker = run('payinWalletSelect(S.deals[0],true)');
assert.match(radios(picker).find(([,id])=>id==='grusha')[2],/ checked disabled/);
assert.doesNotMatch(radios(picker).find(([,id])=>id==='custom')[2],/ checked/);
deal.step='s11';
inputs.pcn_1478='ERC-20';inputs.pca_1478='TKkeEVf2zySaWTLyX2qPwvi6kcdHRuPxkJ';
run('payinCustomSet(1478)');
assert.equal(deal.walletId,'grusha');
assert.equal(saves,2);
assert.match(messages.at(-1),/Адрес не соответствует сети ERC-20/);
inputs.pca_1478='0x'+'2'.repeat(40);
run('payinCustomSet(1478)');
assert.equal(deal.walletId,'custom');
assert.equal(deal.payinCustom.network,'ERC-20');
assert.equal(deal.docFields.payTo,'USDT ERC-20, 0x'+'2'.repeat(40));
assert.equal(saves,3);
picker = run('payinWalletSelect(S.deals[0],false)');
assert.match(radios(picker).find(([,id])=>id==='custom')[2],/ checked/);
run("payinNetworkSet(1478,'TRC-20')");
assert.equal(deal.walletId,'grusha');
assert.equal(saves,4);
run('payinCustomEdit(1478)');
inputs.pcn_1478='TRC-20';inputs.pca_1478='TVmgzMQ2zwV2DVPscBf98WRRdhrcpf5x5p';
run('payinCustomSet(1478)');
assert.equal(deal.walletId,'custom');
assert.equal(deal.payinCustom.network,'TRC-20');
assert.equal(deal.docFields.payTo,'USDT TRC-20, TVmgzMQ2zwV2DVPscBf98WRRdhrcpf5x5p');
assert.equal(saves,5);
deal.step='s12';
picker = run('payinWalletSelect(S.deals[0],true)');
assert.doesNotMatch(picker,/payinNetworkSet/);
assert.match(radios(picker).find(([,id])=>id==='custom')[2],/ checked disabled/);
run("payinNetworkSet(1478,'ERC-20')");
assert.equal(deal.walletId,'custom');
assert.equal(saves,5);

deal.payType='Крипта';
const cryptoFields = run("payinS11Fields(S.deals[0],()=>'<textarea id=\"df_payTo\"></textarea>')");
assert.match(cryptoFields,/Кошелёк, куда клиент платит USDT/);
assert.doesNotMatch(cryptoFields,/df_payTo|мультисиг|личный|копировать/);
deal.payType='Рубли';
const rubFields = run("payinS11Fields(S.deals[0],()=>'<textarea id=\"df_payTo\"></textarea>')");
assert.match(rubFields,/df_payTo/);
assert.doesNotMatch(rubFields,/payin-choices/);
console.log('ERC stand wallet mapping OK');
