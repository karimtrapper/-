"""Тесты вывода рефералов в батах: котировка Bitazza (VWAP −0.25% −20฿),
создание батовой заявки, запрет paid без чека, закрытие через чек."""
import io
import json
import pytest
import sys
import os
import secrets

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ['SECRET_KEY'] = 'test-secret-key-for-pytest'
os.environ['TELEGRAM_BOT_TOKEN'] = '111:TEST_TOKEN'

from app import (app, get_session, Referrer, Deal, DealType, DealStatus, DealAgent,
                 PayoutRequest, AdminUser, thb_payout_quote)


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clean_db():
    def _wipe():
        s = get_session()
        try:
            s.query(PayoutRequest).delete()
            s.query(DealAgent).delete()
            s.query(Deal).delete()
            s.query(Referrer).delete()
            s.commit()
        finally:
            s.close()
    _wipe()
    yield
    _wipe()


def _mk_ref_with_balance(payout=500.0):
    """Реферер (link-режим) + завершённая сделка с начислением payout."""
    s = get_session()
    try:
        r = Referrer(name='Lidia', code='GR-L' + secrets.token_hex(2),
                     token=secrets.token_hex(16), default_percent=10.0)
        s.add(r)
        s.commit()
        deal = Deal(deal_type=DealType('pay_in'), status=DealStatus.COMPLETED, profit_usdt=payout * 2)
        deal.agents.append(DealAgent(referrer_id=r.id, name='Lidia', tier=1,
                                     comp_model='fixed', payout_usdt=payout, paid=False))
        s.add(deal)
        s.commit()
        return r.id, r.token, deal.id
    finally:
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
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['user_id'] = aid
        yield client


BIDS = [(33.51, 300.0), (33.50, 300.0)]


# ── Котировка ─────────────────────────────────────────────────────────────

class TestThbQuote:
    def test_vwap_math(self):
        """VWAP на объём: 300@33.51 + 200@33.50 → −0.25% → −20฿, округление вниз."""
        q = thb_payout_quote(500, bids=BIDS)
        vwap = (300 * 33.51 + 200 * 33.50) / 500          # 33.506
        client = vwap * (1 - 0.0025)
        assert q['bitazza_rate'] == round(vwap, 4)
        assert q['client_rate'] == round(client, 4)
        assert q['thb_amount'] == int(500 * client - 20)   # 16691

    def test_book_not_deep_enough(self):
        """Стакан не покрыл объём — котировки нет (не считаем по неполному)."""
        assert thb_payout_quote(1000, bids=BIDS) is None

    def test_no_bids(self):
        assert thb_payout_quote(500, bids=[]) is None
        assert thb_payout_quote(0, bids=BIDS) is None


# ── Создание батовой заявки ───────────────────────────────────────────────

class TestCreateThbRequest:
    def _post(self, tc, token, monkeypatch, captured, **overrides):
        monkeypatch.setattr('app._bitazza_bids', lambda: [(33.51, 100000.0)])
        monkeypatch.setattr(
            'app.requests.post',
            lambda url, **k: captured.append(k.get('json') or k.get('data')) or
                             type('R', (), {'status_code': 200,
                                            'json': lambda self=None: {'result': {}}})())
        body = {
            'payout_method': 'thb', 'bank_name': 'Kasikorn (KBank)',
            'account_name': 'LIDIA IVANOVA', 'account_number': '123-4-56789-0',
            'contact_method': 'telegram', 'contact_value': '@lidia',
        }
        body.update(overrides)
        return tc.post(f'/api/ref/{token}/payout-request', json=body)

    def test_thb_request_fixes_rate(self, tc, monkeypatch):
        """Батовая заявка: курс зафиксирован сервером, реквизиты сохранены."""
        rid, token, _ = _mk_ref_with_balance(500)
        captured = []
        resp = self._post(tc, token, monkeypatch, captured)
        assert resp.status_code == 200, resp.get_json()
        req = resp.get_json()['request']
        assert req['payout_method'] == 'thb'
        assert req['bitazza_rate'] == 33.51
        assert req['client_rate'] == round(33.51 * 0.9975, 4)
        assert req['thb_amount'] == int(500 * 33.51 * 0.9975 - 20)
        assert req['bank_name'] == 'Kasikorn (KBank)'
        assert req['account_number'] == '123-4-56789-0'
        assert req['amount_usdt'] == 500
        # уведомление команде — батовый формат с курсом откупа
        texts = [c.get('text', '') for c in captured if isinstance(c, dict)]
        assert any('БАТЫ' in t and '33.51' in t for t in texts)

    def test_thb_without_bank_rejected(self, tc, monkeypatch):
        rid, token, _ = _mk_ref_with_balance(500)
        resp = self._post(tc, token, monkeypatch, [], bank_name='')
        assert resp.status_code == 400

    def test_thb_no_rate_returns_503(self, tc, monkeypatch):
        """Bitazza недоступна → заявка не создаётся, понятная ошибка."""
        rid, token, _ = _mk_ref_with_balance(500)
        monkeypatch.setattr('app._bitazza_bids', lambda: None)
        resp = tc.post(f'/api/ref/{token}/payout-request', json={
            'payout_method': 'thb', 'bank_name': 'SCB', 'account_name': 'A',
            'account_number': '1', 'contact_method': 'telegram', 'contact_value': '@x',
        })
        assert resp.status_code == 503

    def test_usdt_flow_unchanged(self, tc, monkeypatch):
        """Старый USDT-флоу работает как раньше (без банковских полей)."""
        rid, token, _ = _mk_ref_with_balance(500)
        captured = []
        monkeypatch.setattr(
            'app.requests.post',
            lambda url, **k: captured.append(1) or type('R', (), {'status_code': 200})())
        resp = tc.post(f'/api/ref/{token}/payout-request', json={
            'wallet': 'T' + 'X' * 30, 'contact_method': 'telegram', 'contact_value': '@x',
        })
        assert resp.status_code == 200
        req = resp.get_json()['request']
        assert req['payout_method'] == 'usdt'
        assert req['thb_amount'] is None

    def test_quote_endpoint(self, tc, monkeypatch):
        rid, token, _ = _mk_ref_with_balance(500)
        monkeypatch.setattr('app._bitazza_bids', lambda: [(33.51, 100000.0)])
        resp = tc.get(f'/api/ref/{token}/payout-quote')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['usdt'] == 500
        assert data['quote']['thb_amount'] == int(500 * 33.51 * 0.9975 - 20)


# ── paid: чек вместо хеша ────────────────────────────────────────────────

def _mk_thb_request(rid, deal_id, amount=500.0):
    s = get_session()
    try:
        req = PayoutRequest(
            referrer_id=rid, amount_usdt=amount, wallet='',
            contact_method='telegram', contact_value='@lidia', status='new',
            deal_ids=json.dumps([deal_id]), payout_method='thb',
            bitazza_rate=33.51, client_rate=33.4262, thb_amount=16693,
            bank_name='Kasikorn (KBank)', account_name='LIDIA IVANOVA',
            account_number='123-4-56789-0',
        )
        s.add(req)
        s.commit()
        return req.id
    finally:
        s.close()


class TestThbPaid:
    def test_patch_paid_blocked_for_thb(self, tc):
        """Батовую заявку нельзя закрыть PATCH'ем с tx_hash — только чек."""
        rid, token, deal_id = _mk_ref_with_balance(500)
        req_id = _mk_thb_request(rid, deal_id)
        resp = tc.patch(f'/api/payout-requests/{req_id}',
                        json={'status': 'paid', 'tx_hash': 'abc123'})
        assert resp.status_code == 400
        assert 'чек' in resp.get_json()['error'].lower()

    def test_receipt_closes_request_and_marks_deals(self, tc, monkeypatch):
        """Чек: заявка → paid, file_id сохранён, сделки снапшота помечены оплаченными."""
        rid, token, deal_id = _mk_ref_with_balance(500)
        req_id = _mk_thb_request(rid, deal_id)
        sent = []
        monkeypatch.setattr('app._tg_send_document',
                            lambda *a, **k: sent.append((a, k)) or 'FILE_ID_1')
        monkeypatch.setattr('app.mark_referrer_rewards_paid_in_gsheet', lambda *a, **k: None)
        resp = tc.post(f'/api/payout-requests/{req_id}/receipt',
                       data={'file': (io.BytesIO(b'fakejpg'), 'check.jpg')},
                       content_type='multipart/form-data')
        assert resp.status_code == 200, resp.get_json()
        req = resp.get_json()['request']
        assert req['status'] == 'paid'
        assert req['has_receipt'] is True
        assert sent, 'чек не отправлен в Telegram'
        s = get_session()
        try:
            rows = s.query(DealAgent).filter_by(referrer_id=rid).all()
            assert all(r.paid for r in rows), 'сделки снапшота не помечены оплаченными'
        finally:
            s.close()

    def test_receipt_rejected_for_usdt(self, tc, monkeypatch):
        rid, token, deal_id = _mk_ref_with_balance(500)
        s = get_session()
        try:
            req = PayoutRequest(referrer_id=rid, amount_usdt=500, wallet='TX' * 15,
                                contact_method='telegram', contact_value='@x', status='new')
            s.add(req); s.commit()
            req_id = req.id
        finally:
            s.close()
        resp = tc.post(f'/api/payout-requests/{req_id}/receipt',
                       data={'file': (io.BytesIO(b'x'), 'check.jpg')},
                       content_type='multipart/form-data')
        assert resp.status_code == 400

    def test_receipt_tg_failure_keeps_request_open(self, tc, monkeypatch):
        """Если чек не ушёл ни рефереру, ни в топик — заявка НЕ закрывается."""
        rid, token, deal_id = _mk_ref_with_balance(500)
        req_id = _mk_thb_request(rid, deal_id)
        monkeypatch.setattr('app._tg_send_document', lambda *a, **k: None)
        resp = tc.post(f'/api/payout-requests/{req_id}/receipt',
                       data={'file': (io.BytesIO(b'x'), 'check.jpg')},
                       content_type='multipart/form-data')
        assert resp.status_code == 502
        s = get_session()
        try:
            assert s.query(PayoutRequest).get(req_id).status == 'new'
        finally:
            s.close()
