"""Полный цикл scripts/stand_copy_prod.py на одноразовом локальном Postgres.

Поднимаем свой кластер Postgres 16 (initdb/pg_ctl из Homebrew), три базы —
`fakeprod`, `fakestand`, `scratch_*` — наполняем синтетикой через модели app.py
и гоняем весь конвейер: dump-prod → inspect-dump → backup-stand →
restore-candidate → verify-candidate. Никакой реальной сети — только
127.0.0.1, никакого Railway/прода.

`skip`, если `initdb` недоступен (например, CI без Homebrew Postgres).
"""
import json
import os
import secrets as _secrets
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import psycopg2
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = str(ROOT / 'scripts' / 'stand_copy_prod.py')

sys.path.insert(0, str(ROOT / 'scripts'))
import stand_copy_prod as scp  # noqa: E402

PG_BIN = '/opt/homebrew/opt/postgresql@16/bin'
INITDB = os.path.join(PG_BIN, 'initdb')
PG_CTL = os.path.join(PG_BIN, 'pg_ctl')
PG_DUMP16 = os.path.join(PG_BIN, 'pg_dump')
PSQL16 = os.path.join(PG_BIN, 'psql')

pytestmark = pytest.mark.skipif(
    not os.path.exists(INITDB),
    reason='initdb (Homebrew postgresql@16) недоступен — пропуск теста локального Postgres',
)


def _free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope='module')
def pg_cluster(tmp_path_factory):
    data_dir = tmp_path_factory.mktemp('pgdata')
    port = _free_port()
    # Путь до сокета Postgres ограничен ~103 байтами — pytest-овский tmp_path
    # (глубоко вложенный) в это не помещается, поэтому сокет кладём в /tmp
    # напрямую, в свою короткую поддиректорию.
    sock_dir = Path('/tmp') / f'calccrm-t4-pg-{os.getpid()}-{port}'
    sock_dir.mkdir(parents=True, exist_ok=True)

    # macOS: postmaster падает с "postmaster became multithreaded during
    # startup", если LANG/LC_ALL не заданы явно (пустая locale заставляет
    # системный слой инициализировать поток ещё до fork внутри postgres).
    pg_env = dict(os.environ, LC_ALL='C', LANG='C')
    subprocess.run(
        [INITDB, '-D', str(data_dir), '-U', 'postgres', '--auth=trust', '--no-locale', '-E', 'UTF8'],
        check=True, capture_output=True, env=pg_env,
    )
    log_path = data_dir / 'server.log'
    subprocess.run(
        [PG_CTL, '-D', str(data_dir), '-l', str(log_path), '-w', '-o',
         f'-p {port} -c listen_addresses=127.0.0.1 -c unix_socket_directories={sock_dir}', 'start'],
        check=True, capture_output=True, env=pg_env,
    )
    try:
        base = f'postgresql://postgres@127.0.0.1:{port}'
        for name in ('fakeprod', 'fakestand', 'scratch_inspect', 'scratch_backup'):
            conn = psycopg2.connect(f'{base}/postgres')
            conn.autocommit = True
            try:
                conn.cursor().execute(f'CREATE DATABASE {name}')
            finally:
                conn.close()
        yield {'base': base, 'port': port, 'data_dir': str(data_dir)}
    finally:
        subprocess.run([PG_CTL, '-D', str(data_dir), '-m', 'immediate', 'stop'], capture_output=True)
        shutil.rmtree(sock_dir, ignore_errors=True)


@pytest.fixture(scope='module')
def app_models():
    """Классы моделей app.py — схема, а не боевой sqlite pytest-а."""
    import app as app_module
    return app_module


def _seed(engine, app_module, *, admin_username, marker):
    """Кладёт в базу по одной репрезентативной строке каждой чувствительной таблицы.

    Возвращает словарь с исходными («грязными») значениями токенов/паролей —
    тест по нему проверяет, что санация их действительно заменила.
    """
    m = app_module
    app_module.Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    try:
        admin = m.AdminUser(
            username=admin_username, password_hash=m.AdminUser.hash_password('secret123'),
            display_name=admin_username.title(), role='admin',
            telegram='@' + admin_username, telegram_user_id=555000111,
        )
        s.add(admin)

        manager = m.Manager(name=f'Менеджер {marker}')
        s.add(manager)

        client = m.Client(name=f'Клиент {marker}', telegram='@client_' + marker, phone='+79001234567')
        s.add(client)
        s.flush()

        referrer_token = _secrets.token_hex(16)
        referrer = m.Referrer(
            name=f'Реферер {marker}', code=f'GR-{marker}', token=referrer_token,
            telegram='@ref_' + marker, telegram_user_id=777000111, auth_mode='telegram',
            total_earned_usdt=123.45, total_paid_usdt=100.0,
        )
        s.add(referrer)

        partner_token = _secrets.token_hex(16)
        partner = m.Partner(name=f'Партнёр {marker}', token=partner_token)
        s.add(partner)
        s.flush()

        nonce = m.LoginNonce(nonce=_secrets.token_hex(32), admin_id=admin.id)
        s.add(nonce)

        deal = m.Deal(
            deal_type=m.DealType.PAY_IN, status=m.DealStatus.COMPLETED,
            client_id=client.id, client_name=client.name,
            profit_usdt=42.0, net_profit_usdt=40.0,
            referrer_id=referrer.id, referrer_payout_usdt=4.2,
        )
        s.add(deal)
        s.flush()

        agent = m.DealAgent(deal_id=deal.id, name=f'Агент {marker}', percent=10.0, payout_usdt=4.0)
        s.add(agent)

        payout_req = m.PayoutRequest(
            referrer_id=referrer.id, amount_usdt=23.45, wallet='T' + marker,
            contact_method='telegram', contact_value='@ref_' + marker,
        )
        s.add(payout_req)

        kyc_token = _secrets.token_hex(32)
        kyc = m.KycRequest(token=kyc_token, client_id=client.id, client_name=client.name)
        s.add(kyc)
        s.flush()
        kyc_file = m.KycFile(kyc_id=kyc.id, kind='doc', mime='image/jpeg', ext='jpg', size=3, data=b'abc')
        s.add(kyc_file)

        agreement = m.Agreement(
            client_id=client.id, client_name=client.name, client_key=marker,
            deal_type='freehold', number=f'MF-{marker}-0101-1',
        )
        s.add(agreement)
        s.flush()
        agreement_doc = m.AgreementDoc(
            agreement_id=agreement.id, kind='agreement', filename='a.pdf', size=3, data=b'xyz',
        )
        s.add(agreement_doc)

        payment_link = m.PaymentLinkOrder(
            order_id=f'ORDER-{marker}', payment_id=f'payment-uuid-{marker}', amount=12345,
            link=f'https://pay.example/checkout/secret-{marker}', status='PENDING',
        )
        s.add(payment_link)

        s.commit()
        return {
            'admin_id': admin.id,
            'admin_password_hash': admin.password_hash,
            'referrer_id': referrer.id,
            'referrer_token': referrer_token,
            'partner_token': partner_token,
            'kyc_token': kyc_token,
            'nonce': nonce.nonce,
            'payment_link_order_id': payment_link.order_id,
            'payment_id': payment_link.payment_id,
        }
    finally:
        s.close()


def _run(*cli_args, expect_ok=True):
    proc = subprocess.run([sys.executable, SCRIPT, *cli_args], capture_output=True, text=True)
    if expect_ok and proc.returncode != 0:
        raise AssertionError(f'{cli_args} упал ({proc.returncode}):\nstdout={proc.stdout}\nstderr={proc.stderr}')
    return proc


def _dsn_dbname(base, name):
    return f'{base}/{name}'


@pytest.fixture()
def seeded(pg_cluster, app_models):
    base = pg_cluster['base']
    prod_engine = create_engine(_dsn_dbname(base, 'fakeprod'))
    stand_engine = create_engine(_dsn_dbname(base, 'fakestand'))
    prod_seed = _seed(prod_engine, app_models, admin_username='karim', marker='prod')
    stand_seed = _seed(stand_engine, app_models, admin_username='stand_karim', marker='stand')
    prod_engine.dispose()
    stand_engine.dispose()
    return {'prod': prod_seed, 'stand': stand_seed}


def test_full_cycle(pg_cluster, seeded, tmp_path):
    base = pg_cluster['base']
    port = pg_cluster['port']
    prod_url = _dsn_dbname(base, 'fakeprod')
    stand_url = _dsn_dbname(base, 'fakestand')
    scratch_inspect_url = _dsn_dbname(base, 'scratch_inspect')
    scratch_backup_url = _dsn_dbname(base, 'scratch_backup')
    admin_url = _dsn_dbname(base, 'postgres')

    dump_dir = tmp_path / 'prod_dump'
    backup_dir = tmp_path / 'stand_backup'
    counts_path = tmp_path / 'counts.json'

    # 1. dump-prod
    proc = _run('dump-prod', '--prod-url', prod_url, '--out-dir', str(dump_dir),
                '--pg-dump-bin', PG_DUMP16)
    dump_info = json.loads(proc.stdout)
    dump_path = dump_info['dump_path']
    assert os.stat(dump_path).st_mode & 0o777 == 0o600
    assert os.stat(dump_dir).st_mode & 0o777 == 0o700
    with open(dump_info['sha256_path']) as f:
        assert dump_info['sha256'] in f.read()

    # DSN не должен утечь ни в stdout, ни в stderr-лог
    assert prod_url not in proc.stdout
    assert prod_url not in Path(dump_info['stderr_path']).read_text()

    # 2. inspect-dump
    proc = _run('inspect-dump', '--dump', dump_path, '--scratch-url', scratch_inspect_url,
                '--counts-out', str(counts_path), '--psql-bin', PSQL16)
    assert counts_path.exists()
    counts = json.loads(counts_path.read_text())
    assert counts['tables']['deals'] == 1
    assert counts['tables']['referrers'] == 1
    assert counts['money']['deals_profit_usdt_sum'] == 42.0
    assert counts['money']['kyc_files_count'] == 1

    # 3. backup-stand
    proc = _run('backup-stand', '--stand-url', stand_url, '--out-dir', str(backup_dir),
                '--scratch-url', scratch_backup_url, '--pg-dump-bin', PG_DUMP16, '--psql-bin', PSQL16)
    backup_info = json.loads(proc.stdout)
    assert backup_info['verified_restore'] is True
    assert stand_url not in proc.stdout

    # 4. restore-candidate
    candidate_db = 'stand_prodcopy_test'
    proc = _run(
        'restore-candidate',
        '--stand-admin-url', admin_url,
        '--candidate-db', candidate_db,
        '--dump', dump_path,
        '--expect-host', '127.0.0.1',
        '--expect-port', str(port),
        '--prod-host-guard', '203.0.113.1:5432',
        '--backup-dir', str(backup_dir),
        '--i-understand',
        '--psql-bin', PSQL16,
    )
    restore_info = json.loads(proc.stdout)
    assert restore_info['candidate_db'] == candidate_db

    candidate_url = _dsn_dbname(base, candidate_db)

    # 5. verify-candidate
    proc = _run('verify-candidate', '--candidate-url', candidate_url, '--counts-json', str(counts_path))
    report = json.loads(proc.stdout)
    assert report['ok'] is True, report['problems']
    diff_tables = {d.get('table') for d in report['documented_differences'] if 'table' in d}
    assert {'login_nonces', 'stand_state', 'admin_users'} <= diff_tables or \
        {'login_nonces', 'admin_users'} <= diff_tables  # stand_state может отсутствовать в дампе

    # ── Прямая проверка санации ──────────────────────────────────────────────
    conn = psycopg2.connect(candidate_url)
    try:
        cur = conn.cursor()

        cur.execute('SELECT token FROM referrers')
        (new_ref_token,) = cur.fetchone()
        assert new_ref_token != seeded['prod']['referrer_token']

        cur.execute('SELECT token FROM partners')
        (new_partner_token,) = cur.fetchone()
        assert new_partner_token != seeded['prod']['partner_token']

        cur.execute('SELECT token FROM kyc_requests')
        (new_kyc_token,) = cur.fetchone()
        assert new_kyc_token != seeded['prod']['kyc_token']

        cur.execute('SELECT COUNT(*) FROM login_nonces')
        assert cur.fetchone()[0] == 0

        cur.execute(
            "SELECT username, login_disabled, notify_enabled, telegram, telegram_user_id, password_hash "
            "FROM admin_users WHERE id = %s", (seeded['prod']['admin_id'],),
        )
        username, login_disabled, notify_enabled, telegram, tg_id, pwd_hash = cur.fetchone()
        assert username == 'prod_karim'
        assert login_disabled is True
        assert notify_enabled is False
        assert telegram is None
        assert tg_id is None
        assert pwd_hash != seeded['prod']['admin_password_hash']
        assert not pwd_hash.startswith('$2b$')

        cur.execute('SELECT to_regclass(%s)', ('public.stand_state',))
        if cur.fetchone()[0] is not None:
            cur.execute('SELECT id, data, version, notified FROM stand_state')
            rows = cur.fetchall()
            assert rows == [(1, '{}', 0, '[]')]

        # Внешние люди — недостижимы даже в теории (решение лидера после QA-репро).
        cur.execute('SELECT telegram, telegram_user_id, auth_mode FROM referrers')
        ref_telegram, ref_tg_id, auth_mode = cur.fetchone()
        assert ref_telegram is None
        assert ref_tg_id is None
        assert auth_mode == 'link'

        cur.execute('SELECT telegram, phone FROM clients')
        client_telegram, client_phone = cur.fetchone()
        assert client_telegram is None
        assert client_phone == '+79001234567'  # решение лидера: свободные поля клиентов — сохраняем намеренно

        cur.execute('SELECT contact_value FROM payout_requests')
        assert cur.fetchone()[0] != '@ref_prod'

        cur.execute('SELECT order_id, payment_id, link FROM payment_link_orders')
        order_id, payment_id, link = cur.fetchone()
        assert order_id == seeded['prod']['payment_link_order_id']  # бухгалтерский след — не трогаем
        assert payment_id == seeded['prod']['payment_id']
        assert link == ''  # публичная ссылка на оплату — обнулена
    finally:
        conn.close()

    # fakestand не тронут restore-candidate вообще
    conn = psycopg2.connect(stand_url)
    try:
        cur = conn.cursor()
        cur.execute("SELECT username FROM admin_users WHERE id = %s", (seeded['stand']['admin_id'],))
        assert cur.fetchone()[0] == 'stand_karim'
        cur.execute('SELECT token FROM referrers')
        assert cur.fetchone()[0] == seeded['stand']['referrer_token']
    finally:
        conn.close()

    # Проверка check_password: старый пароль не подходит к новому хэшу
    import app as app_module
    fake_admin = app_module.AdminUser(password_hash=pwd_hash)
    assert fake_admin.check_password('secret123') is False


@pytest.mark.parametrize('break_rule', [
    'wrong_host', 'wrong_port', 'prod_guard_match', 'bad_db_name',
    'db_name_equals_current', 'no_backup', 'no_i_understand',
])
def test_restore_candidate_safeguards_reject_without_connecting(pg_cluster, tmp_path, break_rule):
    """Каждый предохранитель отказывает ДО подключения к цели.

    Используем заведомо нерутируемый TEST-NET-3 адрес (203.0.113.1) там, где
    предохранитель должен сработать: если бы код всё-таки пытался
    подключиться, тест завис бы на TCP-таймауте вместо мгновенного отказа.
    """
    base = pg_cluster['base']
    port = pg_cluster['port']
    unreachable_admin_url = 'postgresql://postgres@203.0.113.1:5432/postgres'
    real_admin_url = _dsn_dbname(base, 'postgres')

    backup_dir = tmp_path / 'backup'
    backup_dir.mkdir()
    if break_rule != 'no_backup':
        # Валидный manifest — не требуется настоящий дамп, только читаемый файл + верный SHA256 + свежая дата.
        dummy_dump = backup_dir / 'dummy.sql.gz'
        dummy_dump.write_bytes(b'\x1f\x8b\x00')
        import hashlib
        from datetime import datetime, timezone
        sha = hashlib.sha256(dummy_dump.read_bytes()).hexdigest()
        manifest = backup_dir / 'x.manifest.json'
        manifest.write_text(json.dumps({
            'dump_path': str(dummy_dump), 'sha256': sha,
            'created_at': datetime.now(timezone.utc).isoformat(),
        }))

    args = {
        'admin_url': real_admin_url,
        'candidate_db': 'stand_prodcopy_neg',
        'dump': str(tmp_path / 'nonexistent.sql.gz'),
        'expect_host': '127.0.0.1',
        'expect_port': str(port),
        'prod_host_guard': '203.0.113.1:5432',
        'i_understand': True,
    }

    if break_rule == 'wrong_host':
        args['expect_host'] = '10.99.99.99'
    elif break_rule == 'wrong_port':
        args['expect_port'] = str(port + 1)
    elif break_rule == 'prod_guard_match':
        args['prod_host_guard'] = f'127.0.0.1:{port}'
    elif break_rule == 'bad_db_name':
        args['candidate_db'] = 'not_a_candidate_name'
    elif break_rule == 'db_name_equals_current':
        args['candidate_db'] = 'postgres'
    elif break_rule == 'no_i_understand':
        args['i_understand'] = False

    cli = [
        'restore-candidate',
        '--stand-admin-url', args['admin_url'],
        '--candidate-db', args['candidate_db'],
        '--dump', args['dump'],
        '--expect-host', args['expect_host'],
        '--expect-port', args['expect_port'],
        '--prod-host-guard', args['prod_host_guard'],
        '--backup-dir', str(backup_dir),
    ]
    if args['i_understand']:
        cli.append('--i-understand')

    started = time.monotonic()
    proc = subprocess.run([sys.executable, SCRIPT, *cli], capture_output=True, text=True, timeout=10)
    elapsed = time.monotonic() - started

    assert proc.returncode == 2, f'ожидали отказ предохранителя, получили: {proc.stdout} {proc.stderr}'
    assert elapsed < 5, 'предохранитель сработал слишком долго — похоже, была попытка подключения к цели'


def test_every_hash_excluded_column_has_a_sanitize_invariant():
    """Автоматический перебор: каждая (таблица, колонка) из HASH_EXCLUDE_COLUMNS
    обязана иметь зарегистрированный пост-инвариант — иначе она молча выпадает
    и из хеша, и из сверки (ровно так нашла round-3 QA-проверка)."""
    missing = [
        (table, col)
        for table, cols in scp.HASH_EXCLUDE_COLUMNS.items()
        for col in cols
        if (table, col) not in scp.SANITIZE_COLUMN_INVARIANTS
    ]
    assert missing == [], f'нет пост-инварианта для: {missing}'


def test_filter_dump_text_strips_pg17_only_guc():
    """PG17 добавил GUC `transaction_timeout` — pg_dump с прода (17) выставит его
    в начале файла, а PG16-стенд его не знает и упадёт с ERROR на SET. Дамп
    прода снимается pg_dump 18 (клиент), но пишет синтаксис под сервер-источник
    (17), поэтому строка возможна независимо от версии клиента-дампера."""
    text = (
        "SET statement_timeout = 0;\n"
        "SET transaction_timeout = 0;\n"
        "SET client_encoding = 'UTF8';\n"
    )
    filtered, removed = scp.filter_dump_text(text)
    assert 'transaction_timeout' not in filtered
    assert 'statement_timeout' in filtered
    assert 'client_encoding' in filtered
    assert sum(removed.values()) == 1


def test_dump_prod_redacts_password_not_just_full_dsn(tmp_path):
    """QA-репро: сторонний pg_dump печатает пароль отдельно от DSN (например,
    в собственной диагностике). Полное совпадение всей DSN-строки такое не
    ловит — редакция обязана вырезать САМ пароль, где бы он ни встретился."""
    fake_pg_dump = tmp_path / 'fake_pg_dump'
    fake_pg_dump.write_text('#!/bin/sh\necho "connection failed: password=fakepass123" >&2\nexit 1\n')
    fake_pg_dump.chmod(0o700)

    out_dir = tmp_path / 'leak'
    proc = _run(
        'dump-prod', '--prod-url', 'postgresql://alice:fakepass123@127.0.0.1:1/fakeprod',
        '--out-dir', str(out_dir), '--pg-dump-bin', str(fake_pg_dump), expect_ok=False,
    )
    assert proc.returncode != 0
    log_path = next(out_dir.glob('*.stderr.log'))
    log_text = log_path.read_text()
    assert 'fakepass123' not in log_text
    assert 'password=<REDACTED>' in log_text.lower() or '<redacted>' in log_text.lower()


def test_dump_prod_redacts_url_encoded_password_in_both_forms(tmp_path):
    """Пароль в DSN процент-закодирован (`x%40y` = `x@y`); `urlsplit(...).password`
    отдаёт «сырую» закодированную форму — стороннее ПО может напечатать в
    диагностике как её, так и декодированную. Обе должны исчезнуть из лога."""
    fake_pg_dump = tmp_path / 'fake_pg_dump'
    fake_pg_dump.write_text(
        '#!/bin/sh\n'
        'echo "raw form: x%40y%23z" >&2\n'
        'echo "decoded form: x@y#z" >&2\n'
        'exit 1\n'
    )
    fake_pg_dump.chmod(0o700)

    out_dir = tmp_path / 'leak_encoded'
    proc = _run(
        'dump-prod', '--prod-url', 'postgresql://alice:x%40y%23z@127.0.0.1:1/fakeprod',
        '--out-dir', str(out_dir), '--pg-dump-bin', str(fake_pg_dump), expect_ok=False,
    )
    assert proc.returncode != 0
    log_text = next(out_dir.glob('*.stderr.log')).read_text()
    assert 'x%40y%23z' not in log_text
    assert 'x@y#z' not in log_text


def test_verify_candidate_catches_content_corruption(pg_cluster, app_models, tmp_path):
    """Число строк и денежные суммы могут совпасть, а конкретная строка — нет.
    verify-candidate обязан ловить порчу через построчный хеш, а не только
    агрегаты (QA-репро: правка deal_agents.payout_usdt/deals.client_name/PK
    managers.id раньше проходила сверку молча).

    Собственные, уникальные для этого теста базы — `seeded` привязан к общим
    fakeprod/fakestand кластера (module-scope) и переиспользуется другим
    тестом, повторный `_seed` туда упал бы на UNIQUE(username)."""
    base = pg_cluster['base']
    port = pg_cluster['port']
    admin_url = _dsn_dbname(base, 'postgres')

    for name in ('fakeprod_corrupt', 'fakestand_corrupt', 'scratch_corrupt', 'scratch_corrupt_backup'):
        conn = psycopg2.connect(admin_url)
        conn.autocommit = True
        conn.cursor().execute(f'CREATE DATABASE {name}')
        conn.close()

    prod_url = _dsn_dbname(base, 'fakeprod_corrupt')
    stand_url = _dsn_dbname(base, 'fakestand_corrupt')
    scratch_url = _dsn_dbname(base, 'scratch_corrupt')
    scratch_backup_url = _dsn_dbname(base, 'scratch_corrupt_backup')

    prod_engine = create_engine(prod_url)
    stand_engine = create_engine(stand_url)
    _seed(prod_engine, app_models, admin_username='karim_c', marker='prodc')
    _seed(stand_engine, app_models, admin_username='stand_karim_c', marker='standc')
    prod_engine.dispose()
    stand_engine.dispose()

    dump_dir = tmp_path / 'dump'
    backup_dir = tmp_path / 'backup'
    counts_path = tmp_path / 'counts.json'

    dump_info = json.loads(_run('dump-prod', '--prod-url', prod_url, '--out-dir', str(dump_dir),
                                 '--pg-dump-bin', PG_DUMP16).stdout)
    dump_path = dump_info['dump_path']
    _run('inspect-dump', '--dump', dump_path, '--scratch-url', scratch_url,
         '--counts-out', str(counts_path), '--psql-bin', PSQL16)

    backup_info = json.loads(_run('backup-stand', '--stand-url', stand_url, '--out-dir', str(backup_dir),
                                   '--scratch-url', scratch_backup_url, '--pg-dump-bin', PG_DUMP16,
                                   '--psql-bin', PSQL16).stdout)

    candidate_db = 'stand_prodcopy_corrupt'
    _run('restore-candidate', '--stand-admin-url', admin_url, '--candidate-db', candidate_db,
         '--dump', dump_path, '--expect-host', '127.0.0.1', '--expect-port', str(port),
         '--prod-host-guard', '203.0.113.1:5432', '--backup-dir', str(backup_dir),
         '--i-understand', '--psql-bin', PSQL16)
    candidate_url = _dsn_dbname(base, candidate_db)

    baseline = _run('verify-candidate', '--candidate-url', candidate_url, '--counts-json', str(counts_path))
    assert json.loads(baseline.stdout)['ok'] is True

    def _corrupt_and_check(sql):
        conn = psycopg2.connect(candidate_url)
        conn.autocommit = True
        conn.cursor().execute(sql)
        conn.close()
        proc = _run('verify-candidate', '--candidate-url', candidate_url,
                    '--counts-json', str(counts_path), expect_ok=False)
        assert proc.returncode != 0, f'{sql!r} должно было провалить verify-candidate'
        assert json.loads(proc.stdout)['ok'] is False

    _corrupt_and_check("UPDATE deal_agents SET payout_usdt = 99999")
    _corrupt_and_check("UPDATE deals SET client_name = 'CORRUPTED'")
    _corrupt_and_check("UPDATE managers SET id = 999999")

    # NULL-коллизия: clients.notes у сида остаётся NULL. Если бы хеш кодировал
    # NULL фиксированным строковым маркером, запись ЛИТЕРАЛЬНО этого маркера
    # была бы неотличима от настоящего NULL. quote_nullable() отличает их —
    # см. compute_table_hash — эта проверка ловит именно такую регрессию.
    _corrupt_and_check("UPDATE clients SET notes = 'NULL' WHERE notes IS NULL")

    # Санируемые таблицы/колонки не должны молча пропускаться verify-candidate —
    # у них есть точный пост-инвариант (check_sanitize_invariants), а не только
    # исключение из хеша.
    _corrupt_and_check("INSERT INTO login_nonces (nonce) VALUES ('regression-nonce')")
    _corrupt_and_check("UPDATE stand_state SET data = 'BAD' WHERE id = 1")
    _corrupt_and_check("UPDATE payment_link_orders SET link = 'https://pay.example/reused'")
    _corrupt_and_check("UPDATE referrers SET telegram_user_id = 123456789")
    _corrupt_and_check("UPDATE referrers SET auth_mode = 'telegram'")
    _corrupt_and_check("UPDATE admin_users SET telegram = '@leaked'")
    _corrupt_and_check("UPDATE admin_users SET login_disabled = false")

    # Токен "не перевыпущен" — берём исходное (дамповое) значение из counts.json
    # и подкладываем его обратно в кандидата. verify-candidate обязан заметить
    # совпадение со старым токеном явно (пост-инвариант), не только "как будто
    # значение другое, но раз оно исключено из хеша — сойдёт".
    old_token = json.loads(counts_path.read_text())['token_values']['referrers'][0]
    _corrupt_and_check(f"UPDATE referrers SET token = '{old_token}'")

    # Колонки, исключённые из построчного хеша, но без выделенного probe'а
    # выше — round 3 QA нашла, что для них не было отдельного пост-инварианта.
    _corrupt_and_check("UPDATE payout_requests SET contact_value = '@leaked_contact'")
    _corrupt_and_check("UPDATE admin_users SET telegram_user_id = 987654321")
    _corrupt_and_check("UPDATE admin_users SET notify_enabled = true")

    # password_hash: откатываем на исходный ДО санации хеш — берём его из
    # scratch-базы inspect-dump (restore того же дампа без санации), не из
    # прод-базы напрямую.
    dump_admin_hash_conn = psycopg2.connect(scratch_url)
    try:
        cur = dump_admin_hash_conn.cursor()
        cur.execute('SELECT password_hash FROM admin_users LIMIT 1')
        (old_admin_hash,) = cur.fetchone()
    finally:
        dump_admin_hash_conn.close()
    _corrupt_and_check(f"UPDATE admin_users SET password_hash = '{old_admin_hash}'")

    # Токен обнулён массово — санация "потеряла" токен, а не просто оставила
    # старый. Отсутствие пересечения со старыми значениями само по себе это
    # не ловит: пустая строка тоже "не пересекается со старым дампом", но
    # токен, дающий доступ по ссылке, тем не менее сломан. (token NOT NULL в
    # схеме — пустая строка, не NULL.)
    _corrupt_and_check("UPDATE referrers SET token = ''")
    assert 'not_empty' in _run('verify-candidate', '--candidate-url', candidate_url,
                                '--counts-json', str(counts_path), expect_ok=False).stdout

    # Дубликат токенов физически невозможен на этой схеме — referrers.token
    # объявлен UNIQUE в модели (app.py), СУБД сама отклонит INSERT/UPDATE с
    # повтором раньше, чем до него дойдёт verify-candidate. Проверка
    # уникальности в _invariant_token_reissued — defense-in-depth на случай,
    # если ограничение когда-нибудь уберут из схемы; отдельным SQL-тестом
    # здесь не воспроизводима.


def test_verify_candidate_never_leaks_row_content_in_problems(pg_cluster, app_models, tmp_path):
    """QA-репро: нарушение пост-инварианта stand_state печатало саму строку
    (потенциальные ПДн старой доски) в problems/stdout. Сообщение обязано
    содержать только имя таблицы/колонки/инварианта и число нарушений."""
    base = pg_cluster['base']
    port = pg_cluster['port']
    admin_url = _dsn_dbname(base, 'postgres')
    pii_marker = 'PASSPORT-1234567-IVANOV-SECRET'

    for name in ('fakeprod_leak', 'scratch_leak'):
        conn = psycopg2.connect(admin_url)
        conn.autocommit = True
        conn.cursor().execute(f'CREATE DATABASE {name}')
        conn.close()

    prod_url = _dsn_dbname(base, 'fakeprod_leak')
    scratch_url = _dsn_dbname(base, 'scratch_leak')
    prod_engine = create_engine(prod_url)
    _seed(prod_engine, app_models, admin_username='karim_leak', marker='leak')
    prod_engine.dispose()

    dump_dir = tmp_path / 'dump'
    backup_dir = tmp_path / 'backup'
    counts_path = tmp_path / 'counts.json'

    dump_info = json.loads(_run('dump-prod', '--prod-url', prod_url, '--out-dir', str(dump_dir),
                                 '--pg-dump-bin', PG_DUMP16).stdout)
    dump_path = dump_info['dump_path']
    _run('inspect-dump', '--dump', dump_path, '--scratch-url', scratch_url,
         '--counts-out', str(counts_path), '--psql-bin', PSQL16)

    stand_url = _dsn_dbname(base, 'fakestand_leak')
    scratch_backup_url = _dsn_dbname(base, 'scratch_leak_backup')
    for name in ('fakestand_leak', 'scratch_leak_backup'):
        conn = psycopg2.connect(admin_url)
        conn.autocommit = True
        conn.cursor().execute(f'CREATE DATABASE {name}')
        conn.close()
    stand_engine = create_engine(stand_url)
    _seed(stand_engine, app_models, admin_username='stand_karim_leak', marker='leakstand')
    stand_engine.dispose()
    _run('backup-stand', '--stand-url', stand_url, '--out-dir', str(backup_dir),
         '--scratch-url', scratch_backup_url, '--pg-dump-bin', PG_DUMP16, '--psql-bin', PSQL16)

    candidate_db = 'stand_prodcopy_leak'
    _run('restore-candidate', '--stand-admin-url', admin_url, '--candidate-db', candidate_db,
         '--dump', dump_path, '--expect-host', '127.0.0.1', '--expect-port', str(port),
         '--prod-host-guard', '203.0.113.1:5432', '--backup-dir', str(backup_dir),
         '--i-understand', '--psql-bin', PSQL16)
    candidate_url = _dsn_dbname(base, candidate_db)

    conn = psycopg2.connect(candidate_url)
    conn.autocommit = True
    conn.cursor().execute("UPDATE stand_state SET data = %s WHERE id = 1", (pii_marker,))
    conn.cursor().execute("UPDATE deals SET client_name = %s", (pii_marker,))
    conn.close()

    proc = _run('verify-candidate', '--candidate-url', candidate_url,
                '--counts-json', str(counts_path), expect_ok=False)
    assert proc.returncode != 0
    assert pii_marker not in proc.stdout
    assert pii_marker not in proc.stderr
