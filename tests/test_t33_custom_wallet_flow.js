// «Указать кошелёк…» на s11 (payinCustom с owner/multisig) должен вести флоу
// отправки так же, как кошелёк из реестра: мультисиг — фин дир, личный — сам
// владелец, findir-шаг s23 пропускается (Карим, wallet-registry, п.4).
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
             'dealWallet', 'needsSecondSign', 'stepWho', 'payinWallet'];
const CONSTS = ['WALLETS', 'LEGACY_PAYIN_ADDR', 'STEPS'];

function makeCtx() {
  return run(FNS, CONSTS, {
    S: { wallets: [] },
    CRM_WALLETS: [],
    convOf: () => null, // крипто-сделка без пачки конвертации — пачки у неё нет
  });
}

// ── Мультисиг «Указать кошелёк…»: findir-шаг s23 остаётся ──────────────────
{
  const ctx = makeCtx();
  const d = { id: 1, step: 's22', walletId: 'custom',
    payinCustom: { network: 'TRC-20', addr: 'TAbCdEfGh0123456789ijklmnopQRSTUVW', owner: 'компания', multisig: true } };
  const w = vm.runInContext('dealWallet', ctx)(d);
  assert.equal(w.multisig, true);
  assert.equal(w.role, 'findir');
  assert.equal(vm.runInContext('needsSecondSign', ctx)(d), true);
  assert.equal(vm.runInContext('stepWho', ctx)(d, 's23'), 'findir');
}

// ── Личный «Указать кошелёк…» на Теодора: findir пропускается, шаг у teodor ──
{
  const ctx = makeCtx();
  const d = { id: 2, step: 's22', walletId: 'custom',
    payinCustom: { network: 'TRC-20', addr: 'TAbCdEfGh0123456789ijklmnopQRSTUVW', owner: 'Теодор', multisig: false } };
  const w = vm.runInContext('dealWallet', ctx)(d);
  assert.equal(w.multisig, false);
  assert.equal(w.owner, 'Теодор');
  assert.equal(w.role, 'teodor');
  assert.equal(vm.runInContext('needsSecondSign', ctx)(d), false);
  assert.equal(vm.runInContext('stepWho', ctx)(d, 's23'), 'teodor',
    'личный кошелёк — шаг сразу у владельца, роль teodor (как и у Андрея, единственная персональная роль на стенде)');
}

// ── Личный «Указать кошелёк…» на Андрея: та же роль teodor (нет отдельного логина) ──
{
  const ctx = makeCtx();
  const d = { id: 3, step: 's22', walletId: 'custom',
    payinCustom: { network: 'TRC-20', addr: 'TAbCdEfGh0123456789ijklmnopQRSTUVW', owner: 'Андрей', multisig: false } };
  assert.equal(vm.runInContext('stepWho', ctx)(d, 's23'), 'teodor');
  const w = vm.runInContext('dealWallet', ctx)(d);
  assert.equal(w.owner, 'Андрей');
}

// ── payinWallet() отражает owner/multisig из payinCustom (форма «Указать кошелёк…») ──
{
  const ctx = makeCtx();
  const d = { walletId: 'custom',
    payinCustom: { network: 'ERC-20', addr: '0x1234567890abcdef1234567890abcdef12345678', owner: 'Виталий', multisig: true } };
  const w = vm.runInContext('payinWallet', ctx)(d);
  assert.equal(w.owner, 'Виталий');
  assert.equal(w.multisig, true);
  assert.equal(w.net, 'ERC-20');
}

// ── Мультисиг-кошелёк из реестра (не custom) — тот же контракт, что и раньше ──
{
  const ctx = run(FNS, CONSTS, {
    S: { wallets: [] },
    CRM_WALLETS: [{ id: 9, address: 'TKkeEVf2zySaWTLyX2qPwvi6kcdHRuPxkJ', blockchain: 'TRON',
      owner: 'компания', is_multisig: true, accepts_payin: true, is_monitored: true, active: true }],
    convOf: (d) => (d.cnvId ? { walletId: '9' } : null),
  });
  vm.runInContext('syncWalletRegistry()', ctx);
  const d = { id: 4, step: 's23', cnvId: 1 };
  assert.equal(vm.runInContext('stepWho', ctx)(d, 's23'), 'findir');
}

console.log('T33 custom wallet flow OK');
