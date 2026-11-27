"""Idempotent schema upgrade. PostgreSQL downgrade is an explicit, guarded script."""
from pathlib import Path
from sqlalchemy import inspect


def upgrade(engine, table):
    with engine.begin() as conn:
        columns = {c['name']: c for c in inspect(conn).get_columns('payin_tx_uses')}
        if 'stand_generation' in columns and columns['deal_id']['nullable']:
            return
        if conn.dialect.name == 'postgresql':
            sql = Path(__file__).with_name('migrations').joinpath(
                '20261014_payin_reservations_up.sql').read_text()
            conn.exec_driver_sql(sql)
        elif conn.dialect.name == 'sqlite':
            # SQLite cannot relax NOT NULL in place. Preserve every legacy
            # column/value and index; the transaction makes the rebuild atomic.
            conn.exec_driver_sql('ALTER TABLE payin_tx_uses RENAME TO payin_tx_uses_legacy')
            indexes = inspect(conn).get_indexes('payin_tx_uses_legacy')
            for index in indexes:
                conn.exec_driver_sql('DROP INDEX "' + index['name'].replace('"', '""') + '"')
            table.create(conn)
            names = ', '.join('"' + name + '"' for name in columns)
            conn.exec_driver_sql(f'INSERT INTO payin_tx_uses ({names}) SELECT {names} FROM payin_tx_uses_legacy')
            conn.exec_driver_sql('DROP TABLE payin_tx_uses_legacy')
        else:
            raise RuntimeError('Unsupported payin ledger database')
