// Назначенный коллеге шаг забирается только явным действием.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const html = fs.readFileSync('static/stand/tasks.html', 'utf8');
const names = ['employeeName', 'takeAssignee', 'assigneeBlock'];
const code = names.map(name => {
  const match = html.match(new RegExp(`^(?:async )?function ${name}\\([^]*?^}`, 'm'));
  assert.ok(match, `Нет функции ${name}`);
  return match[0];
}).join('\n');
const calls = [];
const ctx = {
  S: {role: 'manager'}, standMeId: 2, standVer: 9,
  STAND_EMPLOYEES: [{id: 1, role: 'manager', display_name: 'Анна'},
    {id: 2, role: 'manager', display_name: 'Борис'}],
  standAction: async (path, body) => { calls.push({path, body}); return {success: true}; },
  toast: () => {},
};
vm.createContext(ctx);
vm.runInContext(code, ctx);
const block = ctx.assigneeBlock({id: 1485, assigneeAdminId: 1}, 'manager');
assert.equal(block, '', 'назначение шага не показывается в новой карточке задачи');
ctx.takeAssignee(1485).then(() => {
  assert.equal(calls.length, 1);
  assert.equal(calls[0].path, '/api/stand/assignee/take');
  assert.equal(calls[0].body.dealId, 1485);
  assert.equal(calls[0].body.version, 9);
  console.log('assignee takeover: PASS');
}).catch(err => { console.error(err); process.exitCode = 1; });
