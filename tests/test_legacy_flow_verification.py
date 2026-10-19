"""Ворота на неподтверждённые флоу (тип сделки + способ Pay-In) в legacy CRM:
POST /api/deals (создание) и PUT /api/deals/<id> (смена при изменении полей).
Зеркалит tests/test_stand_flow_verification.py для стенда."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('SECRET_KEY', 'test-secret-key-for-pytest')

import pytest

from app import app, get_session, AdminUser, Deal, Client, Referrer, DealAgent, PayoutTx, PayoutTxUse


@pytest.fixture(autouse=True)
def clean_db():
    s = get_session()
    try:
        s.query(PayoutTxUse).delete()
        s.query(PayoutTx).delete()
        s.query(DealAgent).delete()
        s.query(Deal).delete()
        s.query(Client).delete()
        s.query(Referrer).delete()
        s.query(AdminUser).delete()
        s.commit()
    finally:
        s.close()
    yield


def _client_as(role):
    s = get_session()
    try:
        user = AdminUser(username='legacy-gate-' + role, display_name='T',
                         role=role, password_hash='unused')
        s.add(user)
        s.commit()
        uid = user.id
    finally:
        s.close()
    client = app.test_client()
    with client.session_transaction() as sess:
        sess['user_id'] = uid
    return client


def _rental_cash_payload(**extra):
    data = {'client_name': 'Rental cash probe', 'deal_kind': 'rental',
           'payin_method': 'partners_cash'}
    data.update(extra)
    return data


def _freehold_requisites_payload(**extra):
    data = {'client_name': 'Freehold requisites probe', 'deal_kind': 'mf_freehold',
           'payin_method': 'sber_reqs', 'realty_purpose': 'x', 'invoice_amount_usd': 100,
           'transfer_fee_percent': .8, 'transfer_fee_fixed_usd': 50}
    data.update(extra)
    return data


def test_legacy_create_unverified_combo_rejected_for_manager():
    resp = _client_as('manager').post('/api/deals', json=_rental_cash_payload())
    assert resp.status_code == 400, resp.json
    assert resp.json['error'] == ('Этот флоу (тип сделки + способ оплаты) ещё не проверен. '
                                   'Проведите сделку через Карима.')


def test_legacy_create_unverified_combo_rejected_for_admin_without_confirm():
    resp = _client_as('admin').post('/api/deals', json=_rental_cash_payload())
    assert resp.status_code == 409, resp.json
    assert resp.json['requires_confirmation'] is True


def test_legacy_create_unverified_combo_allowed_for_admin_with_confirm():
    resp = _client_as('admin').post('/api/deals',
        json=_rental_cash_payload(unverified_confirmed=True))
    assert resp.status_code == 201, resp.json


def test_legacy_create_verified_combo_allowed_for_manager():
    resp = _client_as('manager').post('/api/deals', json=_freehold_requisites_payload())
    assert resp.status_code == 201, resp.json


def test_legacy_manager_cannot_bypass_with_confirm_flag():
    resp = _client_as('manager').post('/api/deals',
        json=_rental_cash_payload(unverified_confirmed=True))
    assert resp.status_code == 400, resp.json
    assert resp.json['error'] == ('Этот флоу (тип сделки + способ оплаты) ещё не проверен. '
                                   'Проведите сделку через Карима.')


def test_legacy_existing_unverified_deal_edit_of_unrelated_field_untouched():
    admin = _client_as('admin')
    created = admin.post('/api/deals',
        json=_rental_cash_payload(unverified_confirmed=True))
    assert created.status_code == 201, created.json
    deal_id = created.json['deal']['id']
    manager = _client_as('manager')
    edited = manager.put(f'/api/deals/{deal_id}', json={'client_name': 'Renamed client'})
    assert edited.status_code == 200, edited.json


def test_legacy_edit_to_unverified_combo_rejected_for_manager():
    admin = _client_as('admin')
    created = admin.post('/api/deals', json=_freehold_requisites_payload())
    assert created.status_code == 201, created.json
    deal_id = created.json['deal']['id']
    manager = _client_as('manager')
    edited = manager.put(f'/api/deals/{deal_id}',
                         json={**_freehold_requisites_payload(), 'payin_method': 'partners_cash'})
    assert edited.status_code == 400, edited.json
    assert edited.json['error'] == ('Этот флоу (тип сделки + способ оплаты) ещё не проверен. '
                                     'Проведите сделку через Карима.')
