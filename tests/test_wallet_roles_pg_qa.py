"""Реальный PostgreSQL: апгрейд старой таблицы wallets до реестра ролей подписи.

SQLite прощает `SET bool = 1`, PostgreSQL — нет, поэтому миграция реестра
проверяется на временном локальном кластере (только Unix-сокет, без сети).
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import psycopg2
import pytest


ROOT = Path(__file__).resolve().parents[1]
BIN = Path('/opt/homebrew/opt/postgresql@17/bin')
REALTY = 'TDuDeRiwrLLN3hnnA57G5yM6ibg58A6wZk'
EXCHANGE = 'TA6S3RBEY57jq8fXEVVsU6H9JZ18inenG4'
LEGACY = 'TKkeEVf2zySaWTLyX2qPwvi6kcdHRuPxkJ'
OTHER_LEGACY = 'TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn'
ADDED_LATER = 'TA4Y62o6YC2Zsck9rZVGTvqW1AQ7X9zTnj'
OLD_COLUMNS = {'is_multisig', 'accepts_payin', 'owner'}
NEW_COLUMNS = {'purpose', 'limit_usd', 'initiator_roles', 'confirmer_roles',
               'owner_can_alone', 'signer_addresses', 'not_for_new_deals',
               'signer_weights', 'threshold', 'policy_log'}

LEGACY_DDL = '''
CREATE TABLE wallets (
    id SERIAL PRIMARY KEY, address VARCHAR(100) UNIQUE NOT NULL,
    blockchain VARCHAR(20) DEFAULT 'TRON', label VARCHAR(100),
    created_at TIMESTAMP DEFAULT now(), active BOOLEAN DEFAULT TRUE,
    is_monitored BOOLEAN DEFAULT TRUE, is_balance BOOLEAN DEFAULT FALSE,
    is_multisig BOOLEAN DEFAULT FALSE, accepts_payin BOOLEAN DEFAULT FALSE,
    owner VARCHAR(100))
'''


def start_app(url, stand):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('STAND_', 'TELEGRAM_', 'BITRIX_', 'SBER_', 'SERVICE_',
                                'TRON', 'ETHERSCAN_', 'GOOGLE_'))
           and k not in {'DATABASE_URL', 'SECRET_KEY', 'LOCAL_NO_AUTH'}}
    env.update(DATABASE_URL=url, SECRET_KEY='pg-wallet-roles-qa', LOCAL_NO_AUTH='0',
               REESTR_SYNC_ENABLED='0', PAYMENT_POLL_ENABLED='0', PAYIN_ADDR_BACKFILL='0',
               KYC_RETENTION_ENABLED='0', TRONSCAN_WARM_ENABLED='0', METRIKA_TOKEN='',
               STAND_SBER_MIRROR_ENABLED='0', STAND_TG_UPDATES_ENABLED='0',
               STAND_TRANSFER_POLL_ENABLED='0', STAND_MODE='1' if stand else '0')
    code = 'import app; app.engine.dispose()'
    result = subprocess.run([sys.executable, '-c', code], cwd=ROOT, env=env,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout + result.stderr


@pytest.fixture
def pg(tmp_path):
    if not (BIN / 'initdb').exists():
        pytest.skip('Локальный PostgreSQL 17 не установлен')
    env = {**os.environ, 'LC_ALL': 'C'}
    data = tmp_path / 'pgdata'
    subprocess.run([str(BIN / 'initdb'), '-D', str(data), '-A', 'trust', '-U', 'qa',
                    '-E', 'UTF8', '--locale=C', '--no-instructions'], check=True, capture_output=True, text=True,
                   timeout=90, env=env)
    server = [str(BIN / 'pg_ctl'), '-D', str(data)]
    with tempfile.TemporaryDirectory(prefix='calccrm-t19-pg-walletroles-', dir='/tmp') as sock:
        subprocess.run(server + ['-o', f'-k {sock} -h ""', '-l', str(tmp_path / 'pg.log'),
                                 'start'], check=True, capture_output=True, text=True,
                       timeout=90, env=env)
        try:
            conn = psycopg2.connect(host=sock, user='qa', dbname='postgres')
            conn.autocommit = True
            yield conn, f'postgresql://qa@/postgres?host={sock}'
            conn.close()
        finally:
            subprocess.run(server + ['-m', 'immediate', 'stop'], check=True,
                           capture_output=True, text=True, timeout=90, env=env)


def columns(conn):
    cur = conn.cursor()
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='wallets'")
    return {r[0] for r in cur.fetchall()}


def flags(conn):
    cur = conn.cursor()
    cur.execute('SELECT address, not_for_new_deals, active, purpose FROM wallets')
    return {r[0]: r[1:] for r in cur.fetchall()}


def seed_legacy(conn):
    cur = conn.cursor()
    cur.execute(LEGACY_DDL)
    cur.execute("INSERT INTO wallets (address, label, is_multisig, accepts_payin, owner) VALUES "
                "(%s,'Кошелёк Груши',TRUE,TRUE,'компания'),(%s,'Андрей',FALSE,TRUE,'Андрей')",
                (LEGACY, OTHER_LEGACY))


def test_stand_upgrade_on_postgres_adds_columns_flags_legacy_once(pg):
    conn, url = pg
    seed_legacy(conn)
    log = start_app(url, stand=True)
    assert NEW_COLUMNS <= columns(conn), 'миграция откатилась целиком:\n' + log[-1500:]
    rows = flags(conn)
    # старые кошельки сохранены, активны и помечены «не для новых сделок»
    assert rows[LEGACY][0] is True and rows[LEGACY][1] is True
    assert rows[OTHER_LEGACY][0] is True and rows[OTHER_LEGACY][1] is True
    # шесть политических кошельков созданы и доступны для новых сделок (раньше было два)
    assert rows[REALTY] == (False, True, 'realty')
    assert rows[EXCHANGE] == (False, True, 'exchange')
    assert rows['TAGufCVNFBLh6NiEGL8iaQ4F9PPnftcgBk'] == (False, True, 'realty_small')
    assert rows['TR68DHoj71Nz4FoTvqnBFQK2Fc6NkEK6nQ'] == (False, True, 'provider')
    assert rows['TQPv1GETKVjSWZymdMu5WbSSeS6JhL2KHt'] == (False, True, 'client_funds')
    assert rows['TUXAF8TNuQ5FTduffBGjqz9RjfensGbYcJ'] == (False, True, 'martrust')
    # кошелёк, заведённый админом после миграции, повторный старт не трогает
    cur = conn.cursor()
    cur.execute("INSERT INTO wallets (address, label, accepts_payin, not_for_new_deals) "
                "VALUES (%s,'Позже',TRUE,FALSE)", (ADDED_LATER,))
    start_app(url, stand=True)
    start_app(url, stand=True)
    rows = flags(conn)
    assert rows[ADDED_LATER][0] is False
    assert rows[LEGACY][0] is True and rows[REALTY][0] is False and rows[EXCHANGE][0] is False
    cur.execute('SELECT count(*) FROM wallets')
    assert cur.fetchone()[0] == 11   # 4 старых (2 свои + 2 из сида) + 6 политик + добавленный позже


def test_prod_mode_upgrade_on_postgres_keeps_legacy_working(pg):
    """STAND_MODE=0: колонки добавлены, старые кошельки не заблокированы, политика не сидится."""
    conn, url = pg
    seed_legacy(conn)
    log = start_app(url, stand=False)
    assert NEW_COLUMNS <= columns(conn), 'миграция откатилась целиком:\n' + log[-1500:]
    rows = flags(conn)
    assert rows[LEGACY][1] is True and rows[OTHER_LEGACY][1] is True
    assert REALTY not in rows and EXCHANGE not in rows
    start_app(url, stand=False)
    assert flags(conn) == rows
