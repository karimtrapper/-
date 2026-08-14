"""
Приход крипты частями: несколько хэшей на одной сделке.
Клиент часто присылает сумму 2-3 переводами — хэши хранятся списком,
payin_tx_hash остаётся первым (его читают карточка, выгрузка, DealCloser).

Запуск: cd Dev/CalcCRM && python -m pytest tests/test_payin_tx_hashes.py -v
"""
import pytest
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ['SECRET_KEY'] = 'test-secret-key-for-pytest'

from app import (app, get_session, Deal, Client, AdminUser, PayinTx, PayinTxUse,
                 _normalize_tx_hashes, _payin_hash_list, get_used_transaction_hashes)

H1 = 'bb99ba6d46a14e814cfcc68b71e80ee0f11f7f69f17adb962c955cc32d0117b9'
H2 = 'aa11bb22cc33dd44ee55ff66aa77bb88cc99dd00ee11ff22aa33bb44cc55dd66'
H3 = '11223344556677889900aabbccddeeff11223344556677889900aabbccddeeff'


@pytest.fixture(autouse=True)
def clean_db():
    s = get_session()
    try:
        s.query(PayinTxUse).delete()
        s.query(PayinTx).delete()
        s.query(Deal).delete()
        s.query(Client).delete()
        s.commit()
    finally:
        s.close()
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


def _payload(**extra):
    data = {
        'client_name': 'Crypto Parts',
        'deal_type': 'pay_in',
        'payin_method': 'crypto_direct',
        'payin_amount_usdt': 300000,
        'payout_amount_thb': 10000000,
        'payout_method': 'transfer',
    }
    data.update(extra)
    return data


class TestNormalize:
    """_normalize_tx_hashes — единый вход для формы и интеграций."""

    def test_objects_kept_with_amounts(self):
        out = _normalize_tx_hashes([{'hash': H1, 'amount_usdt': 100}, {'hash': H2, 'amount_usdt': '50.5'}])
        assert out == [{'hash': H1, 'amount_usdt': 100.0}, {'hash': H2, 'amount_usdt': 50.5}]

    def test_plain_strings_accepted(self):
        assert _normalize_tx_hashes([H1, H2]) == [
            {'hash': H1, 'amount_usdt': None}, {'hash': H2, 'amount_usdt': None}]

    def test_dedupe_and_drop_empty(self):
        out = _normalize_tx_hashes([H1, '  ', {'hash': H1, 'amount_usdt': 5}, None, {'hash': '  '}])
        assert [x['hash'] for x in out] == [H1]

    def test_broken_amount_becomes_none(self):
        assert _normalize_tx_hashes([{'hash': H1, 'amount_usdt': 'abc'}])[0]['amount_usdt'] is None

    def test_tx_hash_key_alias(self):
        assert _normalize_tx_hashes([{'tx_hash': H1}])[0]['hash'] == H1


class TestCreateDeal:
    """POST /api/deals с несколькими хэшами."""

    def test_hashes_saved_and_first_mirrored(self, tc, db):
        resp = tc.post('/api/deals', json=_payload(payin_tx_hashes=[
            {'hash': H1, 'amount_usdt': 200000},
            {'hash': H2, 'amount_usdt': 100000},
        ]))
        deal = resp.json['deal']
        assert [x['hash'] for x in deal['payin_tx_hashes']] == [H1, H2]
        assert deal['payin_tx_hash'] == H1, 'первый хэш дублируется в легаси-поле'
        assert deal['payin_amount_usdt'] == 300000

    def test_amounts_preserved(self, tc):
        resp = tc.post('/api/deals', json=_payload(payin_tx_hashes=[
            {'hash': H1, 'amount_usdt': 200000}, {'hash': H2, 'amount_usdt': 100000}]))
        parts = resp.json['deal']['payin_tx_hashes']
        assert sum(p['amount_usdt'] for p in parts) == 300000

    def test_single_hash_still_works(self, tc):
        """Старый путь без списка не сломан."""
        resp = tc.post('/api/deals', json=_payload(payin_tx_hash=H1))
        deal = resp.json['deal']
        assert deal['payin_tx_hash'] == H1
        assert deal['payin_tx_hashes'] is None

    def test_duplicates_collapsed(self, tc):
        resp = tc.post('/api/deals', json=_payload(payin_tx_hashes=[H1, H1, H2]))
        assert [x['hash'] for x in resp.json['deal']['payin_tx_hashes']] == [H1, H2]


class TestUpdateDeal:
    """PUT /api/deals/<id> — добавление и снятие частей."""

    def test_add_parts_to_existing_deal(self, tc):
        did = tc.post('/api/deals', json=_payload(payin_tx_hash=H1)).json['deal']['id']
        resp = tc.put(f'/api/deals/{did}', json={'payin_tx_hashes': [
            {'hash': H1, 'amount_usdt': 200000}, {'hash': H2, 'amount_usdt': 100000}]})
        deal = resp.json['deal']
        assert len(deal['payin_tx_hashes']) == 2
        assert deal['payin_tx_hash'] == H1

    def test_empty_list_clears_parts_keeps_manual_hash(self, tc):
        did = tc.post('/api/deals', json=_payload(payin_tx_hashes=[H1, H2])).json['deal']['id']
        resp = tc.put(f'/api/deals/{did}', json={'payin_tx_hashes': [], 'payin_tx_hash': H3})
        deal = resp.json['deal']
        assert deal['payin_tx_hashes'] is None
        assert deal['payin_tx_hash'] == H3

    def test_reorder_updates_mirrored_hash(self, tc):
        did = tc.post('/api/deals', json=_payload(payin_tx_hashes=[H1, H2])).json['deal']['id']
        resp = tc.put(f'/api/deals/{did}', json={'payin_tx_hashes': [H2, H1]})
        assert resp.json['deal']['payin_tx_hash'] == H2


class TestUsedHashes:
    """Все части попадают в «уже использованные» — иначе один приход заведут дважды."""

    def test_all_parts_marked_used(self, tc, db):
        tc.post('/api/deals', json=_payload(payin_tx_hashes=[H1, H2]))
        used = get_used_transaction_hashes(db)
        assert H1 in used and H2 in used

    def test_unrelated_hash_not_used(self, tc, db):
        tc.post('/api/deals', json=_payload(payin_tx_hashes=[H1]))
        assert H3 not in get_used_transaction_hashes(db)


class TestPayinHashList:
    """_payin_hash_list — источник для выгрузки в Sheet."""

    def test_list_from_json(self, tc, db):
        did = tc.post('/api/deals', json=_payload(payin_tx_hashes=[H1, H2])).json['deal']['id']
        deal = db.query(Deal).get(did)
        assert _payin_hash_list(deal) == [H1, H2]

    def test_fallback_to_single_hash(self, tc, db):
        did = tc.post('/api/deals', json=_payload(payin_tx_hash=H1)).json['deal']['id']
        deal = db.query(Deal).get(did)
        assert _payin_hash_list(deal) == [H1]

    def test_empty_deal_gives_empty_list(self, tc, db):
        did = tc.post('/api/deals', json=_payload()).json['deal']['id']
        deal = db.query(Deal).get(did)
        assert _payin_hash_list(deal) == []

    def test_broken_json_does_not_crash(self, tc, db):
        did = tc.post('/api/deals', json=_payload(payin_tx_hash=H1)).json['deal']['id']
        deal = db.query(Deal).get(did)
        deal.payin_tx_hashes = 'не json'
        db.commit()
        assert _payin_hash_list(deal) == [H1]
