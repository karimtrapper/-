#!/usr/bin/env python3
"""Копия прод-данных CalcCRM в кандидат-базу стенда + санация.

План: docs/PROD-LIKE-STAND-PLAN.md (раздел «Этап 4»). Пять подкоманд одного
скрипта — каждая самостоятельна, конвейер собирает их извне (см. README ниже):

    dump-prod         — read-only pg_dump прода в .sql.gz + SHA256
    inspect-dump       — restore дампа в одноразовую локальную базу, снятие
                          эталонных счётчиков (counts.json) для последующей сверки
    backup-stand       — pg_dump живого стенда + stand_state + список admin_users,
                          с проверочным restore
    restore-candidate  — создание stand_prodcopy_<дата>, restore дампа, санация
                          (только после всех предохранителей, БЕЗ подключения
                          к цели до их прохождения)
    verify-candidate   — сверка кандидата с эталоном (счётчики/FK/sequences/деньги)

Ни разу не подключается ни к Railway API, ни к живому стенду/проду напрямую —
только к URL-ам, которые лидер передаёт аргументами. Секреты (DSN) в коде не
хранятся, в stdout/логи не пишутся — только редактируются перед записью.
"""
import argparse
import gzip
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from urllib.parse import unquote, urlsplit, urlunsplit

import psycopg2

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SANITIZE_SQL_PATH = os.path.join(SCRIPT_DIR, 'stand_sanitize.sql')

DEFAULT_PG_DUMP_BIN = '/opt/homebrew/opt/libpq/bin/pg_dump'
DEFAULT_PSQL_BIN = 'psql'

# Строки дампа, которые pg_dump новой версии libpq может выпустить для источника
# новее целевой базы. Список пополняется по мере встречи новых GUC — сейчас
# единственный известный кейс: `transaction_timeout` (появился в PostgreSQL 17,
# стенд — PostgreSQL 16).
FILTERED_SET_PATTERNS = [
    (re.compile(r'^SET\s+transaction_timeout\s*=.*;\s*$', re.IGNORECASE),
     'transaction_timeout (GUC PostgreSQL 17+, отсутствует в PostgreSQL 16 и старше)'),
]

# Таблицы, которые санация меняет по содержимому/количеству осознанно —
# verify-candidate не должен ронять сверку из-за них, но обязан о них написать.
DOCUMENTED_DIFF_TABLES = {'login_nonces', 'stand_state'}

CANDIDATE_DB_RE = re.compile(r'^stand_prodcopy_[A-Za-z0-9_]+$')

# Токен-колонки, которые санация обязана перевыпустить. inspect-dump
# записывает их исходные значения в counts.json, verify-candidate проверяет,
# что ни одно из них не «просочилось» в кандидата как есть.
TOKEN_COLUMNS = {'partners': 'token', 'referrers': 'token', 'kyc_requests': 'token'}

MONEY_QUERIES = {
    'deals_profit_usdt_sum': ('deals', 'SELECT COALESCE(SUM(profit_usdt), 0) FROM deals'),
    'deals_net_profit_usdt_sum': ('deals', 'SELECT COALESCE(SUM(net_profit_usdt), 0) FROM deals'),
    'deals_payout_amount_usdt_sum': ('deals', 'SELECT COALESCE(SUM(payout_amount_usdt), 0) FROM deals'),
    'deals_referrer_payout_usdt_sum': ('deals', 'SELECT COALESCE(SUM(referrer_payout_usdt), 0) FROM deals'),
    'deal_agents_payout_usdt_sum': ('deal_agents', 'SELECT COALESCE(SUM(payout_usdt), 0) FROM deal_agents'),
    'referrers_total_earned_usdt_sum': ('referrers', 'SELECT COALESCE(SUM(total_earned_usdt), 0) FROM referrers'),
    'referrers_total_paid_usdt_sum': ('referrers', 'SELECT COALESCE(SUM(total_paid_usdt), 0) FROM referrers'),
    'payout_requests_amount_usdt_sum': ('payout_requests', 'SELECT COALESCE(SUM(amount_usdt), 0) FROM payout_requests'),
    'kyc_files_count': ('kyc_files', 'SELECT COUNT(*) FROM kyc_files'),
    'agreements_count': ('agreements', 'SELECT COUNT(*) FROM agreements'),
    'agreement_docs_count': ('agreement_docs', 'SELECT COUNT(*) FROM agreement_docs'),
}

# Колонки, которые санация меняет осознанно (см. stand_sanitize.sql) — не
# участвуют в построчном хеше содержимого таблицы, иначе verify-candidate
# всегда бы падал именно на них. Всё остальное содержимое таблицы обязано
# совпасть с эталоном побитово.
HASH_EXCLUDE_COLUMNS = {
    'partners': {'token'},
    'referrers': {'token', 'telegram', 'telegram_user_id', 'auth_mode'},
    'kyc_requests': {'token'},
    'clients': {'telegram'},
    'payment_link_orders': {'link'},
    'payout_requests': {'contact_value'},
    'admin_users': {'username', 'password_hash', 'telegram', 'telegram_user_id', 'login_disabled', 'notify_enabled'},
}



# ─────────────────────────── общие мелкие помощники ───────────────────────────

def _secrets_from_url(url):
    """DSN целиком + отдельно пароль из неё, в «сыром» и URL-декодированном виде.

    Сторонний pg_dump (или обёртка над ним) может напечатать пароль сам по
    себе, вне DSN (например `password=...` в диагностике) — редактировать
    только полную строку DSN недостаточно. `urlsplit(...).password` не
    декодирует percent-encoding (пароль `x@y` в DSN выглядит как `x%40y`),
    а диагностика может напечатать пароль в любой из двух форм.
    """
    if not url:
        return []
    out = [url]
    try:
        password = urlsplit(url).password
    except ValueError:
        password = None
    if password:
        out.append(password)
        decoded = unquote(password)
        if decoded != password:
            out.append(decoded)
    return out


def _redact(text, *urls):
    """Убирает DSN и пароль из текста перед тем, как он попадёт в файл или stdout."""
    out = text or ''
    for url in urls:
        for s in _secrets_from_url(url):
            out = out.replace(s, '<REDACTED>')
    out = re.sub(r'postgres(?:ql)?://[^\s\'"]+', '<REDACTED-DSN>', out)
    # Защита от «password=...»/PGPASSWORD в произвольном месте вывода —
    # не полагаемся только на разбор конкретного DSN, который нам передали.
    out = re.sub(r'(?i)\b(pg)?password\s*[=:]\s*\S+', lambda m: f'{m.group(1) or ""}password=<REDACTED>', out)
    return out


def _parse_dsn(url):
    parts = urlsplit(url)
    return {
        'host': parts.hostname,
        'port': parts.port,
        'dbname': (parts.path or '/').lstrip('/'),
    }


def _with_dbname(url, dbname):
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, '/' + dbname, parts.query, parts.fragment))


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _secure_mkdir(path):
    os.makedirs(path, exist_ok=True)
    os.chmod(path, 0o700)


def _write_secure_file(path, data_bytes):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'wb') as f:
        f.write(data_bytes)


def _write_json(path, obj):
    _write_secure_file(path, json.dumps(obj, ensure_ascii=False, indent=2, default=str).encode('utf-8'))


def _gzip_test(path):
    check = subprocess.run(['gzip', '-t', path], capture_output=True)
    if check.returncode != 0:
        raise RuntimeError(f'gzip -t не прошёл для {path}: {check.stderr.decode("utf-8", "replace")}')


def filter_dump_text(text):
    """Вырезает из текста дампа строки, несовместимые с целевой версией Postgres.

    Возвращает (отфильтрованный_текст, {описание: количество_убранных_строк}).
    """
    removed = {}
    out_lines = []
    for line in text.splitlines(keepends=True):
        stripped = line.strip('\n')
        matched = False
        for pattern, desc in FILTERED_SET_PATTERNS:
            if pattern.match(stripped):
                removed[desc] = removed.get(desc, 0) + 1
                matched = True
                break
        if not matched:
            out_lines.append(line)
    return ''.join(out_lines), removed


def _load_gz_text(path):
    with open(path, 'rb') as f:
        return gzip.decompress(f.read()).decode('utf-8')


def _run_psql(target_url, sql_text=None, sql_file=None, single_transaction=False, psql_bin=DEFAULT_PSQL_BIN):
    cmd = [psql_bin, target_url, '-v', 'ON_ERROR_STOP=1', '-q']
    if single_transaction:
        cmd.append('-1')
    stdin_data = None
    if sql_file:
        cmd += ['-f', sql_file]
    elif sql_text is not None:
        cmd += ['-f', '-']
        stdin_data = sql_text.encode('utf-8')
    else:
        raise ValueError('нужен sql_text или sql_file')
    proc = subprocess.run(cmd, input=stdin_data, capture_output=True)
    if proc.returncode != 0:
        stderr = _redact(proc.stderr.decode('utf-8', 'replace'), target_url)
        raise RuntimeError(f'psql упал (код {proc.returncode}): {stderr}')
    return proc.stdout.decode('utf-8', 'replace')


def restore_dump_filtered(dump_gz_path, target_url, psql_bin=DEFAULT_PSQL_BIN):
    """Restore .sql.gz дампа в target_url с фильтром несовместимых строк.

    Отфильтрованный SQL пишем во временный файл (а не подаём через stdin):
    при ошибке psql печатает `psql:<путь>:<номер строки>: ERROR ...` — с
    реальным путём и номером строки внутри ОТФИЛЬТРОВАННОГО дампа, по которому
    можно найти проблемное место, вместо бесполезного `<stdin>`. DSN в это
    сообщение не попадает — редактируется тем же `_redact`, что и остальной
    stderr psql.
    """
    text = _load_gz_text(dump_gz_path)
    filtered_text, removed = filter_dump_text(text)
    fd, tmp_path = tempfile.mkstemp(suffix='.sql', prefix='stand_copy_prod_filtered_')
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(filtered_text)
    try:
        _run_psql(target_url, sql_file=tmp_path, psql_bin=psql_bin)
    except RuntimeError as e:
        raise RuntimeError(f'{e} (отфильтрованный дамп сохранён для диагностики: {tmp_path})') from e
    else:
        os.unlink(tmp_path)
    return removed


def _table_exists(cur, name):
    cur.execute('SELECT to_regclass(%s)', (f'public.{name}',))
    return cur.fetchone()[0] is not None


def _foreign_keys(cur):
    cur.execute("""
        SELECT
            tc.table_name AS child_table,
            kcu.column_name AS child_column,
            ccu.table_name AS parent_table,
            ccu.column_name AS parent_column
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
        JOIN information_schema.constraint_column_usage ccu
          ON tc.constraint_name = ccu.constraint_name AND tc.table_schema = ccu.table_schema
        WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = 'public'
        ORDER BY 1, 2
    """)
    return [
        {'child_table': r[0], 'child_column': r[1], 'parent_table': r[2], 'parent_column': r[3]}
        for r in cur.fetchall()
    ]


def _pk_columns(cur, table):
    cur.execute("""
        SELECT kcu.column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
        WHERE tc.constraint_type = 'PRIMARY KEY' AND tc.table_schema = 'public' AND tc.table_name = %s
        ORDER BY kcu.ordinal_position
    """, (table,))
    return [r[0] for r in cur.fetchall()]


def _table_columns(cur, table):
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        ORDER BY column_name
    """, (table,))
    return [r[0] for r in cur.fetchall()]


def compute_table_hash(cur, table, exclude_cols):
    """md5 всего содержимого таблицы (кроме exclude_cols), в порядке PK.

    Ловит ЛЮБОЕ изменение данных — не только число строк или отдельные суммы:
    другое значение хоть в одной незаисключённой колонке хоть одной строки
    меняет итоговый md5. Колонки внутри строки объединены chr(1), строки между
    собой — chr(2).

    NULL кодируется через `quote_nullable()`: для настоящего NULL она отдаёт
    голый текст `NULL` без кавычек, а для ЛЮБОГО текстового значения — это
    значение в кавычках (внутренние кавычки удвоены). Реальные данные не
    могут дать на выходе `quote_nullable` голый `NULL` — они всегда в
    кавычках, — поэтому строка со значением-меткой в данных (например
    буквально `NULL`) не совпадёт по хешу с настоящим NULL. Фиксированный
    строковый маркер вместо этого был бы уязвим к ровно такой коллизии.

    Порядок колонок в хеше — по алфавиту, одинаков независимо от ADD COLUMN
    (санация добавляет новые колонки в конец физически, но они попадают в
    exclude_cols по имени и не участвуют в хеше ни на одной из сторон сверки).
    """
    pk_cols = _pk_columns(cur, table)
    all_cols = _table_columns(cur, table)
    hash_cols = [c for c in all_cols if c not in exclude_cols]
    if not hash_cols:
        return None, []
    order_cols = pk_cols or hash_cols  # нет PK — сортируем по всем хешируемым колонкам

    col_exprs = ', '.join(f'quote_nullable("{c}"::text)' for c in hash_cols)
    order_exprs = ', '.join(f'"{c}"' for c in order_cols)
    query = (
        f'SELECT md5(coalesce(string_agg(row_data, chr(2) ORDER BY {order_exprs}), \'\')) '
        f'FROM (SELECT {order_exprs}, concat_ws(chr(1), {col_exprs}) AS row_data FROM "{table}") t'
    )
    cur.execute(query)
    (digest,) = cur.fetchone()
    return digest, hash_cols


def compute_snapshot(target_url):
    """Счётчики строк, хеши содержимого, денежные агрегаты, sequences и FK-карта."""
    conn = psycopg2.connect(target_url)
    conn.set_session(readonly=True, autocommit=True)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """)
        tables = [r[0] for r in cur.fetchall()]
        table_set = set(tables)

        table_counts = {}
        for t in tables:
            cur.execute(f'SELECT COUNT(*) FROM "{t}"')
            table_counts[t] = cur.fetchone()[0]

        table_hashes = {}
        table_hash_columns = {}
        for t in tables:
            if t in DOCUMENTED_DIFF_TABLES:
                continue  # содержимое целиком и осознанно заменяется санацией — сверять нечего
            digest, hash_cols = compute_table_hash(cur, t, HASH_EXCLUDE_COLUMNS.get(t, set()))
            table_hashes[t] = digest
            table_hash_columns[t] = hash_cols

        money = {}
        for key, (needed_table, sql) in MONEY_QUERIES.items():
            if needed_table in table_set:
                cur.execute(sql)
                val = cur.fetchone()[0]
                money[key] = float(val) if val is not None else 0.0
            else:
                money[key] = None

        cur.execute("""
            SELECT sequence_name FROM information_schema.sequences
            WHERE sequence_schema = 'public' ORDER BY sequence_name
        """)
        sequences = {}
        for (s,) in cur.fetchall():
            cur.execute(f'SELECT last_value, is_called FROM "{s}"')
            last_value, is_called = cur.fetchone()
            sequences[s] = (last_value + 1) if is_called else last_value

        foreign_keys = _foreign_keys(cur)

        token_values = {}
        for t, col in TOKEN_COLUMNS.items():
            if t in table_set:
                cur.execute(f'SELECT "{col}" FROM "{t}" WHERE "{col}" IS NOT NULL')
                token_values[t] = [r[0] for r in cur.fetchall()]

        # sha256 от password_hash, а не сам хеш — эталон в counts.json не должен
        # содержать значение, по которому (пусть и с усилием) можно было бы
        # опознать пароль; для проверки «изменился ли хеш после санации»
        # отпечатка достаточно.
        admin_password_hash_fingerprints = {}
        if 'admin_users' in table_set:
            cur.execute('SELECT id, password_hash FROM admin_users')
            for admin_id, pwd_hash in cur.fetchall():
                if pwd_hash is not None:
                    admin_password_hash_fingerprints[str(admin_id)] = hashlib.sha256(
                        pwd_hash.encode('utf-8')
                    ).hexdigest()

        return {
            'tables': table_counts,
            'table_hashes': table_hashes,
            'table_hash_columns': table_hash_columns,
            'money': money,
            'sequences': sequences,
            'foreign_keys': foreign_keys,
            'token_values': token_values,
            'admin_password_hash_fingerprints': admin_password_hash_fingerprints,
        }
    finally:
        conn.close()


def check_orphans(target_url, foreign_keys):
    conn = psycopg2.connect(target_url)
    conn.set_session(readonly=True, autocommit=True)
    problems = []
    try:
        cur = conn.cursor()
        for fk in foreign_keys:
            q = (
                f'SELECT COUNT(*) FROM "{fk["child_table"]}" c '
                f'LEFT JOIN "{fk["parent_table"]}" p '
                f'  ON c."{fk["child_column"]}" = p."{fk["parent_column"]}" '
                f'WHERE c."{fk["child_column"]}" IS NOT NULL AND p."{fk["parent_column"]}" IS NULL'
            )
            cur.execute(q)
            n = cur.fetchone()[0]
            if n:
                problems.append({**fk, 'orphan_rows': n})
    finally:
        conn.close()
    return problems


RESERVED_STAND_USERNAMES = {'karim', 'marina', 'artem', 'vitaliy', 'teodor'}


def _count(cur, sql, params=None):
    cur.execute(sql, params or ())
    return cur.fetchone()[0]


def _invariant_null(table, col):
    """Колонка обнулена у всех строк."""
    def check(cur, expected):
        n = _count(cur, f'SELECT COUNT(*) FROM "{table}" WHERE "{col}" IS NOT NULL')
        return {'table': table, 'column': col, 'invariant': 'null', 'violations': n} if n else None
    return check


def _invariant_equals(table, col, value, label):
    """Колонка равна фиксированному значению (плейсхолдер/флаг) у всех строк."""
    def check(cur, expected):
        n = _count(cur, f'SELECT COUNT(*) FROM "{table}" WHERE "{col}" IS DISTINCT FROM %s', (value,))
        return {'table': table, 'column': col, 'invariant': f'equals:{label}', 'violations': n} if n else None
    return check


def _invariant_token_reissued(table, col):
    """Токен не встречается в дампе, не NULL/пуст и уникален (не массовый одинаковый)."""
    def check(cur, expected):
        old_values = set((expected.get('token_values') or {}).get(table) or [])
        cur.execute(f'SELECT "{col}" FROM "{table}"')
        new_values = [r[0] for r in cur.fetchall()]
        problems = []
        leaked = old_values & set(v for v in new_values if v is not None)
        if leaked:
            problems.append({'table': table, 'column': col, 'invariant': 'not_in_dump', 'violations': len(leaked)})
        empty = sum(1 for v in new_values if not v)
        if empty:
            problems.append({'table': table, 'column': col, 'invariant': 'not_empty', 'violations': empty})
        non_empty = [v for v in new_values if v]
        if len(non_empty) != len(set(non_empty)):
            dup = len(non_empty) - len(set(non_empty))
            problems.append({'table': table, 'column': col, 'invariant': 'unique', 'violations': dup})
        return problems
    return check


def _invariant_payment_link_empty(cur, expected):
    """Пусто = NULL или '' — обе формы означают «ссылки нет», обе безопасны."""
    n = _count(cur, "SELECT COUNT(*) FROM payment_link_orders WHERE link IS NOT NULL AND link <> ''")
    return {'table': 'payment_link_orders', 'column': 'link', 'invariant': 'empty', 'violations': n} if n else None


def _invariant_referrer_auth_mode(cur, expected):
    n = _count(cur, "SELECT COUNT(*) FROM referrers WHERE auth_mode = 'telegram'")
    return {'table': 'referrers', 'column': 'auth_mode', 'invariant': "not_equals:telegram", 'violations': n} if n else None


def _invariant_admin_username_not_reserved(cur, expected):
    n = _count(cur, 'SELECT COUNT(*) FROM admin_users WHERE lower(username) = ANY(%s)',
               (list(RESERVED_STAND_USERNAMES),))
    return {'table': 'admin_users', 'column': 'username', 'invariant': 'renamed_prod_prefix', 'violations': n} if n else None


def _invariant_admin_password_hash_changed(cur, expected):
    fingerprints = expected.get('admin_password_hash_fingerprints') or {}
    if not fingerprints:
        return None
    cur.execute('SELECT id, password_hash FROM admin_users')
    unchanged = 0
    for admin_id, pwd_hash in cur.fetchall():
        expected_fp = fingerprints.get(str(admin_id))
        if expected_fp is None or pwd_hash is None:
            continue
        if hashlib.sha256(pwd_hash.encode('utf-8')).hexdigest() == expected_fp:
            unchanged += 1
    return {'table': 'admin_users', 'column': 'password_hash', 'invariant': 'changed', 'violations': unchanged} if unchanged else None


# Каждая колонка из HASH_EXCLUDE_COLUMNS обязана иметь здесь пост-инвариант —
# «исключена из построчного хеша» не значит «не проверяется вовсе». Ключ
# отсутствует в реестре → check_sanitize_invariants сама считает это находкой
# (а не молча пропускает), чтобы новая исключённая колонка без инварианта не
# проходила проверку по умолчанию.
SANITIZE_COLUMN_INVARIANTS = {
    **{(t, c): _invariant_token_reissued(t, c) for t, c in TOKEN_COLUMNS.items()},
    ('referrers', 'telegram'): _invariant_null('referrers', 'telegram'),
    ('referrers', 'telegram_user_id'): _invariant_null('referrers', 'telegram_user_id'),
    ('referrers', 'auth_mode'): _invariant_referrer_auth_mode,
    ('clients', 'telegram'): _invariant_null('clients', 'telegram'),
    ('payment_link_orders', 'link'): _invariant_payment_link_empty,
    ('payout_requests', 'contact_value'): _invariant_equals('payout_requests', 'contact_value', 'sanitized', 'placeholder'),
    ('admin_users', 'username'): _invariant_admin_username_not_reserved,
    ('admin_users', 'password_hash'): _invariant_admin_password_hash_changed,
    ('admin_users', 'telegram'): _invariant_null('admin_users', 'telegram'),
    ('admin_users', 'telegram_user_id'): _invariant_null('admin_users', 'telegram_user_id'),
    ('admin_users', 'login_disabled'): _invariant_equals('admin_users', 'login_disabled', True, 'true'),
    ('admin_users', 'notify_enabled'): _invariant_equals('admin_users', 'notify_enabled', False, 'false'),
}


def _format_invariant_problem(p):
    """Только имена таблицы/колонки/инварианта и число нарушений — без строк.

    Нарушение регулярно всплывает на реальных данных клона (stand_state,
    контакты рефереров и т.п.); печатать сами значения в problems/логи
    означало бы выводить ПДн наружу через сообщение об ошибке.
    """
    return f"{p['table']}.{p['column']}: инвариант «{p['invariant']}» нарушен ({p['violations']} строк)"


def check_sanitize_invariants(candidate_url, expected):
    """Пост-инварианты санации — проверяются ВСЕГДА, а не молча пропускаются.

    login_nonces/stand_state и каждая колонка из HASH_EXCLUDE_COLUMNS — то,
    что санация меняет намеренно (см. stand_sanitize.sql) и что поэтому
    исключено из побайтового хеша содержимого. «Исключено из хеша» не значит
    «не проверяется вовсе»: здесь утверждается ТОЧНОЕ ожидаемое состояние
    после санации, а сообщения содержат только счётчики — не сами данные.
    """
    problems = []
    conn = psycopg2.connect(candidate_url)
    conn.set_session(readonly=True, autocommit=True)
    try:
        cur = conn.cursor()

        if _table_exists(cur, 'login_nonces'):
            n = _count(cur, 'SELECT COUNT(*) FROM login_nonces')
            if n:
                problems.append(f'login_nonces не пуст после санации: {n} строк')

        if _table_exists(cur, 'stand_state'):
            cur.execute('SELECT id, data, version, notified FROM stand_state')
            rows = cur.fetchall()
            expected_state = [(1, '{}', 0, '[]')]
            if rows != expected_state:
                problems.append(
                    f'stand_state не в ожидаемом пустом состоянии: {len(rows)} строк вместо 1 '
                    f'(ожидался ровно один пустой документ)'
                )

        for table, cols in HASH_EXCLUDE_COLUMNS.items():
            if not _table_exists(cur, table):
                continue
            for col in cols:
                checker = SANITIZE_COLUMN_INVARIANTS.get((table, col))
                if checker is None:
                    problems.append(
                        f'внутренняя ошибка: для {table}.{col} (исключена из хеша) не зарегистрирован '
                        f'пост-инвариант в SANITIZE_COLUMN_INVARIANTS'
                    )
                    continue
                result = checker(cur, expected)
                for p in ([result] if isinstance(result, dict) else (result or [])):
                    problems.append(_format_invariant_problem(p))
    finally:
        conn.close()
    return problems


# ────────────────────────────────── команды ───────────────────────────────────

def cmd_dump_prod(args):
    """pg_dump прода, read-only транзакция, без единого лишнего запроса."""
    _secure_mkdir(args.out_dir)
    ts = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    dump_path = os.path.join(args.out_dir, f'prod_dump_{ts}.sql.gz')
    stderr_path = os.path.join(args.out_dir, f'prod_dump_{ts}.stderr.log')
    sha_path = dump_path + '.sha256'

    env = dict(os.environ)
    env['PGOPTIONS'] = '-c default_transaction_read_only=on'

    proc = subprocess.run(
        [args.pg_dump_bin, args.prod_url, '--no-owner', '--no-privileges', '--format=plain'],
        env=env, capture_output=True,
    )
    _write_secure_file(stderr_path, _redact(proc.stderr.decode('utf-8', 'replace'), args.prod_url).encode('utf-8'))

    if proc.returncode != 0:
        print(f'pg_dump прода упал (код {proc.returncode}), детали в {stderr_path}', file=sys.stderr)
        sys.exit(1)

    _write_secure_file(dump_path, gzip.compress(proc.stdout, compresslevel=6))
    sha = _sha256_file(dump_path)
    _write_secure_file(sha_path, f'{sha}  {os.path.basename(dump_path)}\n'.encode('utf-8'))
    _gzip_test(dump_path)

    print(json.dumps({
        'dump_path': dump_path,
        'sha256_path': sha_path,
        'stderr_path': stderr_path,
        'sha256': sha,
        'bytes': os.path.getsize(dump_path),
    }, ensure_ascii=False, indent=2))


def cmd_inspect_dump(args):
    """Restore дампа в одноразовую локальную базу — эталон для verify-candidate."""
    removed = restore_dump_filtered(args.dump, args.scratch_url, psql_bin=args.psql_bin)
    snapshot = compute_snapshot(args.scratch_url)
    snapshot['generated_at'] = datetime.now(timezone.utc).isoformat()
    snapshot['source_dump'] = os.path.basename(args.dump)
    snapshot['filtered_lines'] = removed
    _write_json(args.counts_out, snapshot)
    print(json.dumps({'counts_json': args.counts_out, 'filtered_lines': removed}, ensure_ascii=False, indent=2))


def cmd_backup_stand(args):
    """Полный бэкап живого стенда + stand_state + список admin_users, с проверкой restore."""
    _secure_mkdir(args.out_dir)
    ts = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    dump_path = os.path.join(args.out_dir, f'stand_backup_{ts}.sql.gz')
    sha_path = dump_path + '.sha256'
    state_path = os.path.join(args.out_dir, f'stand_backup_{ts}.state.json')
    admins_path = os.path.join(args.out_dir, f'stand_backup_{ts}.admins.json')
    manifest_path = os.path.join(args.out_dir, f'stand_backup_{ts}.manifest.json')

    proc = subprocess.run(
        [args.pg_dump_bin, args.stand_url, '--no-owner', '--no-privileges', '--format=plain'],
        capture_output=True,
    )
    if proc.returncode != 0:
        print(f'pg_dump стенда упал: {_redact(proc.stderr.decode("utf-8", "replace"), args.stand_url)}', file=sys.stderr)
        sys.exit(1)

    _write_secure_file(dump_path, gzip.compress(proc.stdout, compresslevel=6))
    sha = _sha256_file(dump_path)
    _write_secure_file(sha_path, f'{sha}  {os.path.basename(dump_path)}\n'.encode('utf-8'))
    _gzip_test(dump_path)

    conn = psycopg2.connect(args.stand_url)
    conn.set_session(readonly=True, autocommit=True)
    try:
        cur = conn.cursor()
        state_rows = []
        if _table_exists(cur, 'stand_state'):
            cur.execute('SELECT id, data, version, updated_by, updated_at, notified FROM stand_state')
            cols = ['id', 'data', 'version', 'updated_by', 'updated_at', 'notified']
            state_rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        _write_json(state_path, state_rows)

        cur.execute('SELECT id, username, role, display_name, telegram FROM admin_users ORDER BY id')
        admin_cols = ['id', 'username', 'role', 'display_name', 'telegram']
        admins = [dict(zip(admin_cols, r)) for r in cur.fetchall()]
        _write_json(admins_path, admins)
    finally:
        conn.close()

    # Проверочный restore в одноразовую локальную базу + сверка строк и содержимого.
    removed = restore_dump_filtered(dump_path, args.scratch_url, psql_bin=args.psql_bin)
    live_snapshot = compute_snapshot(args.stand_url)
    scratch_snapshot = compute_snapshot(args.scratch_url)
    mismatches = {
        t: (c, scratch_snapshot['tables'].get(t))
        for t, c in live_snapshot['tables'].items() if c != scratch_snapshot['tables'].get(t)
    }
    hash_mismatches = {
        t: (h, scratch_snapshot['table_hashes'].get(t))
        for t, h in live_snapshot['table_hashes'].items() if h != scratch_snapshot['table_hashes'].get(t)
    }
    if mismatches or hash_mismatches:
        print(f'Проверочный restore бэкапа стенда разошёлся: строки={mismatches}, содержимое={hash_mismatches}',
              file=sys.stderr)
        sys.exit(1)

    manifest = {
        'dump_path': dump_path,
        'sha256_path': sha_path,
        'sha256': sha,
        'created_at': datetime.now(timezone.utc).isoformat(),
        'stand_dbname': _parse_dsn(args.stand_url)['dbname'],
        'state_path': state_path,
        'admins_path': admins_path,
        'verified_restore': True,
        'filtered_lines': removed,
    }
    _write_json(manifest_path, manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


def _find_fresh_backup_manifest(backup_dir, max_age_hours=2):
    """Ищет самый свежий валидный manifest бэкапа стенда моложе max_age_hours.

    Только файловые операции — ни одного сетевого вызова.
    """
    if not os.path.isdir(backup_dir):
        return None, f'папка бэкапов не найдена: {backup_dir}'
    manifests = sorted(
        (os.path.join(backup_dir, name) for name in os.listdir(backup_dir) if name.endswith('.manifest.json')),
        key=os.path.getmtime, reverse=True,
    )
    if not manifests:
        return None, f'в {backup_dir} нет ни одного *.manifest.json'

    now = datetime.now(timezone.utc)
    for path in manifests:
        try:
            with open(path, 'r', encoding='utf-8') as f:
                manifest = json.load(f)
            created_at = datetime.fromisoformat(manifest['created_at'])
            age_hours = (now - created_at).total_seconds() / 3600
            if age_hours > max_age_hours:
                continue
            dump_path = manifest.get('dump_path')
            if not dump_path or not os.path.exists(dump_path):
                continue
            if _sha256_file(dump_path) != manifest.get('sha256'):
                continue
            return manifest, None
        except Exception:
            continue
    return None, f'в {backup_dir} нет валидного бэкапа стенда младше {max_age_hours}ч с корректным SHA256'


def cmd_restore_candidate(args):
    """Создание stand_prodcopy_<дата>, restore прод-дампа, санация.

    Все предохранители — ДО первого подключения к цели. Нарушение любого —
    выход без единого сетевого вызова к базе.
    """
    admin_dsn = _parse_dsn(args.stand_admin_url)

    if admin_dsn['host'] != args.expect_host or admin_dsn['port'] != args.expect_port:
        print(
            f"Отказ: адрес стенд-сервера {admin_dsn['host']}:{admin_dsn['port']} "
            f"не совпадает с ожидаемым {args.expect_host}:{args.expect_port}",
            file=sys.stderr,
        )
        sys.exit(2)

    admin_hostport = f"{admin_dsn['host']}:{admin_dsn['port']}"
    if admin_hostport == args.prod_host_guard:
        print(f'Отказ: целевой адрес {admin_hostport} совпадает с прод-guard', file=sys.stderr)
        sys.exit(2)

    if not CANDIDATE_DB_RE.match(args.candidate_db or ''):
        print(f'Отказ: имя кандидата {args.candidate_db!r} должно начинаться с stand_prodcopy_', file=sys.stderr)
        sys.exit(2)

    if args.candidate_db == admin_dsn['dbname']:
        print('Отказ: имя кандидата совпадает с текущей базой стенда', file=sys.stderr)
        sys.exit(2)

    manifest, err = _find_fresh_backup_manifest(args.backup_dir)
    if err:
        print(f'Отказ: {err}', file=sys.stderr)
        sys.exit(2)

    if not args.i_understand:
        print('Отказ: нужен флаг --i-understand', file=sys.stderr)
        sys.exit(2)

    # ── Предохранители пройдены. Первое подключение к серверу стенда. ───────
    conn = psycopg2.connect(args.stand_admin_url)
    conn.autocommit = True
    try:
        cur = conn.cursor()
        cur.execute('SELECT 1 FROM pg_database WHERE datname = %s', (args.candidate_db,))
        if cur.fetchone():
            print(f'Отказ: база {args.candidate_db} уже существует, DROP не выполняется', file=sys.stderr)
            sys.exit(2)
        cur.execute(f'CREATE DATABASE "{args.candidate_db}"')
    finally:
        conn.close()

    target_url = _with_dbname(args.stand_admin_url, args.candidate_db)

    removed = restore_dump_filtered(args.dump, target_url, psql_bin=args.psql_bin)
    _run_psql(target_url, sql_file=SANITIZE_SQL_PATH, single_transaction=True, psql_bin=args.psql_bin)

    print(json.dumps({
        'candidate_db': args.candidate_db,
        'candidate_url_hint': f'{admin_hostport}/{args.candidate_db}',
        'filtered_lines': removed,
        'sanitized': [
            'partners.token — перевыпущен',
            'referrers.token — перевыпущен',
            'kyc_requests.token — перевыпущен',
            'login_nonces — удалены все строки',
            'admin_users.login_disabled = true, notify_enabled = false, telegram = NULL, telegram_user_id = NULL, password_hash — заведомо невалидный',
            'admin_users.username — karim/marina/artem/vitaliy/teodor -> prod_<логин> при совпадении',
            'referrers.telegram = NULL, referrers.telegram_user_id = NULL, auth_mode telegram -> link',
            'clients.telegram = NULL',
            'payout_requests.contact_value — заменён нейтральным значением',
            'payment_link_orders.link — обнулена (публичная ссылка на оплату у провайдера)',
            'stand_state — сброшено в id=1, data={}, version=0, notified=[]',
        ],
        'not_touched': [
            'payment_link_orders.order_id/payment_id — бухгалтерский след провайдера, не секрет (решение лидера)',
            'deals.doc_invoice_url/doc_contract_url/doc_payment_url — доступ контролирует Google, не стенд',
            'agreement_docs.drive_url — то же самое',
            'payin_tx_hash/payout_tx_hash/doverka_transaction_id/doverka_payout_hash/wallet — финансовый '
            'след (хэши транзакций, номера кошельков), не канал связи с человеком',
            'clients.phone/notes и другие свободные текстовые поля клиентов — решение лидера: стенд целиком '
            'за логином, исходящие заглушены, это рабочие данные команды',
        ],
        'backup_manifest_used': manifest['dump_path'],
    }, ensure_ascii=False, indent=2))


def cmd_verify_candidate(args):
    """Сверка кандидата с эталоном из counts.json (inspect-dump прод-дампа)."""
    with open(args.counts_json, 'r', encoding='utf-8') as f:
        expected = json.load(f)

    actual = compute_snapshot(args.candidate_url)

    problems = []
    documented = []

    for t, exp_count in expected['tables'].items():
        act_count = actual['tables'].get(t)
        if t in DOCUMENTED_DIFF_TABLES:
            documented.append({'table': t, 'dump_rows': exp_count, 'candidate_rows': act_count,
                                'reason': 'санация очищает эту таблицу по контракту T4'})
            continue
        if act_count != exp_count:
            problems.append(f'таблица {t}: дамп={exp_count}, кандидат={act_count}')

    extra_tables = set(actual['tables']) - set(expected['tables'])
    for t in extra_tables:
        if t not in DOCUMENTED_DIFF_TABLES:
            problems.append(f'таблица {t} есть в кандидате, но не было в дампе')

    if 'admin_users' in expected['tables']:
        documented.append({
            'table': 'admin_users',
            'reason': 'login_disabled/notify_enabled/password_hash/telegram_user_id/username изменены санацией, количество строк совпадает',
        })
    documented.append({
        'note': 'partners.token/referrers.token/kyc_requests.token перевыпущены — значения не сравниваются побайтово, '
                'но проверяется, что ни одно старое значение не осталось (см. пост-инварианты ниже)',
    })
    documented.append({
        'note': 'referrers.telegram/telegram_user_id/auth_mode, clients.telegram, admin_users.telegram, '
                'payout_requests.contact_value, payment_link_orders.link — обнулены санацией (внешний '
                'человек/провайдер не должен быть достижим со стенда); точное состояние проверяют пост-инварианты',
    })
    documented.append({
        'note': 'deals.doc_invoice_url/doc_contract_url/doc_payment_url и agreement_docs.drive_url — '
                'сохранены намеренно: доступ к ним контролирует Google (не стенд), команда и так видит их в проде',
    })
    documented.append({
        'note': 'clients.phone/notes и другие свободные текстовые поля клиентов — сохранены намеренно '
                '(решение лидера): стенд целиком за логином, исходящие интеграции заглушены, это рабочие данные '
                'команды для проверки «как в проде»; их порчу всё равно ловит построчный хеш',
    })

    for t, exp_hash in expected.get('table_hashes', {}).items():
        if t in DOCUMENTED_DIFF_TABLES:
            continue
        act_hash = actual['table_hashes'].get(t)
        if act_hash != exp_hash:
            hashed_cols = expected.get('table_hash_columns', {}).get(t, [])
            problems.append(
                f'таблица {t}: содержимое разошлось с эталоном (хеш по колонкам {hashed_cols}: '
                f'дамп={exp_hash}, кандидат={act_hash})'
            )

    for key, exp_val in expected['money'].items():
        act_val = actual['money'].get(key)
        if exp_val is None:
            continue
        if act_val is None or abs(act_val - exp_val) > 1e-6:
            problems.append(f'денежный агрегат {key}: дамп={exp_val}, кандидат={act_val}')

    for seq, exp_val in expected['sequences'].items():
        act_val = actual['sequences'].get(seq)
        if act_val != exp_val:
            problems.append(f'sequence {seq}: дамп next={exp_val}, кандидат next={act_val}')

    orphans = check_orphans(args.candidate_url, actual['foreign_keys'])
    if orphans:
        problems.append(f'сиротские FK-ссылки: {orphans}')

    # Таблицы/колонки санации — не «пропущены молча», а проверены на точный
    # ожидаемый пост-инвариант (см. check_sanitize_invariants).
    problems.extend(check_sanitize_invariants(args.candidate_url, expected))

    report = {'ok': not problems, 'problems': problems, 'documented_differences': documented}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if problems:
        sys.exit(1)


# ──────────────────────────────────── CLI ─────────────────────────────────────

def build_parser():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='command', required=True)

    sp = sub.add_parser('dump-prod', help='read-only pg_dump прода')
    sp.add_argument('--prod-url', required=True, help='DSN прода (DATABASE_PUBLIC_URL), не печатается и не логируется')
    sp.add_argument('--out-dir', required=True)
    sp.add_argument('--pg-dump-bin', default=DEFAULT_PG_DUMP_BIN)
    sp.set_defaults(func=cmd_dump_prod)

    sp = sub.add_parser('inspect-dump', help='restore дампа в одноразовую базу, снятие эталона')
    sp.add_argument('--dump', required=True)
    sp.add_argument('--scratch-url', required=True, help='DSN одноразовой пустой локальной базы')
    sp.add_argument('--counts-out', required=True, help='куда записать counts.json')
    sp.add_argument('--psql-bin', default=DEFAULT_PSQL_BIN)
    sp.set_defaults(func=cmd_inspect_dump)

    sp = sub.add_parser('backup-stand', help='полный бэкап живого стенда с проверкой')
    sp.add_argument('--stand-url', required=True)
    sp.add_argument('--out-dir', required=True)
    sp.add_argument('--scratch-url', required=True, help='DSN одноразовой пустой локальной базы для проверки restore')
    sp.add_argument('--pg-dump-bin', default=DEFAULT_PG_DUMP_BIN)
    sp.add_argument('--psql-bin', default=DEFAULT_PSQL_BIN)
    sp.set_defaults(func=cmd_backup_stand)

    sp = sub.add_parser('restore-candidate', help='создание кандидат-базы + restore + санация')
    sp.add_argument('--stand-admin-url', required=True, help='DSN сервера stand-db с правом CREATE DATABASE')
    sp.add_argument('--candidate-db', required=True)
    sp.add_argument('--dump', required=True)
    sp.add_argument('--expect-host', required=True)
    sp.add_argument('--expect-port', required=True, type=int)
    sp.add_argument('--prod-host-guard', required=True, help='"host:port" прода — цель не должна совпасть с ним')
    sp.add_argument('--backup-dir', required=True, help='папка с manifest.json от backup-stand')
    sp.add_argument('--i-understand', action='store_true')
    sp.add_argument('--psql-bin', default=DEFAULT_PSQL_BIN)
    sp.set_defaults(func=cmd_restore_candidate)

    sp = sub.add_parser('verify-candidate', help='сверка кандидата с эталоном')
    sp.add_argument('--candidate-url', required=True)
    sp.add_argument('--counts-json', required=True)
    sp.set_defaults(func=cmd_verify_candidate)

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
