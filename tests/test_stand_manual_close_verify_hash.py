"""Stateless preview-only hash verification для ручного закрытия сделки.

Эндпоинт ничего не пишет в доску: он лишь проверяет перевод по сети, чтобы
фронт мог мгновенно показать статус хеша. Авторитетная проверка происходит
отдельно, в момент самого закрытия (другая задача плана)."""
import json
import secrets

import app as m
from tests.payin_registry import ensure_payin_wallet
import pytest

pytestmark = pytest.mark.usefixtures('stand_demo_environment')


def _board():
    return {'deals': [{'id': 1474, 'code': 'СД-1474', 'client': 'Synthetic T24',
                       'type': 'Обмен валюты', 'step': 's14', 'closed': False,
                       'crmDealId': None, 'sentToClient': True, 'pay': {},
                       'amountUsdt': 100, 'payout': {'usdt': 90}, 'log': []}],
            'notes': []}


def _setup(monkeypatch, role='manager'):
    monkeypatch.setattr(m, 'STAND_MODE', True)
    m._stand_migrate()
    db = m.get_session()
    try:
        user = m.AdminUser(username='t24-' + secrets.token_hex(6), display_name='T24 User',
                           role=role, password_hash='unused')
        db.add(user)
        db.flush()
        uid = user.id
        row = db.query(m.StandState).filter_by(id=1).first()
        if row is None:
            row = m.StandState(id=1)
            db.add(row)
        row.data = json.dumps(_board())
        row.version = 1
        row.generation = secrets.token_hex(16)
        db.commit()
        return uid
    finally:
        db.close()


def _client(uid):
    client = m.app.test_client()
    with client.session_transaction() as sess:
        sess['user_id'] = uid
    return client


def _payload(**overrides):
    payload = {'dealId': 1474, 'direction': 'payin', 'network': 'trc20',
               'hash': '1' * 64, 'receiver': 'T' + '1' * 33}
    payload.update(overrides)
    return payload


def _post(client, **overrides):
    return client.post('/api/stand/manual-close/verify-hash', json=_payload(**overrides))


def test_verify_hash_requires_manager_or_admin_role(monkeypatch):
    uid = _setup(monkeypatch, role='operator')
    response = _post(_client(uid))
    assert response.status_code == 403
    assert response.json == {'success': False, 'error': 'forbidden'}


def test_verify_hash_rejects_unknown_deal(monkeypatch):
    uid = _setup(monkeypatch)
    response = _post(_client(uid), dealId=999999)
    assert response.status_code == 404


def test_verify_hash_rejects_non_dict_json_body(monkeypatch):
    # Valid JSON that is not an object (e.g. a list) must not crash the route
    # with an uncaught AttributeError on data.get(...) -> plain Flask 500.
    uid = _setup(monkeypatch)
    response = _client(uid).post('/api/stand/manual-close/verify-hash', json=[1, 2, 3])
    assert response.status_code == 400
    assert response.json == {'success': False, 'error': 'invalid_payload'}


def test_verify_hash_returns_confirmed_for_matching_transfer(monkeypatch):
    uid = _setup(monkeypatch)
    ensure_payin_wallet('T' + '1' * 33)
    calls = []

    def fake_verify_transfer(ref, network, sender, receiver, amount, **kwargs):
        calls.append((ref, network, sender, receiver, amount))
        # приход читает сеть: адреса наблюдаются, получатель — наш кошелёк из реестра
        return {'status': 'confirmed', 'verifiedAmount': 100.0,
                'verifiedAt': '2026-10-19T00:00:00+00:00', 'from': 'T' + '9' * 33,
                'to': 'T' + '1' * 33}

    monkeypatch.setattr(m, 'verify_transfer', fake_verify_transfer)
    response = _post(_client(uid))
    assert response.status_code == 200, response.json
    assert response.json == {'success': True, 'status': 'confirmed',
                              'verifiedAmount': 100.0,
                              'verifiedAt': '2026-10-19T00:00:00+00:00',
                              'from': 'T' + '9' * 33, 'to': 'T' + '1' * 33}
    assert len(calls) == 1
    assert calls[0][:2] == ('1' * 64, 'trc20')


def test_verify_hash_surfaces_unconfirmed_status(monkeypatch):
    uid = _setup(monkeypatch)
    monkeypatch.setattr(m, 'verify_transfer', lambda *a, **kw: {'status': 'pending'})
    response = _post(_client(uid))
    assert response.status_code == 422, response.json
    assert response.json['success'] is False
    assert response.json['status'] == 'pending'


def test_verify_hash_does_not_mutate_board_state(monkeypatch):
    uid = _setup(monkeypatch)
    ensure_payin_wallet('T' + '1' * 33)
    monkeypatch.setattr(m, 'verify_transfer', lambda *a, **kw: {
        'status': 'confirmed', 'verifiedAmount': 100.0,
        'verifiedAt': '2026-10-19T00:00:00+00:00', 'from': 'T' + '9' * 33,
        'to': 'T' + '1' * 33})
    db = m.get_session()
    try:
        row = db.query(m.StandState).filter_by(id=1).one()
        before_version, before_data = row.version, row.data
    finally:
        db.close()
    response = _post(_client(uid))
    assert response.status_code == 200, response.json
    db = m.get_session()
    try:
        row = db.query(m.StandState).filter_by(id=1).one()
        assert row.version == before_version
        assert row.data == before_data
    finally:
        db.close()
