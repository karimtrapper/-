"""
Язык партнёрского кабинета (`Referrer.lang`): англоязычные застройщики
получают кабинет, ссылку для клиента и DM-уведомления на английском.

Запуск: cd Dev/CalcCRM && python -m pytest tests/test_referrer_lang.py -v
"""
import pytest
import sys
import os
import json
import secrets

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ['SECRET_KEY'] = 'test-secret-key-for-pytest'
os.environ['REF_LOGIN_BOT_TOKEN'] = '111:TEST_TOKEN'

from app import (app, get_session, Referrer, PayoutRequest, AdminUser,
                 Deal, DealAgent, DealType, DealStatus,
                 referral_links, ref_lang, ref_t, _cancel_button)


@pytest.fixture(autouse=True)
def clean_db():
    def _clean():
        s = get_session()
        try:
            s.query(PayoutRequest).delete()
            s.query(DealAgent).delete()
            s.query(Deal).delete()
            s.query(Referrer).delete()
            s.commit()
        finally:
            s.close()
    _clean()
    yield
    _clean()


@pytest.fixture
def client():
    """Test client с сессией админа: /api/referrers закрыт check_auth."""
    app.config['TESTING'] = True
    s = get_session()
    try:
        a = s.query(AdminUser).first()
        if not a:
            a = AdminUser(username='test_lang_admin', display_name='T',
                          password_hash=AdminUser.hash_password('x'))
            s.add(a)
            s.commit()
        aid = a.id
    finally:
        s.close()
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess['user_id'] = aid
        yield c


def _mk_ref(lang='ru'):
    s = get_session()
    try:
        r = Referrer(name='Dev', code='GR-L' + secrets.token_hex(2),
                     token=secrets.token_hex(16), default_percent=10.0, lang=lang)
        s.add(r)
        s.commit()
        return r.id, r.token
    finally:
        s.close()


# ── Хранение и API ────────────────────────────────────────────────────────

def test_create_referrer_with_lang(client):
    resp = client.post('/api/referrers', json={'name': 'Sansiri', 'lang': 'en'})
    data = resp.get_json()
    assert data['success'] is True
    assert data['referrer']['lang'] == 'en'


def test_create_referrer_defaults_to_ru(client):
    data = client.post('/api/referrers', json={'name': 'Аврора'}).get_json()
    assert data['referrer']['lang'] == 'ru'


def test_unknown_lang_falls_back_to_ru(client):
    data = client.post('/api/referrers', json={'name': 'X', 'lang': 'fr'}).get_json()
    assert data['referrer']['lang'] == 'ru'


def test_update_lang(client):
    rid, _ = _mk_ref('ru')
    data = client.put(f'/api/referrers/{rid}', json={'lang': 'en'}).get_json()
    assert data['referrer']['lang'] == 'en'


def test_update_ignores_unknown_lang(client):
    """Мусор в поле не должен молча сбрасывать язык кабинета на русский."""
    rid, _ = _mk_ref('en')
    data = client.put(f'/api/referrers/{rid}', json={'lang': 'de'}).get_json()
    assert data['referrer']['lang'] == 'en'


def test_stats_returns_lang(client):
    _, token = _mk_ref('en')
    data = client.get(f'/api/ref/{token}/stats').get_json()
    assert data['success'] is True
    assert data['lang'] == 'en'


# ── Ссылка для клиента ────────────────────────────────────────────────────

def test_wa_link_text_follows_lang():
    """Партнёр пересылает WA-ссылку своему клиенту — русский текст там мусор."""
    ru = referral_links('GR-TEST', 'ru')['wa_link']
    en = referral_links('GR-TEST', 'en')['wa_link']
    assert 'Hello' in en and '%D0%97' not in en          # без кириллицы
    assert 'Hello' not in ru
    # Метка источника одинаковая: аналитика не должна зависеть от языка
    assert 'ref_GRTEST' in en.replace('%20', ' ')
    assert 'ref_GRTEST' in ru.replace('%20', ' ').replace('+', ' ')


def test_stats_wa_link_localized(client):
    _, token = _mk_ref('en')
    data = client.get(f'/api/ref/{token}/stats').get_json()
    assert 'Hello' in data['wa_link']


# ── Уведомления ───────────────────────────────────────────────────────────

def test_ref_t_picks_language():
    s = get_session()
    try:
        ru = Referrer(name='a', code='GR-A1', token='t1', lang='ru')
        en = Referrer(name='b', code='GR-B1', token='t2', lang='en')
        assert ref_lang(ru) == 'ru' and ref_lang(en) == 'en'
        assert ref_t(ru, 'привет', 'hi') == 'привет'
        assert ref_t(en, 'привет', 'hi') == 'hi'
        assert ref_t(None, 'привет', 'hi') == 'привет'   # защитный дефолт
    finally:
        s.close()


def test_cancel_button_localized():
    s = get_session()
    try:
        en = Referrer(name='b', code='GR-B2', token='t3', lang='en')
        assert 'Cancel' in _cancel_button(5, en)[0][0]['text']
        assert 'Отменить' in _cancel_button(5)[0][0]['text']
    finally:
        s.close()


def test_payout_request_dm_in_english(client, monkeypatch):
    """Заявка на выплату от англоязычного партнёра → DM на английском."""
    sent = {}

    class Resp:
        status_code = 200

    def fake_post(url, **kw):
        if 'sendMessage' in url:
            sent['text'] = (kw.get('json') or {}).get('text', '')
        return Resp()

    monkeypatch.setattr('app.requests.post', fake_post)

    rid, token = _mk_ref('en')
    s = get_session()
    try:
        r = s.query(Referrer).get(rid)
        r.telegram_user_id = 4242
        # Баланс считается из deal_agents, не из счётчиков реферера
        deal = Deal(deal_type=DealType('pay_in'), status=DealStatus.COMPLETED, profit_usdt=200)
        deal.agents.append(DealAgent(referrer_id=rid, name=r.name, tier=1,
                                     comp_model='fixed', payout_usdt=60.0, paid=False))
        s.add(deal)
        s.commit()
    finally:
        s.close()

    resp = client.post(f'/api/ref/{token}/payout-request', json={
        'payout_method': 'usdt', 'wallet': 'TXtest',
        'contact_method': 'telegram', 'contact_value': '@dev',
    })
    assert resp.get_json()['success'] is True
    assert 'Withdrawal request created' in sent['text']
    assert 'Заявка' not in sent['text']
