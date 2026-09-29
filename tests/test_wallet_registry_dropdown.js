const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

// Реестр кошельков CRM — единственный источник кошельков, куда клиент платит
// USDT на s11. Проверяем: фильтр по сети и accepts_payin, дефолт — мультисиг,
// легаси walletId резолвится по адресу из реестра или как раньше, если реестра
// ещё нет.
const html = fs.readFileSync('static/stand/tasks.html', 'utf8');
const start = html.indexOf('let CRM_WALLETS=[];');
const end = html.indexOf('function walletSends(w)', start);
assert.ok(start >= 0 && end > start, 'payin dropdown block not found');

const context = vm.createContext({S: {}, CRM_WALLETS: []});
vm.runInContext(html.slice(start, end), context);
const run = (code) => vm.runInContext(code, context);

// --- Реестр с мультисигом Груши, личным Теодора и Андрея (TRC-20) + Теодор ERC-20
const REGISTRY = [
  {id: 1, address: 'TKkeEVf2zySaWTLyX2qPwvi6kcdHRuPxkJ', blockchain: 'TRON', owner: 'компания', is_multisig: true, accepts_payin: true, label: 'Кошелёк Груши'},
  {id: 2, address: 'TVmgzMQ2zwV2DVPscBf98WRRdhrcpf5x5p', blockchain: 'TRON', owner: 'Теодор', is_multisig: false, accepts_payin: true, label: null},
  {id: 3, address: 'TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn', blockchain: 'TRON', owner: 'Андрей', is_multisig: false, accepts_payin: true, label: null},
  {id: 4, address: '0x68aEA0F5386a57b48953F6fFF2f22D29D00D9ba9', blockchain: 'ETH', owner: 'Теодор', is_multisig: false, accepts_payin: true, label: 'Теодор · ERC-20'},
  {id: 5, address: 'TNotAcceptingPayinAddress0000000000', blockchain: 'TRON', owner: 'Кто-то', is_multisig: false, accepts_payin: false, label: null},
];
run(`CRM_WALLETS = ${JSON.stringify(REGISTRY)}`);

// Фильтр по сети видит только accepts_payin=true своей сети
const trc = run('crmPayinChoices("TRC-20")');
assert.equal(trc.length, 3);
assert.ok(trc.every(w => w.accepts_payin));
const erc = run('crmPayinChoices("ERC-20")');
assert.equal(erc.length, 1);
assert.equal(erc[0].address, '0x68aEA0F5386a57b48953F6fFF2f22D29D00D9ba9');

// Дефолт — мультисиг-кошелёк сети, если есть
const def = run('payinDefaultWallet("TRC-20")');
assert.equal(def.addr, 'TKkeEVf2zySaWTLyX2qPwvi6kcdHRuPxkJ');
assert.equal(def.multisig, true);
// Для ERC-20 мультисига нет — берём первый (единственный) вариант
const defErc = run('payinDefaultWallet("ERC-20")');
assert.equal(defErc.addr, '0x68aEA0F5386a57b48953F6fFF2f22D29D00D9ba9');

// Легаси walletId резолвится через реестр по известному адресу
run('S = {}');
const grusha = run('payinWallet({walletId:"grusha"})');
assert.equal(grusha.addr, 'TKkeEVf2zySaWTLyX2qPwvi6kcdHRuPxkJ');
assert.equal(grusha.multisig, true);
const vitaly = run('payinWallet({walletId:"vitaly"})');
assert.equal(vitaly.addr, grusha.addr);
const teodorErc = run('payinWallet({walletId:"teodor-erc"})');
assert.equal(teodorErc.addr, '0x68aEA0F5386a57b48953F6fFF2f22D29D00D9ba9');
assert.equal(teodorErc.net, 'ERC-20');

// Новый формат: walletId — числовой id кошелька реестра
const byId = run('payinWallet({walletId:"3"})');
assert.equal(byId.addr, 'TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn');
assert.equal(byId.owner, 'Андрей');

// Свой кошелёк — не из реестра
const custom = run('payinWallet({walletId:"custom",payinCustom:{network:"TRC-20",addr:"TXXCustomAddress0000000000000000"}})');
assert.equal(custom.id, 'custom');
assert.equal(custom.addr, 'TXXCustomAddress0000000000000000');

// Легаси-адрес, которого ещё нет в реестре (реестр не засеян) — резолвится по
// прежним правилам сети/владения
run('CRM_WALLETS = []');
run('S = {}');
const legacyOnly = run('payinWallet({walletId:"andrey"})');
assert.equal(legacyOnly.addr, 'TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn');
assert.equal(legacyOnly.multisig, false);

console.log('wallet registry dropdown OK');
