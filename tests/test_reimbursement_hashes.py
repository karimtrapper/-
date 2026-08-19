"""
Возмещение с несколькими хэшами.

Регресс 04.08: `reimbursements.tx_hash` в модели давно Text, но в Postgres
остался VARCHAR(100) — возмещение, покрытое 6 переводами (~395 символов),
падало на INSERT со StringDataRightTruncation. На sqlite длина не проверяется,
поэтому тест страхует контракт API, а тип колонки чинит миграция в app.py.

Запуск: cd Dev/CalcCRM && python -m pytest tests/test_reimbursement_hashes.py -v
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ['SECRET_KEY'] = 'test-secret-key-for-pytest'

import app as appmod
from app import (app, get_session, Deal, Client, AdminUser, Reimbursement,
                 ReimbursementTx, ReimbursementTxUse)

HASHES = [
    'e68c2832dea7d5286753000000000000000000000000000000000000000000a1',
    'ccc683411df263539846000000000000000000000000000000000000000000a2',
    '43d19347ce5e7abb1583000000000000000000000000000000000000000000a3',
    '05988fca8277c7106653000000000000000000000000000000000000000000a4',
    '5a1edb9790444f0351f8000000000000000000000000000000000000000000a5',
    'ce10ab8327380e7373d5000000000000000000000000000000000000000000a6',
]


@pytest.fixture(autouse=True)
def clean_db(monkeypatch):
    s = get_session()
    try:
        s.query(Deal).delete()
        # Bulk-delete не тянет ORM-каскад, поэтому использования и сами переводы
        # чистим явно — иначе остаток по этим хэшам «съеден» прошлым тестом
        # и возмещение отобьётся как повторное.
        s.query(ReimbursementTxUse).delete()
        s.query(Reimbursement).delete()
        s.query(ReimbursementTx).delete()
        s.query(Client).delete()
        s.commit()
    finally:
        s.close()
    # Хэши тут синтетические — в сеть за суммой не ходим, сумма берётся из запроса
    monkeypatch.setattr(appmod, '_tron_tx_amount', lambda h: None)
    yield


@pytest.fixture
def db():
    s = get_session()
    yield s
    s.close()


@pytest.fixture
def tc():
    app.config['TESTING'] = True
    s = get_session()
    try:
        a = s.query(AdminUser).first()
        if not a:
            a = AdminUser(username='test_admin', display_name='T',
                          password_hash=AdminUser.hash_password('x'))
            s.add(a); s.commit()
        aid = a.id
    finally:
        s.close()
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess['user_id'] = aid
        yield c


@pytest.fixture
def deal(tc):
    """Сделка, ожидающая возмещения (выплата THB из кармана фаундера)."""
    resp = tc.post('/api/deals', json={
        'client_name': 'Reimb Client',
        'deal_type': 'pay_in',
        'payin_method': 'crypto_direct',
        'payin_amount_usdt': 520000,
        'payout_amount_thb': 16742400,
        'payout_method': 'transfer',
        'payout_source': 'founder_personal',
        'payout_founder_name': 'Андрей',
    })
    return resp.json['deal']


def test_six_hashes_accepted(tc, deal):
    """Главный регресс: 6 хэшей — это ~395 символов, VARCHAR(100) не хватало."""
    resp = tc.post('/api/reimbursements', json={
        'founder_name': 'Андрей',
        'deal_ids': [deal['id']],
        'amount_usdt': 504289,
        'tx_hashes': HASHES,
    })
    assert resp.json['success'], resp.json.get('error')


def test_all_hashes_stored_and_returned(tc, deal):
    tc.post('/api/reimbursements', json={
        'founder_name': 'Андрей', 'deal_ids': [deal['id']],
        'amount_usdt': 504289, 'tx_hashes': HASHES,
    })
    r = tc.get('/api/reimbursements').json['reimbursements'][0]
    assert r['tx_hashes'] == HASHES
    assert len(r['tx_hash']) > 100, 'строка длиннее старого лимита VARCHAR(100)'


def test_single_hash_still_works(tc, deal):
    resp = tc.post('/api/reimbursements', json={
        'founder_name': 'Андрей', 'deal_ids': [deal['id']],
        'amount_usdt': 504289, 'tx_hashes': [HASHES[0]],
    })
    assert resp.json['success']
    assert tc.get('/api/reimbursements').json['reimbursements'][0]['tx_hashes'] == [HASHES[0]]


def test_deal_completed_and_payout_set(tc, deal):
    """Возмещение закрывает сделку и проставляет выплату в USDT."""
    tc.post('/api/reimbursements', json={
        'founder_name': 'Андрей', 'deal_ids': [deal['id']],
        'amount_usdt': 504289, 'tx_hashes': HASHES,
    })
    updated = tc.get(f"/api/deals/{deal['id']}").json['deal']
    assert updated['status'] == 'completed'
    assert updated['payout_amount_usdt'] == 504289


def _mk_deal(tc, payout_thb, payout_usdt):
    """Ещё одна сделка того же фаундера, ждущая возмещения."""
    return tc.post('/api/deals', json={
        'client_name': 'Zakharov Vyacheslav - Grusha', 'deal_type': 'pay_in',
        'payin_method': 'crypto_direct', 'payin_amount_usdt': 330.28,
        'payout_amount_thb': payout_thb, 'payout_amount_usdt': payout_usdt,
        'payout_method': 'transfer', 'payout_source': 'founder_personal',
        'payout_founder_name': 'Андрей',
    }).json['deal']['id']


def test_reused_hash_error_names_previous_reimbursement(tc):
    """Повторный клик по устаревшей форме: ошибка говорит, где перевод уже учтён.

    Голое «доступно $0.00» читается как поломка CRM, хотя перевод просто
    полностью ушёл в созданное раньше возмещение (#469 / cbb092…, 19.08).
    """
    deal_a = _mk_deal(tc, 10000, 305.4)
    deal_b = _mk_deal(tc, 10000, 305.4)
    h = 'cbb092e5bc772b7e171ef078c3eb967b08f83bd59e38b3c7bf668207746a027a'
    body = {'founder_name': 'Андрей', 'amount_usdt': 305.4, 'tx_hashes': [h],
            'tx_uses': [{'tx_hash': h, 'amount_usdt': 305.4}]}

    first = tc.post('/api/reimbursements', json={**body, 'deal_ids': [deal_a]})
    assert first.status_code == 200
    rid = first.json['reimbursement']['id']

    again = tc.post('/api/reimbursements', json={**body, 'deal_ids': [deal_b]})
    assert again.status_code == 409
    assert f'#{rid}' in again.json['error']
    assert 'обнови страницу' in again.json['error']
    assert again.json['used_in'] == [{'reimbursement_id': rid, 'amount_usdt': 305.4}]
