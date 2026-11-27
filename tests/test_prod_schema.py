"""Проверка базовой схемы CRM и таблиц стенда."""

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
STAND_TABLES = {
    'stand_state', 'stand_deleted_deals', 'stand_files', 'stand_notify_log', 'stand_tg_bind', 'stand_tg_offset',
    'stand_sber_mirror_state', 'stand_crm_links', 'stand_close_evidence', 'stand_channels',
    'channel_export_messages',
}


# Базовые таблицы CRM из app.py на 0e28991.
PROD_TABLES = {
    'admin_users',
    'agreement_docs',
    'agreements',
    'bank_cards',
    'card_allocations',
    'card_topups',
    'cash_allocations',
    'cash_batches',
    'channel_traffic',
    'clients',
    'conversion_debits',
    'conversion_sources',
    'conversion_txs',
    'conversions',
    'deal_agents',
    'deals',
    'kyc_files',
    'kyc_requests',
    'login_nonces',
    'managers',
    'partners',
    'payin_tx_uses',
    'payin_txs',
    'payment_link_orders',
    'payout_requests',
    'payout_tx_uses',
    'payout_txs',
    'reestr_inflows',
    'reestr_snapshots',
    'referrers',
    'reimbursement_tx_uses',
    'reimbursement_txs',
    'reimbursements',
    'sber_debits',
    'sber_incomes',
    'transactions',
    'wallet_operations',
    'wallets',
}


def _start(database, mode, database_url=None):
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(('STAND_', 'TELEGRAM_', 'BITRIX_', 'SBER_',
                                  'SERVICE_', 'TRON', 'ETHERSCAN_', 'GOOGLE_'))
           and key not in {'DATABASE_URL', 'SECRET_KEY', 'LOCAL_NO_AUTH', 'TASKS_ENABLED'}}
    env.update(DATABASE_URL=database_url or f'sqlite:///{database}', SECRET_KEY='schema-test-secret',
               LOCAL_NO_AUTH='0', REESTR_SYNC_ENABLED='0', PAYMENT_POLL_ENABLED='0',
               PAYIN_ADDR_BACKFILL='0', KYC_RETENTION_ENABLED='0')
    if mode is not None:
        env['STAND_MODE'] = mode
    code = '''
import socket
_connect = socket.socket.connect
_connect_ex = socket.socket.connect_ex
def _local(address):
    if isinstance(address, tuple) and address[0] not in ('127.0.0.1', '::1', 'localhost'):
        raise RuntimeError('Внешняя сеть запрещена в schema-тесте')
def _safe_connect(sock, address):
    _local(address)
    return _connect(sock, address)
def _safe_connect_ex(sock, address):
    _local(address)
    return _connect_ex(sock, address)
socket.socket.connect = _safe_connect
socket.socket.connect_ex = _safe_connect_ex
import app
from sqlalchemy import inspect
assert app.STAND_MODE == (''' + repr(mode == '1') + ''')
assert set(app.STAND_ONLY_TABLES) == ''' + repr(STAND_TABLES) + '''
print('SCHEMA=' + __import__('json').dumps({
    'tables': inspect(app.engine).get_table_names(),
    'columns': [c['name'] for c in inspect(app.engine).get_columns('admin_users')],
}))
app.engine.dispose()
'''
    result = subprocess.run([sys.executable, '-c', code], cwd=ROOT, env=env,
                            capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(next(line[7:] for line in result.stdout.splitlines()
                           if line.startswith('SCHEMA=')))


@pytest.mark.parametrize('mode', [None, '0', '1'])
def test_schema_mode_and_repeated_start(tmp_path, mode):
    database = tmp_path / 'schema.db'
    first = _start(database, mode)
    second = _start(database, mode)
    assert first == second
    tables = set(first['tables'])
    assert {'login_disabled', 'notify_enabled'} <= set(first['columns'])
    if mode == '1':
        assert tables == PROD_TABLES | STAND_TABLES
    else:
        assert tables == PROD_TABLES
        assert not tables & STAND_TABLES


def test_admin_flags_are_additive_on_existing_table(tmp_path):
    database = tmp_path / 'legacy.db'
    with sqlite3.connect(database) as conn:
        conn.execute('CREATE TABLE admin_users (id INTEGER PRIMARY KEY, username VARCHAR(50))')
        conn.execute("INSERT INTO admin_users (id, username) VALUES (1, 'legacy')")
    first = _start(database, '0')
    second = _start(database, '0')
    assert first == second
    with sqlite3.connect(database) as conn:
        columns = {row[1]: row for row in conn.execute('PRAGMA table_info(admin_users)')}
        assert columns['login_disabled'][4].upper() == 'FALSE'
        assert columns['notify_enabled'][4].upper() == 'FALSE'
        assert conn.execute('SELECT id, username, login_disabled, notify_enabled '
                            'FROM admin_users').fetchone() == (1, 'legacy', 0, 0)


@pytest.mark.skipif(not Path('/opt/homebrew/opt/postgresql@17/bin/initdb').exists(),
                    reason='Локальный PostgreSQL 17 не установлен')
def test_postgres_prod_schema_matches_baseline(tmp_path):
    """Временный кластер проверяет prod-схему и повторный старт на PostgreSQL."""
    binaries = Path('/opt/homebrew/opt/postgresql@17/bin')
    data = tmp_path / 'pgdata'
    # На macOS локаль Python-процесса может сорвать запуск postmaster.
    pg_env = {**os.environ, 'LC_ALL': 'C'}
    subprocess.run([str(binaries / 'initdb'), '-D', str(data), '-A', 'trust',
                    '-U', 'schema_test', '--no-instructions'],
                   check=True, capture_output=True, text=True, timeout=90,
                   env=pg_env)
    server = [str(binaries / 'pg_ctl'), '-D', str(data)]
    # Unix-сокет PostgreSQL ограничен 103 байтами, путь pytest бывает длиннее.
    with tempfile.TemporaryDirectory(prefix='calccrm-t19-pg-schema-', dir='/tmp') as socket_dir:
        subprocess.run(server + ['-o', f'-k {socket_dir} -h ""', '-l',
                                 str(tmp_path / 'postgres.log'), 'start'],
                       check=True, capture_output=True, text=True, timeout=90,
                       env=pg_env)
        try:
            url = f'postgresql://schema_test@/postgres?host={socket_dir}'
            first = _start(None, None, url)
            second = _start(None, None, url)
            assert first == second
            assert set(first['tables']) == PROD_TABLES
            assert not set(first['tables']) & STAND_TABLES
            assert {'login_disabled', 'notify_enabled'} <= set(first['columns'])
        finally:
            subprocess.run(server + ['-m', 'immediate', 'stop'], check=True,
                           capture_output=True, text=True, timeout=90,
                           env=pg_env)
