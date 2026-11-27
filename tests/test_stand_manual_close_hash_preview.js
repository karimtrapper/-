// Предпросмотр хеша прихода в ручном переносе: сеть читает адреса и сумму, пустые поля
// заполняются, введённое не затирается, ошибки реестра переводятся словарём.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync('static/stand/tasks.html', 'utf8');
const fn = name => { const m = html.match(new RegExp('^function ' + name + '\\([^]*?^}', 'm')); assert.ok(m, name); return m[0]; };
const constant = name => { const m = html.match(new RegExp('^const ' + name + '=.*?;', 'ms')); assert.ok(m, name); return m[0]; };

function make(response) {
  const S = {manualCloseForm: {}};
  const ctx = {S, render: () => {}, calls: [],
    fetch: (url, opts) => { ctx.calls.push(JSON.parse(opts.body));
      return Promise.resolve({json: () => Promise.resolve(response)}); }};
  vm.createContext(ctx);
  vm.runInContext([fn('manualCloseFormState'), fn('mcHashCheck'), constant('MANUAL_CLOSE_ERRORS')].join('\n'), ctx);
  return ctx;
}
const settle = () => new Promise(resolve => setTimeout(resolve, 5));

(async () => {
  // hash-only из пула: адресов и суммы нет → сеть заполняет пустые поля
  {
    const ctx = make({success: true, verifiedAmount: 1400, verifiedAt: 'T', from: 'TFrom', to: 'TOurs'});
    const f = ctx.manualCloseFormState(1);
    f.payin.hashes.push({hash: 'a'.repeat(64), network: 'TRC20', amount: null, receiver: '', sender: ''});
    ctx.mcHashCheck(1, 'payin', 0); await settle();
    const h = f.payin.hashes[0];
    assert.deepEqual([h.sender, h.receiver, h.amount], ['TFrom', 'TOurs', 1400]);
    assert.equal(h._check.ok, true);
    assert.equal(ctx.calls[0].receiver, null, 'пустой адрес уходит как null (hash-only)');
  }
  // введённые явно адрес и сумма не затираются
  {
    const ctx = make({success: true, verifiedAmount: 1400, from: 'TFrom', to: 'TOurs'});
    const f = ctx.manualCloseFormState(1);
    f.payin.hashes.push({hash: 'b'.repeat(64), network: 'TRC20', amount: 1399.99, receiver: 'TTyped', sender: 'TTypedFrom'});
    ctx.mcHashCheck(1, 'payin', 0); await settle();
    const h = f.payin.hashes[0];
    assert.deepEqual([h.sender, h.receiver, h.amount], ['TTypedFrom', 'TTyped', 1399.99]);
  }
  // чужой кошелёк: код сервера → понятный текст словаря
  {
    const ctx = make({success: false, error: 'payin_wallet_not_registered'});
    const f = ctx.manualCloseFormState(1);
    f.payin.hashes.push({hash: 'c'.repeat(64), network: 'TRC20', amount: null});
    ctx.mcHashCheck(1, 'payin', 0); await settle();
    assert.match(f.payin.hashes[0]._check.error, /не наш активный кошелёк из реестра/);
    assert.equal(f.payin.hashes[0]._check.ok, false);
  }
  // выдача: адреса не заполняются сетью (payout не трогаем)
  {
    const ctx = make({success: true, verifiedAmount: 90, from: 'TFrom', to: 'TOurs'});
    const f = ctx.manualCloseFormState(1);
    f.payout.hashes.push({hash: 'd'.repeat(64), network: 'TRC20', amount: null});
    ctx.mcHashCheck(1, 'payout', 0); await settle();
    const h = f.payout.hashes[0];
    assert.deepEqual([h.sender, h.receiver, h.amount], [undefined, undefined, null]);
  }
  // устаревший ответ: пока шёл запрос, хеш переписали / строку удалили — поля не трогаем
  for (const change of ['rewrite', 'network', 'delete']) {
    let release;
    const ctx = make({success: true, verifiedAmount: 1400, from: 'TOldFrom', to: 'TOldTo'});
    ctx.fetch = (url, opts) => new Promise(resolve => { release = () => resolve({json: () => Promise.resolve(
      {success: true, verifiedAmount: 1400, from: 'TOldFrom', to: 'TOldTo'})}); });
    const f = ctx.manualCloseFormState(1);
    f.payin.hashes.push({hash: 'e'.repeat(64), network: 'TRC20', amount: null});
    const h = f.payin.hashes[0];
    ctx.mcHashCheck(1, 'payin', 0);
    if (change === 'rewrite') h.hash = 'f'.repeat(64);
    else if (change === 'network') h.network = 'ERC20';
    else f.payin.hashes.splice(0, 1);
    release(); await settle();
    assert.deepEqual([h.sender, h.receiver, h.amount], [undefined, undefined, null], change);
  }
  console.log('manual close hash preview PASS');
})();
