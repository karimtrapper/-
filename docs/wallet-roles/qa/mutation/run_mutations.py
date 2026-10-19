"""Мутационная проверка QA-тестов ролей кошельков (только на временной копии).

Запуск (официальный фенс-раннер копии, интерпретатор — Python 3.11 venv):
  /tmp/s27-venv311/bin/python run_mutations.py <worktree> <outdir> [mutant ...]

Для каждого мутанта: копия дерева -> одна точная правка app.py -> фенс-pytest на
выбранных тестах. Ожидание: мутант «убит» (есть упавшие тесты). Исходное дерево не меняется.
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SRC = Path(sys.argv[1]).resolve()
OUT = Path(sys.argv[2]).resolve()
ONLY = set(sys.argv[3:])
T = 'tests/test_wallet_roles_'

MUTANTS = {
 'M1-self-confirm-id-guard': ('app.py',
  "        if claim.get('byId') == actor_id:\n            return jsonify(success=False, error='Нельзя подтвердить собственную отправку'), 403\n        user = db.query(AdminUser)",
  "        if False:\n            return jsonify(success=False, error='Нельзя подтвердить собственную отправку'), 403\n        user = db.query(AdminUser)",
  [T + 'confirm_qa.py'], 'role_change_of_same_actor'),
 'M2-settle-needs-confirmation': ('app.py',
  "not claim.get('byId') or not confirmation.get('byId')):",
  "not claim.get('byId')):",
  [T + 'confirm_qa.py'], 'rejects_confirmation_without_actor_id'),
 'M3-settle-owner-alone-validation': ('app.py',
  "            if (claim.get('byId') != confirmation.get('byId') or\n                    claim.get('role') != 'teodor' or not policy['wallet'].owner_can_alone):\n                return False",
  "            pass",
  [T + 'confirm_qa.py'], 'forged_owner_alone_marker'),
 'M4-settle-self-confirmation': ('app.py',
  "        elif claim.get('byId') == confirmation.get('byId'):\n            return False",
  "        elif False:\n            return False",
  [T + 'confirm_qa.py'], 'self_confirmation_marker'),
 'M5-put-guard-transfer-markers': ('app.py',
  "('transferClaim', 'transferConfirmation', 'transferOwnerApproval')):",
  "('__qa_none__',)):",
  [T + 'claim_qa.py', T + 'confirm_qa.py'], 'forge'),
 'M6-put-guard-recipient-warnings': ('app.py',
  "        if before.get('recipientWarnings') != deal.get('recipientWarnings'):",
  "        if False:",
  [T + 'payin_qa.py'], 'forged_state_put'),
 'M7-claim-role-eligibility': ('app.py',
  "or user.role != actor or actor not in roles:",
  "or user.role != actor:",
  [T + 'claim_qa.py'], 'other_roles'),
 'M8-claim-limit-inclusive': ('app.py',
  "policy['amount'] > Decimal(str(policy['wallet'].limit_usd))",
  "policy['amount'] >= Decimal(str(policy['wallet'].limit_usd))",
  [T + 'claim_qa.py'], 'limit_is_inclusive'),
 'M9-crm-approval-required': ('app.py',
  "    if data.get('payout_owner_approved') is not True:\n        return (_EXCHANGE_APPROVAL_ERROR, 400)",
  "    if False:\n        return (_EXCHANGE_APPROVAL_ERROR, 400)",
  [T + 'crm_qa.py'], 'over_limit_without_flag'),
 'M10-crm-approver-role': ('app.py',
  "    if (role not in ('findir', 'teodor') or not user or user.login_disabled\n            or user.role != role):",
  "    if (not user):",
  [T + 'crm_qa.py'], 'other_roles'),
 'M11-crm-limit-inclusive': ('app.py',
  "    if amount <= Decimal(str(wallet.limit_usd or 10000)):",
  "    if amount < Decimal(str(wallet.limit_usd or 10000)):",
  [T + 'crm_qa.py'], 'inclusive'),
 'M12-tron-receiver-case-insensitive': ('app.py',
  "else actual_receiver != receiver)",
  "else actual_receiver.lower() != receiver.lower())",
  [T + 'payin_qa.py'], 'case_sensitive'),
}

IGNORE = shutil.ignore_patterns('.git', '__pycache__', '.pytest_cache', 'node_modules', '*.pyc')


def run_copy(mutant, edit):
    work = Path(tempfile.mkdtemp(prefix='calccrm-mut-'))
    dst = work / 'repo'
    shutil.copytree(SRC, dst, ignore=IGNORE)
    if edit:
        fname, old, new, _, _ = edit
        path = dst / fname
        text = path.read_text()
        if text.count(old) != 1:
            shutil.rmtree(work, ignore_errors=True)
            return {'mutant': mutant, 'status': 'ANCHOR_NOT_FOUND', 'occurrences': text.count(old),
                    'killed': False}
        path.write_text(text.replace(old, new))
    # Все мутанты и контроль идут на ОДНОМ наборе файлов и порядке: у фикстур общая БД,
    # и узкая выборка (например, только CRM-файл) меняет сборку и setup.
    tests = sorted({t for m_ in MUTANTS.values() for t in m_[3]})
    proc = subprocess.run([sys.executable, 'scripts/run_fenced_pytest.py', '-q', '--tb=short',
                           '-p', 'no:cacheprovider', *tests], cwd=dst,
                          capture_output=True, text=True, timeout=1800)
    logs = OUT / 'logs'
    logs.mkdir(parents=True, exist_ok=True)
    (logs / f'{mutant}.stdout.log').write_text(proc.stdout)
    (logs / f'{mutant}.stderr.log').write_text(proc.stderr)
    log = proc.stdout + proc.stderr
    failed = re.findall(r'^FAILED (\S+)', log, re.M)
    summary = (re.findall(r'\d+ (?:passed|failed)[^\n]*', log) or [''])[-1]
    fence = re.search(r'NETWORK_FENCE attempts=(\d+) unexpected=(\d+) report=(\S+)', log)
    fence_ok = bool(fence) and fence.group(2) == '0'
    shutil.rmtree(work, ignore_errors=True)
    res = {'mutant': mutant, 'status': 'mutated' if edit else 'baseline', 'exit': proc.returncode,
           'failed': failed, 'summary': summary, 'fence_ok': fence_ok,
           'fence': fence.group(0) if fence else None}
    if edit:
        hit = [f for f in failed if edit[4] in f]
        res.update(expected_witness=edit[4], witness_failures=hit,
                   incidental_failures=[f for f in failed if f not in hit],
                   killed=bool(hit) and fence_ok)
    return res


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    plan = [('BASELINE', None)] + [(k, v) for k, v in MUTANTS.items() if not ONLY or k in ONLY]
    for name, edit in plan:
        res = run_copy(name, edit)
        results.append(res)
        print(name, res.get('status'), 'exit=%s' % res.get('exit'), 'fence_ok=%s' % res.get('fence_ok'),
              'killed=%s' % res.get('killed'), res.get('summary'), flush=True)
        (OUT / 'mutation-results.json').write_text(json.dumps(results, ensure_ascii=False, indent=1))
        if name == 'BASELINE' and not (res['exit'] == 0 and res['fence_ok']):
            print('BASELINE_NOT_GREEN: мутации не запускались; смотрите logs/BASELINE.*.log', flush=True)
            sys.exit(2)
    bad = [r['mutant'] for r in results[1:] if not r.get('killed')]
    print('SURVIVORS_OR_UNPROVEN:', bad or 'none')
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
