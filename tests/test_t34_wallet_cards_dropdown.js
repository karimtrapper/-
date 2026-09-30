// «Куда брокер пришлёт USDT» (s18) теперь выпадающий список из единого реестра
// CRM, а не карточки по хардкоду — кошельков в реестре много (Карим, wallet-registry).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../static/stand/tasks.html'), 'utf8');
function functions(names) {
  return names.map(name => {
    const oneLine = html.match(new RegExp(`^function ${name}\\([^\\n]*\\)\\{[^\\n]*\\}$`, 'm'));
    if (oneLine) return oneLine[0];
    const found = html.match(new RegExp(`^function ${name}\\([^]*?^}`, 'm'));
    assert.ok(found, `Функция ${name} отсутствует`);
    return found[0];
  }).join('\n');
}
function consts(names) {
  return names.map(name => {
    const found = html.match(new RegExp(`^(?:const|let) ${name}\\s*=[\\s\\S]*?;$`, 'm'));
    assert.ok(found, `Константа ${name} отсутствует`);
    return found[0].replace(/^(?:const|let) /, 'var ');
  }).join('\n');
}
function run(fnNames, constNames, context) {
  vm.createContext(context);
  vm.runInContext(consts(constNames) + '\n' + functions(fnNames), context);
  return context;
}

const FNS = ['crmWalletToLegacy', 'syncWalletRegistry', 'wallets', 'walletById',
             'walletCards', 'walletSends', 'addrValid', 'htmlText'];
const CONSTS = ['WALLETS', 'LEGACY_PAYIN_ADDR', 'ADDR_RE'];

const ctx = run(FNS, CONSTS, {
  S: { wallets: [] },
  CRM_WALLETS: [
    { id: 11, address: 'TAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA', blockchain: 'TRON',
      label: 'Кошелёк Иры', owner: 'Ира', is_multisig: false, accepts_payin: false, is_monitored: true, active: true },
    { id: 12, address: 'TBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB', blockchain: 'TRON',
      owner: 'компания', is_multisig: true, accepts_payin: true, is_monitored: true, active: true },
    { id: 13, address: 'invalid-address', blockchain: 'TRON',
      owner: 'битый', is_multisig: false, accepts_payin: false, is_monitored: true, active: true },
  ],
});
vm.runInContext('syncWalletRegistry()', ctx);
const html_out = vm.runInContext("walletCards({id:5}, null, 'walletPick', false, 'b2w_5')", ctx);

assert.match(html_out, /<select/, 'рендерится select, а не карточки');
assert.match(html_out, /TAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA · TRC-20 · Ира/, 'формат «адрес · сеть · владелец»');
assert.match(html_out, /TBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB · TRC-20 · компания · мультисиг/, 'мультисиг отмечен в опции');
assert.ok(!html_out.includes('invalid-address'), 'кошелёк без корректного TRC-20 адреса не предлагается');

console.log('T34 wallet dropdown OK');
