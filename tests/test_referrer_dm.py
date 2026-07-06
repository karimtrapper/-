"""Тесты DM-уведомлений рефереру и inline-отмены."""
import pytest, sys, os, secrets

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ['SECRET_KEY'] = 'test-secret-key-for-pytest'
os.environ['REF_LOGIN_BOT_TOKEN'] = '111:TEST_TOKEN'
os.environ['REF_LK_WEBHOOK_SECRET'] = 'whsecret'

from app import (app, get_session, Referrer, PayoutRequest,
                 send_referrer_dm, _cancel_payout, _cancel_button)


@pytest.fixture(autouse=True)
def clean_db():
    s = get_session()
    try:
        s.query(PayoutRequest).delete(); s.query(Referrer).delete(); s.commit()
    finally:
        s.close()
    yield


def _mk_ref(**kw):
    s = get_session()
    try:
        r = Referrer(name='Ed', code='GR-D'+secrets.token_hex(2), token=secrets.token_hex(16),
                     default_percent=10.0, telegram_user_id=kw.get('telegram_user_id'))
        s.add(r); s.commit()
        return r.id, r.token
    finally:
        s.close()


def test_dm_skipped_without_tg_id(monkeypatch):
    calls = []
    monkeypatch.setattr('app.requests.post', lambda *a, **k: calls.append(1))
    rid, _ = _mk_ref(telegram_user_id=None)
    s = get_session(); r = s.query(Referrer).get(rid); s.close()
    assert send_referrer_dm(r, 'hi') is False
    assert calls == []


def test_dm_sent_with_tg_id(monkeypatch):
    class Resp: status_code = 200
    captured = {}
    def fake_post(url, **k):
        captured['url'] = url; captured['json'] = k.get('json'); return Resp()
    monkeypatch.setattr('app.requests.post', fake_post)
    rid, _ = _mk_ref(telegram_user_id=42)
    s = get_session(); r = s.query(Referrer).get(rid); s.close()
    assert send_referrer_dm(r, 'hi', buttons=_cancel_button(7)) is True
    assert captured['json']['chat_id'] == 42
    assert 'reply_markup' in captured['json']


def test_cancel_payout_helper():
    rid, _ = _mk_ref(telegram_user_id=42)
    s = get_session()
    req = PayoutRequest(referrer_id=rid, amount_usdt=50, wallet='x',
                        contact_method='telegram', contact_value='@e', status='new')
    s.add(req); s.commit(); req_id = req.id; s.close()
    s = get_session()
    req = s.query(PayoutRequest).get(req_id)
    assert _cancel_payout(s, req) is True
    s.close()
    s = get_session()
    assert s.query(PayoutRequest).get(req_id).status == 'cancelled'
    req = s.query(PayoutRequest).get(req_id)
    assert _cancel_payout(s, req) is False
    s.close()
