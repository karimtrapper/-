const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const html = fs.readFileSync('static/stand/tasks.html', 'utf8');
const start = html.indexOf('const WALLETS=[');
const end = html.indexOf('/* Кошелёк, на который крипто-клиент', start);
assert.ok(start >= 0 && end > start);
const context = vm.createContext({S: {wallets: [
  {id:'grusha',name:'Кошелёк Груши',owner:'компания',addr:'TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn',multisig:true},
  {id:'vitaly',name:'Кошелёк Виталия',owner:'Виталий',addr:'TKkeEVf2zySaWTLyX2qPwvi6kcdHRuPxkJ',multisig:true},
  {id:'andrey',name:'Кошелёк Андрея',owner:'Андрей',addr:'адрес уточнить',multisig:false},
  {id:'custom',name:'Своя запись',owner:'Андрей',addr:'TVmgzMQ2zwV2DVPscBf98WRRdhrcpf5x5p',multisig:false}
]}});
vm.runInContext(html.slice(start, end), context);
const get = id => vm.runInContext(`walletById(${JSON.stringify(id)})`, context);
const grusha = get('grusha');
const vitaly = get('vitaly');
const andrey = get('andrey');
assert.equal(grusha.addr, 'TKkeEVf2zySaWTLyX2qPwvi6kcdHRuPxkJ');
assert.equal(grusha.owner, 'компания');
assert.equal(grusha.multisig, true);
assert.equal(grusha.name, 'Кошелёк Груши (мультисиг)');
assert.equal(vitaly.addr, grusha.addr);
assert.equal(vitaly.owner, 'компания');
assert.equal(andrey.addr, 'TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn');
assert.equal(andrey.owner, 'Андрей');
assert.equal(andrey.multisig, false);
assert.match(andrey.note, /личный: Андрей подписывает сам/);
assert.equal(get('custom').addr, 'TVmgzMQ2zwV2DVPscBf98WRRdhrcpf5x5p');
assert.equal(context.S.wallets[0].addr, 'TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn');
assert.equal(get('teodor').id, 'teodor');
console.log('T30 wallet mapping OK');
