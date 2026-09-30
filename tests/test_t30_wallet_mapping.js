// Единый реестр кошельков (wallet-registry, Карим): wallets()/walletById() теперь
// зеркалят CRM-реестр (CRM_WALLETS, /api/wallets), а не отдельный хардкод S.wallets.
// Легаси id ('grusha'/'vitaly'/'andrey'/'teodor'/'teodor-erc') продолжают резолвиться
// по известному адресу — через реестр, если он уже знает адрес, иначе через старый
// хардкод WALLETS (Карим, wallet-registry).
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
    // Не рубим по первому «;» — заметки в WALLETS сами содержат точку с запятой
    // внутри строки («старый ID vitaly; кошелёк компании…»). Берём до «;» в
    // конце строки (после `]`/`}` или примитива), а не первой попавшейся.
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

const FNS = ['crmWalletToLegacy', 'syncWalletRegistry', 'wallets', 'walletById'];
const CONSTS = ['WALLETS', 'LEGACY_PAYIN_ADDR'];

// ── Реестр CRM знает легаси-адрес Груши/Виталия (мультисиг) и Теодора (личный) ──
{
  const ctx = run(FNS, CONSTS, {
    S: { wallets: [] },
    CRM_WALLETS: [
      { id: 501, address: 'TKkeEVf2zySaWTLyX2qPwvi6kcdHRuPxkJ', blockchain: 'TRON',
        owner: 'компания', is_multisig: true, accepts_payin: true, is_monitored: true, active: true },
      { id: 502, address: 'TVmgzMQ2zwV2DVPscBf98WRRdhrcpf5x5p', blockchain: 'TRON',
        owner: 'Теодор', is_multisig: false, accepts_payin: true, is_monitored: true, active: true },
      { id: 503, address: 'TNewWalletAddrExample000000000001', blockchain: 'TRON',
        label: 'Кошелёк Иры', owner: 'Ира', is_multisig: false, accepts_payin: false, is_monitored: true, active: true },
    ],
  });
  vm.runInContext('syncWalletRegistry()', ctx);
  const grusha = vm.runInContext("walletById('grusha')", ctx);
  const vitaly = vm.runInContext("walletById('vitaly')", ctx);
  const teodor = vm.runInContext("walletById('teodor')", ctx);
  assert.equal(grusha.addr, 'TKkeEVf2zySaWTLyX2qPwvi6kcdHRuPxkJ');
  assert.equal(grusha.owner, 'компания');
  assert.equal(grusha.multisig, true);
  assert.equal(grusha.role, 'findir', 'мультисиг из реестра — роль findir');
  assert.equal(vitaly.addr, grusha.addr, 'grusha и vitaly — легаси id одного и того же адреса');
  assert.equal(teodor.addr, 'TVmgzMQ2zwV2DVPscBf98WRRdhrcpf5x5p');
  assert.equal(teodor.multisig, false);
  assert.equal(teodor.role, 'teodor', 'личный кошелёк из реестра — роль teodor');

  // Новый кошелёк реестра (не легаси) виден в общем списке отправки/пачки.
  const ira = vm.runInContext("walletById('503')", ctx);
  assert.ok(ira, 'кошелёк, заведённый только в CRM, резолвится по числовому id');
  assert.equal(ira.owner, 'Ира');
  assert.equal(ira.multisig, false);
  assert.equal(ira.role, 'teodor');

  // andrey/teodor-erc реестр ещё не знает — резолвятся через старый хардкод WALLETS.
  const andrey = vm.runInContext("walletById('andrey')", ctx);
  assert.equal(andrey.addr, 'TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn');
  assert.equal(andrey.owner, 'Андрей');
  assert.equal(andrey.multisig, false);
}

// ── Реестр CRM пуст (ещё не загрузился) — легаси резолвятся полностью по WALLETS ──
{
  const ctx = run(FNS, CONSTS, { S: { wallets: [] }, CRM_WALLETS: [] });
  vm.runInContext('syncWalletRegistry()', ctx);
  const grusha = vm.runInContext("walletById('grusha')", ctx);
  assert.equal(grusha.addr, 'TKkeEVf2zySaWTLyX2qPwvi6kcdHRuPxkJ');
  assert.equal(grusha.multisig, true);
  const teodorErc = vm.runInContext("walletById('teodor-erc')", ctx);
  assert.equal(teodorErc.owner, 'Теодор');
}

// ── wallets() до первой синхронизации не падает — фолбэк на старый хардкод ──
{
  const ctx = run(FNS, CONSTS, { S: {}, CRM_WALLETS: [] });
  const list = vm.runInContext('wallets()', ctx);
  assert.ok(Array.isArray(list) && list.length > 0);
}

console.log('T30 wallet mapping (CRM registry) OK');
