"""Fresh installation and lossless legacy SQLite upgrade; PostgreSQL dump roundtrip is scripted."""
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
import app as m
from payin_reservation_schema import upgrade


@pytest.mark.parametrize('legacy', [False, True])
def test_fresh_and_existing_ledger_schema(tmp_path, legacy):
    engine = create_engine('sqlite:///' + str(tmp_path / 'schema.db'))
    try:
        with engine.begin() as conn:
            for sql in ('CREATE TABLE deals (id INTEGER PRIMARY KEY)',
                        'CREATE TABLE payin_txs (id INTEGER PRIMARY KEY)',
                        'CREATE TABLE conversions (id INTEGER PRIMARY KEY)'):
                conn.exec_driver_sql(sql)
            if legacy:
                conn.exec_driver_sql('''CREATE TABLE payin_tx_uses (
                    id INTEGER PRIMARY KEY, tx_id INTEGER NOT NULL REFERENCES payin_txs(id),
                    deal_id INTEGER NOT NULL REFERENCES deals(id), amount_usdt FLOAT NOT NULL,
                    created_at DATETIME, CONSTRAINT uq_payin_tx_use UNIQUE(tx_id, deal_id))''')
                conn.exec_driver_sql("INSERT INTO payin_tx_uses VALUES (42, 1, 2, 123.45, '2026-10-14')")
            else:
                m.PayinTxUse.__table__.create(conn)
        upgrade(engine, m.PayinTxUse.__table__)
        upgrade(engine, m.PayinTxUse.__table__)
        with engine.begin() as conn:
            columns = {c['name']: c for c in inspect(conn).get_columns('payin_tx_uses')}
            assert columns['deal_id']['nullable']
            if legacy:
                assert conn.exec_driver_sql('SELECT id, tx_id, deal_id, amount_usdt, created_at FROM payin_tx_uses').one() == (42, 1, 2, 123.45, '2026-10-14')
            conn.exec_driver_sql("INSERT INTO payin_tx_uses (tx_id, amount_usdt, stand_generation, stand_cnv_id) VALUES (1, 10, 'g', 'A'), (1, 10, 'g', 'B')")
        for sql in ("INSERT INTO payin_tx_uses (tx_id, amount_usdt, stand_generation, stand_cnv_id) VALUES (1, 10, 'g', 'A')",
                    'INSERT INTO payin_tx_uses (tx_id, amount_usdt) VALUES (1, 10)'):
            with pytest.raises(IntegrityError):
                with engine.begin() as conn:
                    conn.exec_driver_sql(sql)
    finally:
        engine.dispose()
