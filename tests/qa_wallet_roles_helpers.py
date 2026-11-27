"""Общие помощники независимой QA-проверки ролей кошельков.

Роль актора берётся из БД (AdminUser), как в проде; current_role не подменяется.
"""
import json
import secrets

import app as m


def make_user(role, name=None):
    s = m.get_session()
    try:
        u = m.AdminUser(username=f'qa-{role}-{secrets.token_hex(4)}', role=role,
                        password_hash='unused', display_name=name or f'QA {role} {secrets.token_hex(2)}')
        s.add(u)
        s.commit()
        return u.id
    finally:
        s.close()


def client_for(user_id):
    m.app.config['TESTING'] = True
    client = m.app.test_client()
    with client.session_transaction() as sess:
        sess['user_id'] = user_id
    return client


def put_board(state, version=1):
    db = m.get_session()
    try:
        row = m._stand_row(db)
        row.data, row.version = json.dumps(state, ensure_ascii=False), version
        db.commit()
    finally:
        db.close()


def board():
    db = m.get_session()
    try:
        row = m._stand_row(db)
        return json.loads(row.data or '{}'), row.version
    finally:
        db.close()


def snapshot_board():
    db = m.get_session()
    try:
        row = m._stand_row(db)
        return row.data, row.version, row.generation
    finally:
        db.close()


def restore_board(saved):
    db = m.get_session()
    try:
        row = m._stand_row(db)
        row.data, row.version, row.generation = saved
        db.commit()
    finally:
        db.close()


def registry_id(address):
    db = m.get_session()
    try:
        return db.query(m.Wallet).filter(m.Wallet.address == address).one().id
    finally:
        db.close()


def send_deal(deal_id, wallet_address, dest, amount, **extra):
    """Сделка на шаге s23 с кошельком отправки из реестра (id — число, как в проде)."""
    wid = registry_id(wallet_address)
    deal = {'id': deal_id, 'code': f'СД-{deal_id}', 'client': 'Синтетика', 'step': 's23',
            'type': 'Оплата недвижимости', 'kind': 'Лизхолд', 'walletId': wid,
            'transfer': {'addr': dest, 'amount': amount, 'net': 'TRC-20', 'sends': []},
            'log': [], 'payinHashes': [], 'demoTransfers': False}
    deal.update(extra)
    db = m.get_session()
    try:
        w = db.query(m.Wallet).filter(m.Wallet.id == wid).one().to_dict()
    finally:
        db.close()
    mirror = {'id': wid, 'addr': wallet_address, 'multisig': True, 'role': 'findir',
              'owner': 'компания', 'name': w['label']}
    for key in ('purpose', 'limit_usd', 'initiator_roles', 'confirmer_roles', 'owner_can_alone',
                'signer_addresses'):
        mirror[key] = w[key]
    return deal, mirror


def serve():
    """Настоящий многопоточный HTTP-сервер приложения на свободном локальном порту."""
    import threading
    from werkzeug.serving import make_server
    server = make_server('127.0.0.1', 0, m.app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, f'http://127.0.0.1:{server.server_port}'


def cookie_for(user_id):
    serializer = m.app.session_interface.get_signing_serializer(m.app)
    return {'Cookie': 'session=' + serializer.dumps({'user_id': user_id})}


MIRROR_ERROR = 'Правила кошелька берутся только из реестра'


def checked_put(client, version, data, witness=None):
    """PUT общего состояния. Отказ зеркала кошелька не засчитывается как защита от подделки:
    отрицательный тест обязан упираться в свой сторожок (witness), а не в побочный."""
    r = client.put('/api/stand/state', json={'version': version, 'data': data})
    text = r.get_data(as_text=True)
    assert MIRROR_ERROR not in text, 'PUT отвергнут зеркалом кошелька, тест бы стал пустым: ' + text[:200]
    if witness is not None:
        assert r.status_code == 409 and witness in text, (r.status_code, text[:300])
    return r


# ------------------------------------------------------------ изоляция БД между тестами

_SKIP_TABLES = {'wallets', 'stand_state'}


def db_snapshot():
    """Снимок общей тестовой БД: максимальные id по таблицам, ключи таблиц без id, строки
    реестра кошельков и доска.

    QA-тесты сеют кошельки с политикой и создают сделки/переводы/связи; после теста всё созданное
    удаляется, чтобы старые тесты не видели чужих строк (и не ловили повторное использование id)."""
    from sqlalchemy import func, inspect, select
    existing = set(inspect(m.engine).get_table_names())
    db = m.get_session()
    try:
        maxima, keys = {}, {}
        for table in m.Base.metadata.sorted_tables:
            if table.name in _SKIP_TABLES:
                continue
            if table.name not in existing:
                # Отсутствовать может только стенд-таблица (её создаёт _stand_migrate, а CRM-файл
                # может запускаться отдельно). Нехватка бизнес-таблицы — ошибка окружения, не повод молчать.
                assert table.name in m.STAND_ONLY_TABLES, f'в тестовой БД нет бизнес-таблицы {table.name}'
                continue
            if 'id' in table.c:
                maxima[table.name] = db.execute(select(func.max(table.c.id))).scalar()
            elif len(table.primary_key.columns) == 1:
                col = list(table.primary_key.columns)[0]
                keys[table.name] = (col.name, {r[0] for r in db.execute(select(col))})
        wallets = [{c.name: getattr(w, c.name) for c in m.Wallet.__table__.columns}
                   for w in db.query(m.Wallet).all()]
    finally:
        db.close()
    return {'maxima': maxima, 'keys': keys, 'wallets': wallets, 'board': _safe_board()}


def _safe_board():
    try:
        return snapshot_board()
    except Exception:
        return None


def db_restore(snap):
    from sqlalchemy import select
    db = m.get_session()
    try:
        for table in reversed(m.Base.metadata.sorted_tables):
            if table.name in snap['maxima']:
                top = snap['maxima'][table.name]
                db.execute(table.delete() if top is None else table.delete().where(table.c.id > top))
            elif table.name in snap['keys']:
                name, before = snap['keys'][table.name]
                col = table.c[name]
                extra = [r[0] for r in db.execute(select(col)) if r[0] not in before]
                for i in range(0, len(extra), 400):
                    db.execute(table.delete().where(col.in_(extra[i:i + 400])))
        db.query(m.Wallet).delete()
        for row in snap['wallets']:
            db.add(m.Wallet(**row))
        db.commit()
    finally:
        db.close()
    if snap['board'] is not None:
        restore_board(snap['board'])
