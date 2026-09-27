"""Зеркало Сбера: локальная БД и подменённый канал чтения, без сети."""

import json
import logging
from datetime import datetime, timedelta
from uuid import uuid4

import pytest

import app as appmod
import stand_sber_mirror as mirror


@pytest.fixture
def stand(monkeypatch):
    monkeypatch.setattr(appmod, 'STAND_MODE', True)
    monkeypatch.setenv('STAND_PROD_RO_KEY', 'secret-should-not-be-logged')
    monkeypatch.setenv('STAND_SBER_MIRROR_ENABLED', '1')
    monkeypatch.setenv('STAND_SBER_BOARD_DAYS', '14')
    db = appmod.get_session()
    db.query(appmod.StandSberMirrorState).delete()
    db.query(appmod.StandState).delete()
    db.commit()
    user = db.query(appmod.AdminUser).filter_by(username='sber_mirror_test').first()
    if not user:
        user = appmod.AdminUser(username='sber_mirror_test', role='admin',
                                password_hash=appmod.AdminUser.hash_password('test'))
        db.add(user)
        db.commit()
    user_id = user.id
    db.close()
    client = appmod.app.test_client()
    with client.session_transaction() as session:
        session['user_id'] = user_id
    yield client
    db = appmod.get_session()
    db.query(appmod.StandSberMirrorState).delete()
    db.query(appmod.StandState).delete()
    db.query(appmod.SberIncome).filter(appmod.SberIncome.uuid.like('mirror-test-%')).delete()
    db.commit()
    db.close()


def income(days=0):
    return {'id': 123, 'uuid': 'mirror-test-' + uuid4().hex,
            'operation_date': (datetime.utcnow() - timedelta(days=days)).isoformat(),
            'amount_rub': 12345.67, 'payer': 'Иванов', 'purpose': 'Договор 1',
            'doc_number': '42', 'excluded': False}


def board():
    db = appmod.get_session()
    try:
        row = db.query(appmod.StandState).filter_by(id=1).first()
        return json.loads(row.data), row.version
    finally:
        db.close()


def test_poll_upsert_board_and_human_link_survive(stand, monkeypatch):
    item = income()
    calls = []

    def fake(kind, params):
        calls.append((kind, params))
        return 200, {'success': True, 'incomes': [item]}

    monkeypatch.setattr(mirror.stand_egress, 'read_get', fake)
    assert mirror.poll(appmod)
    assert mirror.poll(appmod)
    data, version = board()
    assert len(data['incomes']) == 1
    record = data['incomes'][0]
    assert record['id'] == 'sber:' + item['uuid']
    assert record['source'] == 'sber'
    assert record['rub'] == item['amount_rub']
    assert record['purpose'] == item['purpose']
    assert record['acc'] == ''
    assert record['docNumber'] == '42'
    assert version == 1
    db = appmod.get_session()
    assert db.query(appmod.SberIncome).filter_by(uuid=item['uuid']).count() == 1
    db.close()
    assert calls == [('prod_incomes', {'all': '1'})] * 2

    record['dealId'] = 44
    record['cnvId'] = 9
    record['excluded'] = True
    record['rub'] = 1
    response = stand.put('/api/stand/state', json={'version': version, 'data': data})
    assert response.status_code == 200
    assert response.json['data']['incomes'][0]['rub'] == item['amount_rub']
    assert mirror.poll(appmod)
    saved = board()[0]['incomes'][0]
    assert (saved['dealId'], saved['cnvId'], saved['excluded']) == (44, 9, True)
    assert len(board()[0]['incomes']) == 1
    assert mirror.status(appmod)['last_new_count'] == 0
    assert stand.get('/api/stand/sber-mirror/status').json['enabled'] is True
    assert mirror.status(appmod)['window_limit'] == 300
    assert mirror.status(appmod)['last_seen_count'] == 1


def test_history_cutoff_and_board_protection(stand, monkeypatch):
    old, fresh = income(20), income(1)
    monkeypatch.setattr(mirror.stand_egress, 'read_get',
                        lambda *a, **kw: (200, {'success': True, 'incomes': [old, fresh]}))
    assert mirror.poll(appmod)
    data, version = board()
    assert [x['uuid'] for x in data['incomes']] == [fresh['uuid']]
    db = appmod.get_session()
    assert db.query(appmod.SberIncome).filter(appmod.SberIncome.uuid.in_([old['uuid'], fresh['uuid']])).count() == 2
    db.close()
    data['incomes'][0]['payer'] = 'подмена'
    data['incomes'][0]['source'] = 'demo'
    data['incomes'][0]['purpose'] = 'подмена'
    response = stand.put('/api/stand/state', json={'version': version, 'data': data})
    assert response.status_code == 200
    saved = response.json['data']['incomes'][0]
    assert (saved['payer'], saved['source'], saved['purpose']) == ('Иванов', 'sber', 'Договор 1')
    data = response.json['data']
    data['incomes'] = []
    response = stand.put('/api/stand/state', json={'version': response.json['version'], 'data': data})
    assert len(response.json['data']['incomes']) == 1


def test_error_and_429_keep_loop_alive_without_secret(stand, monkeypatch, caplog):
    responses = iter([(429, None), (200, {'success': True, 'incomes': []})])
    monkeypatch.setattr(mirror.stand_egress, 'read_get', lambda *a, **kw: next(responses))
    with caplog.at_level(logging.WARNING):
        assert not mirror.poll(appmod)
    assert mirror.status(appmod)['last_error'] == 'HTTP 429'
    assert 'secret-should-not-be-logged' not in caplog.text
    assert mirror.poll(appmod)
    assert mirror.status(appmod)['last_error'] is None


def test_disabled_off_stand_never_starts_or_polls(stand, monkeypatch):
    monkeypatch.setattr(appmod, 'STAND_MODE', False)
    monkeypatch.setattr(mirror.stand_egress, 'read_get',
                        lambda *a, **kw: pytest.fail('network called'))
    assert mirror.start(appmod) is False
    assert mirror.poll(appmod) is False


def test_bad_amounts_conflicting_uuid_and_limited_window(stand, monkeypatch):
    valid = income()
    bad = []
    for value in ('NaN', -1, 10**15):
        item = income()
        item['amount_rub'] = value
        bad.append(item)
    conflict = income()
    changed = dict(conflict, amount_rub=99)
    batch = [valid, conflict, changed] + bad
    monkeypatch.setattr(mirror.stand_egress, 'read_get',
                        lambda *a: (200, {'success': True, 'incomes': batch}))
    assert mirror.poll(appmod)
    assert [i['uuid'] for i in board()[0]['incomes']] == [valid['uuid']]
    assert mirror.status(appmod)['last_seen_count'] == len(batch)
    assert mirror.status(appmod)['limited_window'] is True
    # Окно 300 строк не содержит задним числом вставленный старый приход.
    # Статус сообщает предел, не обещая полного охвата истории.
    batch[:] = [income() for _ in range(300)]
    assert mirror.poll(appmod)
    assert mirror.status(appmod)['last_seen_count'] == 300
    assert mirror.status(appmod)['window_limit'] == 300


def test_copied_sql_history_appears_during_429_and_acquiring_gross(stand, monkeypatch):
    item = income(1)
    item['purpose'] = 'Зачисление средств по операциям эквайринга. Комиссия 700.00.'
    db = appmod.get_session()
    db.add(appmod.SberIncome(uuid=item['uuid'], operation_date=item['operation_date'],
                             amount_rub=99300, payer=item['payer'],
                             purpose=item['purpose'], doc_number='42'))
    db.commit()
    db.close()
    monkeypatch.setattr(mirror.stand_egress, 'read_get', lambda *a: (429, None))
    assert not mirror.poll(appmod)
    record = board()[0]['incomes'][0]
    assert (record['rub'], record['feeRub'], record['grossRub']) == (99300, 700, 100000)
    assert record['kind'] == 'эквайринг'
    assert mirror.status(appmod)['last_error'] == 'HTTP 429'


def test_client_cannot_reserve_bank_id_before_sql_bridge(stand, monkeypatch):
    item = income()
    fake = {'id': 'sber:' + item['uuid'], 'source': 'demo', 'rub': 1,
            'payer': 'подделка', 'dealId': 77}
    response = stand.put('/api/stand/state', json={'version': 0, 'data': {'incomes': [fake]}})
    assert response.status_code == 200
    monkeypatch.setattr(mirror.stand_egress, 'read_get',
                        lambda *a: (200, {'success': True, 'incomes': [item]}))
    assert mirror.poll(appmod)
    saved = board()[0]['incomes']
    assert len(saved) == 1
    assert (saved[0]['source'], saved[0]['rub'], saved[0]['dealId']) == ('sber', 12345.67, None)
