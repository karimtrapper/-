"""Единый реестр кошельков: колонки миграции, валидация POST/PATCH /api/wallets.

Запуск: cd Dev/CalcCRM && python -m pytest tests/test_wallet_registry_api.py -v
"""
import pytest

from app import app, get_session, AdminUser, Wallet


ADDR = 'TKkeEVf2zySaWTLyX2qPwvi6kcdHRuPxkJ'
ADDR2 = 'TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn'


@pytest.fixture(autouse=True)
def clean_wallets():
    s = get_session()
    try:
        s.query(Wallet).delete()
        s.commit()
    finally:
        s.close()
    yield


@pytest.fixture
def tc():
    app.config['TESTING'] = True
    s = get_session()
    try:
        a = s.query(AdminUser).first()
        if not a:
            a = AdminUser(username='wallet_test_admin', display_name='T',
                          password_hash=AdminUser.hash_password('x'))
            s.add(a); s.commit()
        aid = a.id
    finally:
        s.close()
    c = app.test_client()
    with c.session_transaction() as sess:
        sess['user_id'] = aid
    return c


def test_migration_columns_exist_and_default():
    """Additive/nullable колонки: старая модель Wallet() без них продолжает работать."""
    s = get_session()
    try:
        w = Wallet(address=ADDR)
        s.add(w)
        s.commit()
        s.refresh(w)
        assert w.is_multisig is False
        assert w.accepts_payin is False
        assert w.owner is None
        d = w.to_dict()
        assert d['is_multisig'] is False
        assert d['accepts_payin'] is False
        assert d['owner'] is None
    finally:
        s.close()


def test_post_wallet_accepts_registry_fields(tc):
    r = tc.post('/api/wallets', json={
        'address': ADDR, 'blockchain': 'TRON', 'label': 'Тест',
        'is_multisig': True, 'accepts_payin': True, 'owner': 'компания',
    })
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body['success'] is True
    assert body['wallet']['is_multisig'] is True
    assert body['wallet']['accepts_payin'] is True
    assert body['wallet']['owner'] == 'компания'


def test_post_wallet_rejects_non_boolean_flags(tc):
    r = tc.post('/api/wallets', json={'address': ADDR, 'is_multisig': 'yes'})
    assert r.status_code == 400
    assert r.get_json()['success'] is False


def test_post_wallet_rejects_long_owner(tc):
    r = tc.post('/api/wallets', json={'address': ADDR, 'owner': 'a' * 101})
    assert r.status_code == 400


def test_post_wallet_existing_address_updates_registry_flags(tc):
    tc.post('/api/wallets', json={'address': ADDR})
    r = tc.post('/api/wallets', json={'address': ADDR, 'accepts_payin': True, 'owner': 'Теодор'})
    assert r.status_code == 200
    body = r.get_json()
    assert body['wallet']['accepts_payin'] is True
    assert body['wallet']['owner'] == 'Теодор'
    # Дубликата строки не создалось
    s = get_session()
    try:
        assert s.query(Wallet).filter(Wallet.address == ADDR).count() == 1
    finally:
        s.close()


def test_patch_wallet_accepts_registry_fields(tc):
    s = get_session()
    try:
        w = Wallet(address=ADDR2)
        s.add(w)
        s.commit()
        wid = w.id
    finally:
        s.close()
    r = tc.patch(f'/api/wallets/{wid}', json={'is_multisig': True, 'accepts_payin': True, 'owner': 'Андрей'})
    assert r.status_code == 200
    body = r.get_json()
    assert body['wallet']['is_multisig'] is True
    assert body['wallet']['accepts_payin'] is True
    assert body['wallet']['owner'] == 'Андрей'


def test_patch_wallet_rejects_non_boolean_flags(tc):
    s = get_session()
    try:
        w = Wallet(address=ADDR2)
        s.add(w)
        s.commit()
        wid = w.id
    finally:
        s.close()
    r = tc.patch(f'/api/wallets/{wid}', json={'accepts_payin': 1})
    assert r.status_code == 400


def test_patch_wallet_rejects_long_owner():
    s = get_session()
    try:
        w = Wallet(address=ADDR2)
        s.add(w)
        s.commit()
        wid = w.id
    finally:
        s.close()
    app.config['TESTING'] = True
    s2 = get_session()
    try:
        a = s2.query(AdminUser).first()
        if not a:
            a = AdminUser(username='wallet_test_admin2', display_name='T',
                          password_hash=AdminUser.hash_password('x'))
            s2.add(a); s2.commit()
        aid = a.id
    finally:
        s2.close()
    c = app.test_client()
    with c.session_transaction() as sess:
        sess['user_id'] = aid
    r = c.patch(f'/api/wallets/{wid}', json={'owner': 'b' * 200})
    assert r.status_code == 400


def test_patch_wallet_owner_empty_string_clears_owner(tc):
    s = get_session()
    try:
        w = Wallet(address=ADDR2, owner='Андрей')
        s.add(w)
        s.commit()
        wid = w.id
    finally:
        s.close()
    r = tc.patch(f'/api/wallets/{wid}', json={'owner': '  '})
    assert r.status_code == 200
    assert r.get_json()['wallet']['owner'] is None
