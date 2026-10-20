"""Независимый QA: неявное подтверждение чека на s26 — на копии реального дампа стенда.

  python3 scripts/qa_s26_dump_repro.py restore [--dump ФАЙЛ]   # по умолчанию — самый свежий
                                                                # по mtime *before-*.sql.gz
  python3 scripts/qa_s26_dump_repro.py run [сценарий ...] [--root ДЕРЕВО_ПРИЛОЖЕНИЯ]
  python3 scripts/qa_s26_dump_repro.py list

`restore` поднимает одноразовый Postgres 17 (только Unix-сокет, без TCP) в QA_S26_HOME
(по умолчанию /tmp/claude/s26), заливает дамп в базу-шаблон `s26` и пишет dump_meta.json
(имя, mtime, sha256 дампа). `run` клонирует шаблон на каждый сценарий
(CREATE DATABASE ... TEMPLATE), запускает приложение под sandbox-exec `(deny network*)`
с единственным исключением — наш сокет, плюс питоновский network_fence из
tests/network_bootstrap; фоновые опросы и интеграции выключены. Код выхода != 0, если
хоть одна проверка (check) не прошла. `--root` — другое дерево приложения (например,
`git archive HEAD` для красного прогона на базе). Сырой дамп и state.json содержат ПДн
и остаются ВНЕ репозитория; отчёт содержит только структуру, роли и идентификаторы.
"""
import argparse
import datetime
import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve()
TOOLS = HERE.parents[1]  # worktree: tests/network_bootstrap берём отсюда
HOME = Path(os.environ.get('QA_S26_HOME', '/tmp/claude/s26'))
SOCK = HOME / 'sock'
PG_BIN = Path(os.environ.get('QA_S26_PG_BIN', '/opt/homebrew/opt/postgresql@17/bin'))
VENV_PY = os.environ.get('QA_S26_PY', '/Users/karimamirov/worktrees/.venvs/calccrm-venv/bin/python')
BACKUPS = Path(os.environ.get('QA_S26_BACKUPS', '~/Backups/calccrm-stand')).expanduser()
DUMP_GLOB = 'stand_prodcopy_20260928-before-*.sql.gz'
TEMPLATE = 's26'
DEAL = 1483
ENV_LC = {**os.environ, 'LC_ALL': 'C'}

# Тексты go() из static/stand/tasks.html для s26 → s27.
GO_TEXTS = ('MT103 подтверждён, чек у менеджера — отправить клиенту и закрыть',
            'Оплачено, чек у менеджера — отправить клиенту и закрыть')


# ----------------------------------------------------------------- launcher
def pg(tool, *args, **kw):
    return subprocess.run([str(PG_BIN / tool), *map(str, args)], env=ENV_LC, text=True,
                          capture_output=True, **kw)


def scratch_verified():
    """Дропать базы разрешено только в нашем кластере: data_directory внутри HOME."""
    r = pg('psql', '-h', SOCK, '-U', 'qa', '-d', 'postgres', '-Atc', 'show data_directory')
    return r.returncode == 0 and Path(r.stdout.strip()).resolve() == (HOME / 'pgdata').resolve()


def drop_db(name):
    if not scratch_verified():
        sys.exit('отказ: сокет не принадлежит scratch-кластеру QA_S26_HOME')
    pg('dropdb', '-h', SOCK, '-U', 'qa', '--if-exists', name)


def latest_dump():
    files = sorted(glob.glob(str(BACKUPS / DUMP_GLOB)), key=os.path.getmtime)
    if not files:
        sys.exit(f'нет {DUMP_GLOB} в {BACKUPS}')
    return Path(files[-1])


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def cmd_restore(args):
    dump = Path(args.dump).expanduser() if args.dump else latest_dump()
    if not dump.exists():
        sys.exit(f'нет дампа {dump}')
    HOME.mkdir(parents=True, exist_ok=True)
    data = HOME / 'pgdata'
    if not data.exists():
        r = pg('initdb', '-D', data, '-A', 'trust', '-U', 'qa', '-E', 'UTF8', '--locale=C',
               '--no-instructions')
        if r.returncode:
            sys.exit(r.stdout + r.stderr)
    SOCK.mkdir(exist_ok=True)
    pg('pg_ctl', '-D', data, '-o', f'-k {SOCK} -h ""', '-l', HOME / 'pg.log', '-w', 'start')
    if not scratch_verified():
        sys.exit('scratch Postgres не поднялся')
    pg('dropdb', '-h', SOCK, '-U', 'qa', '--if-exists', TEMPLATE)
    r = pg('createdb', '-h', SOCK, '-U', 'qa', TEMPLATE)
    if r.returncode:
        sys.exit(r.stderr)
    zcat = subprocess.Popen(['gzip', '-dc', str(dump)], stdout=subprocess.PIPE)
    r = subprocess.run([str(PG_BIN / 'psql'), '-h', str(SOCK), '-U', 'qa', '-d', TEMPLATE, '-q'],
                       stdin=zcat.stdout, env=ENV_LC, capture_output=True, text=True)
    errors = [l for l in r.stderr.splitlines() if 'ERROR' in l]
    deals = pg('psql', '-h', SOCK, '-U', 'qa', '-d', TEMPLATE, '-Atc',
               'select count(*) from deals').stdout.strip()
    meta = {'dump': dump.name, 'mtime': datetime.datetime.fromtimestamp(
                dump.stat().st_mtime).isoformat(), 'sha256': sha256(dump),
            'restore_errors': len(errors), 'crm_deals': int(deals or 0)}
    (HOME / 'dump_meta.json').write_text(json.dumps(meta, indent=1))
    print(json.dumps(meta, indent=1))
    if errors:
        sys.exit(1)


def profile(work):
    own = str(Path(work).resolve())  # resolve() уже даёт /private/tmp/...
    sock = str(SOCK.resolve())
    return '\n'.join(['(version 1)', '(allow default)', '(deny network*)',
                      f'(allow network-outbound (regex #"^{sock}/"))',
                      f'(allow network-bind (regex #"^{own}/"))',
                      f'(allow network-outbound (regex #"^{own}/"))']) + '\n'


def run_scenario(name, root):
    db = f'{TEMPLATE}_{name}'
    drop_db(db)
    r = pg('createdb', '-h', SOCK, '-U', 'qa', '-T', TEMPLATE, db)
    if r.returncode:
        return {'scenario': name, 'ok': False, 'launcher_error': r.stderr.strip()}
    Path('/tmp/claude').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='s26qa-run-', dir='/tmp/claude') as work:
        prof = Path(work) / 'net.sb'
        prof.write_text(profile(work))
        ledger = Path(work) / 'attempts.jsonl'
        ledger.touch(mode=0o600)
        env = {k: os.environ[k] for k in ('PATH', 'LANG', 'TZ', 'S26_TRACE_DNS') if k in os.environ}
        env.update(LC_ALL='C', HOME=work, TMPDIR=work, PYTHON_DOTENV_DISABLED='1',
                   CALCCRM_FENCE_LEDGER=str(ledger), CALCCRM_FENCE_PORT_START='39905',
                   CALCCRM_FENCE_ACTIVE='1',
                   PYTHONPATH=str(TOOLS / 'tests' / 'network_bootstrap') + os.pathsep + str(root),
                   DATABASE_URL=f'postgresql://qa@/{db}?host={SOCK}',
                   STAND_MODE='1', SECRET_KEY='s26-qa', LOCAL_NO_AUTH='0',
                   STAND_FILES_LOCAL_DIR=str(Path(work) / 'objects'),
                   S26_SCENARIO=name, S26_ROOT=str(root))
        cmd = [shutil.which('sandbox-exec'), '-f', str(prof), VENV_PY, str(HERE), '--inner']
        r = subprocess.run(cmd, cwd=root, env=env, capture_output=True, text=True, timeout=900)
        attempts = [json.loads(x) for x in ledger.read_text().splitlines()]
    out = [l[7:] for l in r.stdout.splitlines() if l.startswith('RESULT ')]
    res = json.loads(out[-1]) if out else {'scenario': name, 'ok': False, 'no_result': True}
    unexpected = len([a for a in attempts if not a['expected']])
    res['egress_blocked'] = [l for l in (r.stdout + r.stderr).splitlines() if 'EGRESS-BLOCKED' in l][:5]
    res.update(exit=r.returncode, fence_unexpected=unexpected,
               fence_attempts=[{k: a.get(k) for k in ('kind', 'source')} for a in attempts])
    # Любая неожиданная попытка выхода в сеть (забор) — провал сценария, не «ожидаемое».
    if unexpected or r.returncode or not out:
        res['ok'] = False
        res['stderr_tail'] = r.stderr[-1200:]
    if os.environ.get('S26_TRACE_DNS'):
        res['stderr_tail'] = r.stderr[-6000:]
    drop_db(db)
    return res


def cmd_ui(args):
    """Рендер настоящих функций tasks.html на реальных фактах 1483 (после `run positive_real`);
    node — под тем же sandbox-exec «deny network*»."""
    facts = HOME / 'facts-1483.json'
    if not facts.exists():
        sys.exit('сначала: run positive_real')
    with tempfile.TemporaryDirectory(prefix='s26qa-ui-', dir='/tmp/claude') as work:
        prof = Path(work) / 'net.sb'
        prof.write_text('(version 1)\n(allow default)\n(deny network*)\n')
        env = {k: os.environ[k] for k in ('PATH', 'LANG', 'TZ') if k in os.environ}
        env.update(HOME=work, TMPDIR=work)
        r = subprocess.run([shutil.which('sandbox-exec'), '-f', str(prof), shutil.which('node'),
                            str(TOOLS / 'scripts' / 'qa_s26_ui_check.js'), str(facts)],
                           cwd=TOOLS, env=env, capture_output=True, text=True, timeout=120)
    print(r.stdout.strip() or r.stderr.strip()[-800:])
    sys.exit(r.returncode)


def cmd_run(args):
    root = Path(args.root).resolve() if args.root else TOOLS
    names = args.scenarios or list(SCENARIO_NAMES)
    meta_file = HOME / 'dump_meta.json'
    report = {'when': datetime.datetime.now().isoformat(timespec='seconds'), 'app_root': str(root),
              'dump': json.loads(meta_file.read_text()) if meta_file.exists() else None,
              'results': []}
    for name in names:
        res = run_scenario(name, root)
        report['results'].append(res)
        bad = [c for c in res.get('checks', []) if not c['ok']]
        print(('PASS ' if res.get('ok') else 'FAIL ') + name +
              (f' (fence_unexpected={res["fence_unexpected"]})' if res.get('fence_unexpected') else '') +
              ''.join(f'\n     x {c["label"]}: {c["detail"]}' for c in bad) +
              (f'\n     stderr: {res["stderr_tail"][-400:]}' if res.get('stderr_tail') else ''),
              flush=True)
    report['ok'] = all(r.get('ok') for r in report['results'])
    out = HOME / f'report-{root.name}-{datetime.datetime.now():%H%M%S}.json'
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print('report:', out)
    sys.exit(0 if report['ok'] else 1)


# ------------------------------------------------------------------- inner
CHECKS = []


def check(label, cond, detail=''):
    CHECKS.append({'label': label, 'ok': bool(cond), 'detail': '' if cond else str(detail)[:400]})
    return bool(cond)


def emit(name, **extra):
    print('RESULT ' + json.dumps({'scenario': name, 'ok': all(c['ok'] for c in CHECKS),
                                  'checks': CHECKS, **extra}, ensure_ascii=False, default=str),
          flush=True)


def user_id(m, role):
    db = m.get_session()
    try:
        return db.query(m.AdminUser.id).filter_by(role=role, login_disabled=False).order_by(
            m.AdminUser.id).first()[0]
    finally:
        db.close()


def client_for(m, role):
    client = m.app.test_client()
    with client.session_transaction() as sess:
        sess['user_id'] = user_id(m, role)
    return client


def deal_of(state):
    return next(d for d in state['deals'] if d['id'] == DEAL)


def load(m):
    db = m.get_session()
    try:
        row = db.query(m.StandState).filter_by(id=1).one()
        return json.loads(row.data), row.version
    finally:
        db.close()


def edit_db(m, fn):
    """Правка клона напрямую в БД (минуя PUT-guards) — построение сценария."""
    db = m.get_session()
    try:
        row = db.query(m.StandState).filter_by(id=1).one()
        state = json.loads(row.data)
        fn(m, deal_of(state), state, db, row)
        row.data = json.dumps(state, ensure_ascii=False)
        row.version += 1
        db.commit()
    finally:
        db.close()


def evidence_rows(m):
    db = m.get_session()
    try:
        return [(e.kind, e.provenance) for e in db.query(m.StandCloseEvidence).filter_by(
            stand_deal_id=DEAL).all()]
    finally:
        db.close()


def readiness(client):
    j = client.get(f'/api/stand/deals/{DEAL}/close-evidence').json
    return j, {f['kind']: f for f in j.get('facts', [])}


def crm_body(deal):
    """Форма CRM для freehold IPPS→SWIFT (значения из карточки, как их строит tasks.html)."""
    hashes = lambda items: [{'hash': h['hash'], 'network': 'trc20',
                             'amount_usdt': h['amount']} for h in items]
    mode = (deal.get('rubReceivingAccount') or {}).get('mode')
    return {'client_name': deal['client'], 'deal_kind': 'mf_freehold',
            'payin_method': 'flow_sole_reqs' if mode == 'flowsole' else 'sber_reqs',
            'payin_rate_rub_usdt': float(str(deal['rates']['broker']).replace(',', '.')),
            'payin_amount_rub': deal['incomeAmount'], 'payin_amount_usdt': deal['pay']['usdt'],
            'invoice_amount_usd': deal['invoiceUsd'], 'transfer_fee_percent': 1.5,
            'transfer_fee_fixed_usd': 50, 'transfer_sent_usd': deal['payout']['usdt'],
            'realty_purpose': (deal.get('payTo') or {}).get('purpose'),
            'payin_tx_hashes': hashes(deal['payinHashes']),
            'payout_tx_hashes': hashes(deal['payout']['hashes'])}


def close_as(m, role, crm_extra=None):
    state, version = load(m)
    crm = {**crm_body(deal_of(state)), **(crm_extra or {})}
    r = client_for(m, role).post(f'/api/stand/deals/{DEAL}/crm-close',
                                 json={'version': version, 'crm': crm})
    return r.status_code, (r.json or {})


def positions(deal):
    """Индексы записей s26-завершения в журнале (None — нет)."""
    log = deal.get('log') or []
    find = lambda pred: next((i for i, e in enumerate(log) if pred(e)), None)
    attach = find(lambda e: str(e.get('text', '')).startswith('Приложен файл: receipt'))
    go = find(lambda e: e.get('kind') == 'comment' and
              any(str(e.get('text', '')).endswith(t) for t in GO_TEXTS))
    step = find(lambda e: e.get('text') == 'Шаг передан дальше' and not e.get('kind'))
    return attach, go, step


def expect_blocked(m, label):
    """Закрытие невозможно: receipt не ready, crm-close менеджером — отказ, сделка открыта."""
    j, facts = readiness(client_for(m, 'manager'))
    receipt = facts.get('receipt', {})
    check(f'{label}: receipt не ready и в missing', receipt.get('ready') is False and
          'receipt' in (j.get('missing') or []), (j.get('missing'), receipt))
    check(f'{label}: нет implicit-метки', not receipt.get('implicit'), receipt)
    status, body = close_as(m, 'manager')
    check(f'{label}: crm-close блокирован', status >= 400 and not body.get('success'),
          (status, body.get('error')))
    check(f'{label}: сделка осталась открытой', not deal_of(load(m)[0]).get('closed'), '')
    return status, body.get('error')


def stale_row(m, generation):
    return m.StandCloseEvidence(generation=generation, stand_deal_id=DEAL, kind='receipt',
                                fingerprint='0' * 64, actor_id=12, provenance='operator_attestation',
                                confirmed_at=datetime.datetime(2026, 10, 1))


# ---- мутации клона -----------------------------------------------------------
def drop_files(m, deal, state, db, row):
    deal['files']['receipt'] = []
    deal['docs']['receipt'] = False


def drop_completion(m, deal, state, db, row):
    attach, go, step = positions(deal)
    deal['log'] = [e for i, e in enumerate(deal['log']) if i not in (go, step)]


def stale_explicit(m, deal, state, db, row):
    drop_completion(m, deal, state, db, row)
    db.add(stale_row(m, row.generation))


def file_after_completion(m, deal, state, db, row):
    """s26 завершён БЕЗ файла; запись о приложенном чеке — уже после «Шаг передан дальше»."""
    attach, go, step = positions(deal)
    deal['log'].append(deal['log'].pop(attach))


def manager_comment(m, deal, state, db, row):
    deal['log'][positions(deal)[1]]['role'] = 'manager'


def no_step_marker(m, deal, state, db, row):
    deal['log'].pop(positions(deal)[2])


def not_paid(m, deal, state, db, row):
    deal['pay']['invoicePaid'] = False


def no_attach_entry(m, deal, state, db, row):
    deal['log'].pop(positions(deal)[0])


def step_s26(m, deal, state, db, row):
    deal['step'] = 's26'


def mutate_blocked(name, label, fn):
    def run(m):
        edit_db(m, fn)
        status, error = expect_blocked(m, label)
        emit(name, status=status, error=error)
    return run


# ---- сценарии ---------------------------------------------------------------
def sc_positive_real(m):
    """Реальный дамп, как есть: s26 завершён оператором с MT103 → чек принят неявно."""
    state, _ = load(m)
    deal = deal_of(state)
    attach, go, step = positions(deal)
    check('исходник: step=s27, invoicePaid, файл receipt', deal['step'] == 's27' and
          deal['pay'].get('invoicePaid') and deal['files'].get('receipt'), deal['step'])
    check('исходник: в журнале attach < go < «Шаг передан дальше»',
          None not in (attach, go, step) and attach < go < step, (attach, go, step))
    check('исходник: receipt-подтверждения в stand_close_evidence нет',
          not any(k == 'receipt' for k, _ in evidence_rows(m)), evidence_rows(m))
    entry = deal['log'][go]
    author = entry.get('author')
    j0, _ = readiness(client_for(m, 'manager'))
    # реальный ответ API → scripts/qa_s26_ui_check.js (рендер настоящих функций tasks.html)
    (HOME / 'facts-1483.json').write_text(json.dumps({'version': j0['version'], 'facts': j0['facts'],
                                                      'author': author, 'at': entry['at']}))
    stamp = datetime.datetime.fromtimestamp(entry['at'] / 1000, datetime.timezone.utc
                                            ).strftime('%Y-%m-%dT%H:%M:%S')
    for role in ('manager', 'operator'):
        j, facts = readiness(client_for(m, role))
        r = facts.get('receipt', {})
        check(f'{role}: missing == []', j.get('missing') == [], j.get('missing'))
        check(f'{role}: receipt ready, источник operator_attestation',
              r.get('ready') and r.get('source') == 'operator_attestation', r)
        check(f'{role}: implicit, кто={author!r}, роль operator',
              r.get('implicit') is True and r.get('confirmed_by') == author and
              r.get('confirmed_role') == 'operator', r)
        check(f'{role}: время = время s26-записи журнала ({stamp}Z)',
              str(r.get('checked_at', '')).startswith(stamp), r.get('checked_at'))
    check('GET не бэкфиллит receipt-подтверждение',
          not any(k == 'receipt' for k, _ in evidence_rows(m)), evidence_rows(m))
    status, body = close_as(m, 'manager')
    check('менеджер: crm-close успешен (201)', status == 201 and body.get('success'),
          (status, body.get('error'), body.get('details')))
    closed = deal_of(load(m)[0])
    check('сделка закрыта и привязана к CRM', closed.get('closed') and closed.get('crmDealId'),
          closed.get('closeReason'))
    check('закрытие не создаёт receipt-подтверждения',
          not any(k == 'receipt' for k, _ in evidence_rows(m)), evidence_rows(m))
    emit('positive_real', author=author, close_status=status)


def sc_operator_cannot_close(m):
    status, body = close_as(m, 'operator')
    check('operator: crm-close запрещён (403)', status == 403, (status, body.get('error')))
    emit('operator_cannot_close')


def sc_explicit_receipt_without_completion(m):
    """Явное operator-подтверждение чека БЕЗ завершённого s26 не открывает закрытие."""
    edit_db(m, drop_completion)
    _, version = load(m)
    r = client_for(m, 'operator').post(f'/api/stand/deals/{DEAL}/close-evidence',
                                       json={'version': version, 'kind': 'receipt'})
    status, error = expect_blocked(m, f'явный receipt-POST (HTTP {r.status_code}) без завершения s26')
    emit('explicit_receipt_without_completion', post_status=r.status_code,
         post_error=(r.json or {}).get('error'), close_error=error)


def sc_receipt_swapped(m):
    """После s26 чек подменили другим валидным файлом — приёмка не должна «переехать» на него."""
    def swap(m, deal, state, db, row):
        deal['files']['receipt'] = [dict(deal['files']['bankCreditEvidence'][0])]
    edit_db(m, swap)
    j, facts = readiness(client_for(m, 'manager'))
    check('подмена файла чека после завершения s26 → НЕ ready', not facts['receipt'].get('ready'),
          facts['receipt'])
    emit('receipt_swapped_after_completion')


def sc_spoof_manager_put(m):
    """Менеджер через PUT не подделает ни s26Done, ни «операторские» записи журнала."""
    edit_db(m, drop_completion)
    mgr = client_for(m, 'manager')
    saved = mgr.get('/api/stand/state').json
    d = deal_of(saved['data'])
    d['s26Done'] = {'at': 1792389014706, 'byId': user_id(m, 'operator'), 'by': 'Forged',
                    'role': 'operator', 'receipts': ['x']}
    d['log'] = d['log'] + [{'at': 1, 'role': 'operator', 'author': 'Forged', 'kind': 'comment',
                            'text': GO_TEXTS[0]},
                           {'at': 2, 'role': 'operator', 'kind': 's26_completed', 'by': 'Forged',
                            'byId': user_id(m, 'operator'), 'text': 'Шаг передан дальше'},
                           {'at': 3, 'role': 'operator', 'text': 'Шаг передан дальше'}]
    r = mgr.put('/api/stand/state', json={'version': saved['version'], 'data': saved['data'],
                                         'fileStorageVersion': 1})
    stored = deal_of(load(m)[0])
    check('PUT менеджера отработал детерминированно (200/403/409)', r.status_code in (200, 403, 409),
          r.status_code)
    check('s26Done от менеджера не сохранён', (stored.get('s26Done') or {}).get('by') != 'Forged',
          stored.get('s26Done'))
    forged = [e for e in stored['log'] if 'Forged' in json.dumps(e, ensure_ascii=False)]
    check('поддельные записи не получили роль operator/admin и kind s26_completed',
          all(e.get('role') not in ('operator', 'admin') and e.get('kind') != 's26_completed'
              for e in forged), forged)
    expect_blocked(m, 'после spoof-PUT менеджера')
    emit('spoof_manager_put', put_status=r.status_code, put_error=(r.json or {}).get('error'))


def rewind_to_s26(m, deal, state, db, row):
    """Откат клона на момент «оператор ещё не оплатил/не приложил MT103»."""
    attach, go, step = positions(deal)
    deal['log'] = deal['log'][:attach]
    deal.update(step='s26', sentToClient=False, sentAt=None)
    deal['pay']['invoicePaid'] = False
    deal['payout'].pop('invoice', None)
    deal.pop('s26Done', None)
    for e in db.query(m.StandCloseEvidence).filter_by(stand_deal_id=DEAL).all():
        db.delete(e)


def put_state(client, saved, **changes):
    saved['data']['deals'] = [dict(d, **changes) if d['id'] == DEAL else d for d in saved['data']['deals']]
    return client.put('/api/stand/state', json={'version': saved['version'], 'data': saved['data'],
                                               'fileStorageVersion': 1})


def sc_live_s26_via_api(m):
    """Живой путь: оператор через PUT завершает s26 → сервер сам фиксирует завершение (подделка в
    теле затирается) → менеджер отмечает «чек отправлен» → crm-close успешен."""
    edit_db(m, rewind_to_s26)
    op = client_for(m, 'operator')
    saved = op.get('/api/stand/state').json
    d = saved and deal_of(saved['data'])
    log = d['log'] + [{'text': 'Подтверждение от IPPS: MT103 приложен — застройщику дошло $1'},
                      {'text': GO_TEXTS[0]}]
    payout = dict(d['payout'], invoice={'source': 'IPPS (SWIFT)', 'usd': d['invoiceUsd'],
                                        'to': 'x', 'at': 'n'})
    r = put_state(op, saved, step='s27', log=log, payout=payout, pay=dict(d['pay'], invoicePaid=True),
                  s26Done={'at': 1, 'byId': 999999, 'by': 'Forged', 'role': 'admin', 'receipts': ['x']})
    check('оператор: PUT s26→s27 принят', r.status_code == 200, (r.status_code, (r.json or {}).get('error')))
    stored = deal_of(load(m)[0])
    forged = [e for e in stored['log'] if 'Forged' in json.dumps(e, ensure_ascii=False)]
    check('подделка из тела PUT не сохранена', (stored.get('s26Done') or {}).get('by') != 'Forged' and
          not forged, (stored.get('s26Done'), forged))
    marks = [e for e in stored['log'] if e.get('kind') == 's26_completed'] or \
        ([stored['s26Done']] if stored.get('s26Done') else [])
    mark = marks[-1] if marks else {}
    check('сервер зафиксировал завершение s26 (byId=оператор, role=operator, receipts, at=сейчас)',
          mark.get('byId') == user_id(m, 'operator') and mark.get('role') == 'operator' and
          mark.get('receipts') and mark.get('at', 0) > 10 ** 12, mark)
    j, facts = readiness(client_for(m, 'manager'))
    check('receipt ready+implicit', facts['receipt'].get('ready') and facts['receipt'].get('implicit'),
          facts['receipt'])
    mgr = client_for(m, 'manager')
    saved = mgr.get('/api/stand/state').json
    r = put_state(mgr, saved, sentToClient=True, sentAt='20.10, 13:17')
    check('менеджер: sentToClient принят', r.status_code == 200, (r.status_code, (r.json or {}).get('error')))
    j, facts = readiness(client_for(m, 'manager'))
    check('все факты ready', j.get('missing') == [], (j.get('missing'), j.get('details')))
    status, body = close_as(m, 'manager')
    check('менеджер закрывает (201)', status == 201, (status, body.get('error'), body.get('details')))
    emit('live_s26_via_api', mark={k: mark.get(k) for k in ('kind', 'byId', 'role', 'at')})


def sc_live_forged_by_manager(m):
    """Менеджер не может «завершить» s26 за оператора: ни переход, ни подделка метки не засчитываются."""
    edit_db(m, rewind_to_s26)
    mgr = client_for(m, 'manager')
    saved = mgr.get('/api/stand/state').json
    d = deal_of(saved['data'])
    r = put_state(mgr, saved, step='s27', pay=dict(d['pay'], invoicePaid=True),
                  s26Done={'at': 1, 'byId': user_id(m, 'operator'), 'by': 'Forged',
                           'role': 'operator', 'receipts': []})
    j, facts = readiness(client_for(m, 'manager'))
    check('чек не принят от менеджерского «завершения»', not facts['receipt'].get('ready'),
          (r.status_code, facts['receipt']))
    emit('live_forged_by_manager', put_status=r.status_code)


def sc_regression_all_deals(m):
    """Не регрессируют ли ДРУГИЕ открытые сделки дампа: receipt-факт по каждой (сравнить base/candidate)."""
    state, _ = load(m)
    mgr = client_for(m, 'manager')
    table = {}
    for d in state['deals']:
        if d.get('type') != 'Оплата недвижимости' or d.get('closed') or d.get('originMode') == 'manual':
            continue
        j = mgr.get(f"/api/stand/deals/{d['id']}/close-evidence").json
        f = {x['kind']: x for x in j.get('facts', [])}.get('receipt', {})
        table[d['id']] = {'step': d.get('step'), 'ready': f.get('ready'), 'reason': f.get('reason'),
                          'implicit': f.get('implicit', False), 'missing': j.get('missing')}
    check('таблица построена', bool(table), table)
    emit('regression_all_deals', table=table)


SCENARIOS = {
    'regression_all_deals': sc_regression_all_deals,
    'positive_real': sc_positive_real,
    'operator_cannot_close': sc_operator_cannot_close,
    'neg_no_receipt_file': mutate_blocked('neg_no_receipt_file', 'нет файла чека', drop_files),
    'neg_no_s26_completion': mutate_blocked('neg_no_s26_completion', 'нет завершения s26',
                                            drop_completion),
    'neg_stale_explicit_no_completion': mutate_blocked(
        'neg_stale_explicit_no_completion', 'устаревшее явное + нет завершения', stale_explicit),
    'neg_file_added_after_completion': mutate_blocked(
        'neg_file_added_after_completion', 'файл добавлен после завершения', file_after_completion),
    'neg_manager_authored_completion': mutate_blocked(
        'neg_manager_authored_completion', 'запись завершения от менеджера', manager_comment),
    'neg_no_step_marker': mutate_blocked('neg_no_step_marker', 'нет «Шаг передан дальше»',
                                         no_step_marker),
    'neg_invoice_not_paid': mutate_blocked('neg_invoice_not_paid', 'invoicePaid=false', not_paid),
    'neg_no_attach_entry': mutate_blocked('neg_no_attach_entry', 'нет записи о приложенном чеке',
                                          no_attach_entry),
    'neg_step_s26': mutate_blocked('neg_step_s26', 'step=s26', step_s26),
    'explicit_receipt_without_completion': sc_explicit_receipt_without_completion,
    'receipt_swapped_after_completion': sc_receipt_swapped,
    'spoof_manager_put': sc_spoof_manager_put,
    'live_s26_via_api': sc_live_s26_via_api,
    'live_forged_by_manager': sc_live_forged_by_manager,
}
SCENARIO_NAMES = list(SCENARIOS)


def stub_external_delivery(app):
    """Как tests/conftest.py: внешняя доставка (GSheet, Telegram, webhook) — синтетический отказ
    транспорта ДО сокета; логика close/readiness не отключается."""
    import requests
    from urllib.parse import urlsplit
    real = {'get': requests.get, 'post': requests.post}
    local = ('localhost', '127.0.0.1', '::1')

    def guard(kind):
        def call(url, *a, **kw):
            if urlsplit(url).hostname not in local:
                raise requests.ConnectionError('synthetic external transport unavailable')
            return real[kind](url, *a, **kw)
        return call
    requests.get, requests.post = guard('get'), guard('post')
    app.get_gsheet_client = lambda: None
    import stand_egress
    # TronScan чтение (как фикстура conftest: «хеш не проиндексирован») — до сокета.
    stand_egress.read_get = lambda operation, *a, **kw: (404, None, 'http_4xx')


def trace_dns():
    """Диагностика (S26_TRACE_DNS=1): кто и какой хост резолвит."""
    import socket
    import traceback
    prev = socket.getaddrinfo

    def traced(host, *a, **kw):
        if host not in ('localhost', '127.0.0.1', None):
            print('DNSTRACE', host, ' <- '.join(f'{os.path.basename(f.filename)}:{f.lineno}:{f.name}'
                  for f in reversed(traceback.extract_stack(limit=16)[:-1])), file=sys.stderr)
        return prev(host, *a, **kw)
    socket.getaddrinfo = traced


def inner():
    sys.path.insert(0, os.environ['S26_ROOT'])
    import app
    stub_external_delivery(app)
    if os.environ.get('S26_TRACE_DNS'):
        trace_dns()
    SCENARIOS[os.environ['S26_SCENARIO']](app)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('action', nargs='?', choices=['restore', 'run', 'list', 'ui'])
    ap.add_argument('scenarios', nargs='*')
    ap.add_argument('--dump')
    ap.add_argument('--root')
    ap.add_argument('--inner', action='store_true')
    args = ap.parse_args()
    if args.inner:
        return inner()
    if args.action == 'list':
        return print('\n'.join(SCENARIO_NAMES))
    {'restore': cmd_restore, 'run': cmd_run, 'ui': cmd_ui}[args.action](args)


if __name__ == '__main__':
    main()
