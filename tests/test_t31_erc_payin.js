// T31 ERC payin selection — теперь кошелёк прихода на s11 идёт из единого
// реестра CRM (дропдаун), а не из отдельного справочника задачника
// (wallet-registry, переезд с card-picker на <select>).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const html = fs.readFileSync('static/stand/tasks.html', 'utf8');
const start = html.indexOf('const LEGACY_PAYIN_ADDR=');
const end = html.indexOf('function walletSends(', start);
assert.ok(start > 0 && end > start);

const GRUSHA = 'TKkeEVf2zySaWTLyX2qPwvi6kcdHRuPxkJ';
const TEODOR_ERC = '0x68aEA0F5386a57b48953F6fFF2f22D29D00D9ba9';
const CUSTOM_ERC = '0x' + '2'.repeat(40);
const CUSTOM_TRC = 'TVmgzMQ2zwV2DVPscBf98WRRdhrcpf5x5p';

const registry = [
  {id: 1, address: GRUSHA, blockchain: 'TRON', owner: 'компания', is_multisig: true, accepts_payin: true, label: 'Груша'},
  {id: 2, address: TEODOR_ERC, blockchain: 'ETH', owner: 'Теодор', is_multisig: false, accepts_payin: true, label: 'Теодор · ERC-20'},
];
const deal = {id: 1478, step: 's11', walletId: 'vitaly',
  docFields: {payTo: 'USDT TRC-20, ' + GRUSHA},
  amountUsdt: 1000, rates: {client: 36}};
const beforeDeal = JSON.stringify(deal);
let saves = 0;
const inputs = {};
const checks = {};
const messages = [];
const ctx = vm.createContext({S: {deals: [deal], role: 'manager'}, CRM_WALLETS: registry,
  htmlText: value => String(value), deal: id => id === deal.id ? deal : null,
  isCrypto: d => d.payType === 'Крипта', save: () => { saves++; }, render: () => {},
  log: () => {}, toast: message => messages.push(message), val: id => inputs[id],
  // «Чей кошелёк»/мультисиг/«Запомнить» читаются через DOM (owner-select + чекбоксы)
  document: {getElementById: id => (id in checks ? {checked: checks[id]} : null)}});
vm.runInContext(html.slice(start, end), ctx);
const run = source => vm.runInContext(source, ctx);

// Легаси 'vitaly' резолвится в тот же адрес, что и 'grusha', через реестр
assert.equal(run("payinWallet({walletId:'vitaly'}).addr"), GRUSHA);
assert.equal(run("payinWallet({walletId:'vitaly'}).owner"), 'компания');
assert.equal(run("payToCrypto(payinWallet({walletId:'teodor-erc'}))"),
  'USDT ERC-20, ' + TEODOR_ERC);
assert.equal(run("payToCrypto(payinWallet({walletId:'custom',payinCustom:{network:'TRC-20',addr:'" + GRUSHA + "'}}))"),
  'USDT TRC-20, ' + GRUSHA);
assert.equal(run("addrValid('0x'+'2'.repeat(40),'TRC-20')"), false);
assert.equal(run("addrValid('0x'+'2'.repeat(40),'ERC-20')"), true);

const options = markup => [...markup.matchAll(/<option value="([^"]+)"([^>]*)>([^<]*)<\/option>/g)];
let picker = run('payinWalletSelect(S.deals[0],false)');
let choices = options(picker);
assert.equal(choices.filter(([, id]) => id === '1').length, 1);
assert.equal(choices.filter(([, id]) => id === '2').length, 0); // другая сеть — не в TRC-20 списке
assert.equal(choices.filter(([, id]) => id === 'custom').length, 1);
assert.match(choices.find(([, id]) => id === '1')[2], / selected/);
assert.match(picker, new RegExp(GRUSHA + ' · TRC-20 · компания · мультисиг'));
assert.doesNotMatch(picker, /df_payTo/);
assert.equal(saves, 0);
assert.equal(JSON.stringify(deal), beforeDeal);

run("payinNetworkSet(1478,'ERC-20')");
assert.equal(deal.walletId, '2');
assert.equal(deal.docFields.payTo, 'USDT ERC-20, ' + TEODOR_ERC);
picker = run('payinWalletSelect(S.deals[0],false)');
choices = options(picker);
assert.equal(choices.filter(([, id]) => id === '2').length, 1);
assert.match(choices.find(([, id]) => id === '2')[2], / selected/);
assert.match(picker, new RegExp(TEODOR_ERC + ' · ERC-20 · Теодор'));

run("payinNetworkSet(1478,'TRC-20')");
assert.equal(deal.walletId, '1');
assert.equal(deal.docFields.payTo, 'USDT TRC-20, ' + GRUSHA);
assert.equal(saves, 2);
assert.equal(deal.amountUsdt, 1000);
assert.deepEqual(deal.rates, {client: 36});

run('payinCustomEdit(1478)');
picker = run('payinWalletSelect(S.deals[0],false)');
assert.match(options(picker).find(([, id]) => id === 'custom')[2], / selected/);
assert.match(picker, /id="pcn_1478"/);
assert.match(picker, /id="pca_1478"/);
assert.equal(saves, 2); // открытие формы не меняет сохранённого получателя
deal.step = 's12';
picker = run('payinWalletSelect(S.deals[0],true)');
assert.ok(picker.includes('disabled'));
deal.step = 's11';

inputs.pcn_1478 = 'ERC-20'; inputs.pca_1478 = GRUSHA; inputs.pco_1478 = 'Теодор';
run('payinCustomSet(1478)');
assert.equal(deal.walletId, '1'); // адрес не подошёл сети — выбор не сохранён
assert.equal(saves, 2);
assert.match(messages.at(-1), /Адрес не соответствует сети ERC-20/);

inputs.pca_1478 = CUSTOM_ERC;
run('payinCustomSet(1478)');
assert.equal(deal.walletId, 'custom');
assert.equal(deal.payinCustom.network, 'ERC-20');
assert.equal(deal.docFields.payTo, 'USDT ERC-20, ' + CUSTOM_ERC);
assert.equal(saves, 3);
picker = run('payinWalletSelect(S.deals[0],false)');
assert.match(options(picker).find(([, id]) => id === 'custom')[2], / selected/);

run("payinNetworkSet(1478,'TRC-20')");
assert.equal(deal.walletId, '1');
assert.equal(saves, 4);

run('payinCustomEdit(1478)');
inputs.pcn_1478 = 'TRC-20'; inputs.pca_1478 = CUSTOM_TRC; inputs.pco_1478 = 'Теодор';
run('payinCustomSet(1478)');
assert.equal(deal.walletId, 'custom');
assert.equal(deal.payinCustom.network, 'TRC-20');
assert.equal(deal.docFields.payTo, 'USDT TRC-20, ' + CUSTOM_TRC);
assert.equal(saves, 5);
deal.step = 's12';
picker = run('payinWalletSelect(S.deals[0],true)');
assert.doesNotMatch(picker, /payinNetworkSet/);
assert.ok(picker.includes('disabled'));
deal.step = 's11';

// «Запомнить» скрыт для роли, которой нельзя заводить кошельки
assert.doesNotMatch(run("payinWalletSelect(S.deals[0],false)"), /Запомнить в список кошельков/);
run("S.role='operator'");
run('payinCustomEdit(1478)');
assert.match(run("payinWalletSelect(S.deals[0],false)"), /Запомнить в список кошельков/);
run("S.role='manager'");

deal.payType = 'Крипта';
const cryptoFields = run("payinS11Fields(S.deals[0],()=>'<textarea id=\"df_payTo\"></textarea>')");
assert.match(cryptoFields, /Кошелёк, куда клиент платит USDT/);
assert.doesNotMatch(cryptoFields, /df_payTo/);
deal.payType = 'Рубли';
const rubFields = run("payinS11Fields(S.deals[0],()=>'<textarea id=\"df_payTo\"></textarea>')");
assert.match(rubFields, /df_payTo/);
assert.doesNotMatch(rubFields, /payin-choices/);

console.log('T31 ERC payin (реестр CRM) OK');
