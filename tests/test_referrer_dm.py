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


def test_webhook_bad_secret():
    with app.test_client() as c:
        r = c.post('/api/tg/lk-webhook', json={}, headers={'X-Telegram-Bot-Api-Secret-Token': 'wrong'})
    assert r.status_code == 403


def test_webhook_cancel_by_owner(monkeypatch):
    monkeypatch.setattr('app.requests.post', lambda *a, **k: type('R', (), {'status_code': 200})())
    rid, _ = _mk_ref(telegram_user_id=42)
    s = get_session()
    req = PayoutRequest(referrer_id=rid, amount_usdt=50, wallet='x',
                        contact_method='telegram', contact_value='@e', status='new')
    s.add(req); s.commit(); req_id = req.id; s.close()
    update = {'callback_query': {'id': 'cq1', 'from': {'id': 42}, 'data': f'cancel:{req_id}',
              'message': {'message_id': 5, 'chat': {'id': 42}}}}
    with app.test_client() as c:
        r = c.post('/api/tg/lk-webhook', json=update,
                   headers={'X-Telegram-Bot-Api-Secret-Token': 'whsecret'})
    assert r.status_code == 200
    s = get_session()
    assert s.query(PayoutRequest).get(req_id).status == 'cancelled'
    s.close()


def test_webhook_cancel_wrong_user(monkeypatch):
    monkeypatch.setattr('app.requests.post', lambda *a, **k: type('R', (), {'status_code': 200})())
    rid, _ = _mk_ref(telegram_user_id=42)
    s = get_session()
    req = PayoutRequest(referrer_id=rid, amount_usdt=50, wallet='x',
                        contact_method='telegram', contact_value='@e', status='new')
    s.add(req); s.commit(); req_id = req.id; s.close()
    update = {'callback_query': {'id': 'cq2', 'from': {'id': 999}, 'data': f'cancel:{req_id}',
              'message': {'message_id': 5, 'chat': {'id': 999}}}}
    with app.test_client() as c:
        r = c.post('/api/tg/lk-webhook', json=update,
                   headers={'X-Telegram-Bot-Api-Secret-Token': 'whsecret'})
    assert r.status_code == 200
    s = get_session()
    assert s.query(PayoutRequest).get(req_id).status == 'new'
    s.close()


def test_new_deal_notify_sends_dm_with_button(monkeypatch):
    """При завершённой сделке реферер-агент получает DM с суммой и кнопкой «Вывести»."""
    import json as _json
    from app import Deal, DealAgent, DealType, DealStatus, notify_agents_new_deal
    captured = []
    monkeypatch.setattr('app.requests.post',
                        lambda url, **k: captured.append(k.get('json')) or type('R', (), {'status_code': 200})())
    rid, token = _mk_ref(telegram_user_id=42)
    s = get_session()
    deal = Deal(deal_type=DealType('pay_in'), status=DealStatus.COMPLETED, profit_usdt=100)
    deal.agents.append(DealAgent(referrer_id=rid, name='Ed', tier=1,
                                 comp_model='fixed', payout_usdt=50, paid=False))
    s.add(deal); s.commit()
    notify_agents_new_deal(s, deal)
    did = deal.id
    s.close()
    # очистка своей сделки, чтобы не влиять на другие тесты
    s = get_session()
    s.query(DealAgent).filter_by(deal_id=did).delete()
    s.query(Deal).filter_by(id=did).delete(); s.commit(); s.close()

    assert captured, 'DM не отправлен'
    j = captured[0]
    assert j['chat_id'] == 42
    assert '$50.00' in j['text']
    kb = _json.loads(j['reply_markup'])['inline_keyboard']
    assert kb[0][0]['url'].endswith('/ref/' + token)


def test_new_deal_notify_skips_agent_without_tg(monkeypatch):
    """Агент без привязки TG не получает DM."""
    from app import Deal, DealAgent, DealType, DealStatus, notify_agents_new_deal
    captured = []
    monkeypatch.setattr('app.requests.post',
                        lambda url, **k: captured.append(1) or type('R', (), {'status_code': 200})())
    rid, _ = _mk_ref(telegram_user_id=None)
    s = get_session()
    deal = Deal(deal_type=DealType('pay_in'), status=DealStatus.COMPLETED, profit_usdt=100)
    deal.agents.append(DealAgent(referrer_id=rid, name='Ed', tier=1,
                                 comp_model='fixed', payout_usdt=50, paid=False))
    s.add(deal); s.commit(); did = deal.id
    notify_agents_new_deal(s, deal)
    s.close()
    s = get_session()
    s.query(DealAgent).filter_by(deal_id=did).delete()
    s.query(Deal).filter_by(id=did).delete(); s.commit(); s.close()
    assert captured == []


def test_paid_marks_only_snapshot_deals(monkeypatch):
    """Критикал-фикс: «Выплачено» помечает только сделки, вошедшие в заявку.
    Сделка, закрытая ПОСЛЕ создания заявки, остаётся неоплаченной."""
    monkeypatch.setattr('app.requests.post', lambda *a, **k: type('R', (), {'status_code': 200})())
    from app import Deal, DealAgent, DealType, DealStatus, AdminUser
    rid, token = _mk_ref(telegram_user_id=None)  # link-режим — заявка без TG-входа

    s = get_session()
    # Сделка №1 на $50 — ДО заявки
    d1 = Deal(deal_type=DealType('pay_in'), status=DealStatus.COMPLETED, profit_usdt=100)
    d1.agents.append(DealAgent(referrer_id=rid, name='Ed', tier=1,
                               comp_model='fixed', payout_usdt=50, paid=False))
    s.add(d1); s.commit(); d1_id = d1.id
    s.close()

    # Реферер создаёт заявку (снапшот = сделка №1)
    with app.test_client() as c:
        r = c.post(f'/api/ref/{token}/payout-request',
                   json={'wallet': 'w', 'contact_method': 'telegram', 'contact_value': '@e'})
        assert r.status_code == 200, r.get_json()
        req_id = r.get_json()['request']['id']

    # Сделка №2 на $30 — ПОСЛЕ заявки
    s = get_session()
    d2 = Deal(deal_type=DealType('pay_in'), status=DealStatus.COMPLETED, profit_usdt=60)
    d2.agents.append(DealAgent(referrer_id=rid, name='Ed', tier=1,
                               comp_model='fixed', payout_usdt=30, paid=False))
    s.add(d2); s.commit(); d2_id = d2.id
    # реальный админ для PATCH (check_auth ревалидирует по БД)
    a = s.query(AdminUser).first()
    if not a:
        a = AdminUser(username='snap_admin', display_name='S',
                      password_hash=AdminUser.hash_password('x'))
        s.add(a); s.commit()
    aid = a.id
    s.close()

    # Админ помечает заявку выплаченной
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess['user_id'] = aid
        r = c.patch(f'/api/payout-requests/{req_id}', json={'status': 'paid', 'tx_hash': '0xabc'})
        assert r.status_code == 200, r.get_json()

    # Проверка: №1 оплачена, №2 — НЕТ (осталась к выводу)
    s = get_session()
    ag1 = s.query(DealAgent).filter_by(deal_id=d1_id, referrer_id=rid).first()
    ag2 = s.query(DealAgent).filter_by(deal_id=d2_id, referrer_id=rid).first()
    paid1, paid2 = bool(ag1.paid), bool(ag2.paid)
    # уборка своих сделок
    s.query(DealAgent).filter(DealAgent.deal_id.in_([d1_id, d2_id])).delete(synchronize_session=False)
    s.query(Deal).filter(Deal.id.in_([d1_id, d2_id])).delete(synchronize_session=False)
    s.commit(); s.close()

    assert paid1 is True, 'сделка из заявки должна быть помечена оплаченной'
    assert paid2 is False, 'сделка, закрытая после заявки, НЕ должна помечаться оплаченной'
