const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../static/stand/tasks.html'), 'utf8');
function source(name, async = false) {
  const re = new RegExp('^' + (async ? 'async ' : '') + 'function ' + name + '\\([^]*?^}', 'm');
  const match = html.match(re);
  assert.ok(match, `${name} missing`);
  return match[0];
}

function makeCtx(confirmResult) {
  const S = {manualCloseDraft: {}};
  const renders = [];
  const confirms = [];
  const ctx = {
    S, render: () => renders.push(1),
    confirm: msg => { confirms.push(msg); return confirmResult; },
  };
  vm.createContext(ctx);
  vm.runInContext([
    source('manualCloseAsk'), source('manualCloseOpen'), source('manualCloseCancel'),
  ].join('\n'), ctx);
  return {ctx, S, renders, confirms};
}

function main() {
  // test: manualCloseAsk does nothing if confirm() returns false
  {
    const {ctx, S, renders, confirms} = makeCtx(false);
    ctx.manualCloseAsk(1474);
    assert.equal(confirms.length, 1, 'confirm must be called');
    assert.equal(S.manualCloseDraft[1474], undefined, 'draft flag must stay unset on cancel');
    assert.equal(renders.length, 0, 'render must not run when confirm is declined');
  }

  // test: manualCloseAsk calls manualCloseOpen if confirm() returns true
  {
    const {ctx, S, renders} = makeCtx(true);
    ctx.manualCloseAsk(1474);
    assert.equal(S.manualCloseDraft[1474], true, 'manualCloseAsk must open the draft via manualCloseOpen');
    assert.equal(renders.length, 1, 'manualCloseOpen must re-render');
  }

  // test: manualCloseOpen sets S.manualCloseDraft[id] truthy
  {
    const {ctx, S, renders} = makeCtx(true);
    ctx.manualCloseOpen(1474);
    assert.ok(S.manualCloseDraft[1474], 'manualCloseOpen must set the draft flag');
    assert.equal(renders.length, 1);
  }

  // test: manualCloseCancel clears it
  {
    const {ctx, S, renders} = makeCtx(true);
    S.manualCloseDraft[1474] = true;
    ctx.manualCloseCancel(1474);
    assert.equal(S.manualCloseDraft[1474], undefined, 'manualCloseCancel must delete the draft flag');
    assert.equal(renders.length, 1);
  }

  console.log('T_manual_close_trigger: confirm gate, open, cancel PASS');
}
main();
