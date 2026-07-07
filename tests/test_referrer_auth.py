"""Тесты входа в реферальный кабинет через Telegram."""
import pytest, sys, os, secrets, hmac, hashlib, time, json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ['SECRET_KEY'] = 'test-secret-key-for-pytest'
os.environ['REF_LOGIN_BOT_TOKEN'] = '111:TEST_TOKEN'  # фиктивный, для HMAC

from app import app, get_session, Referrer, verify_telegram_auth, apply_referrer_tg_binding


@pytest.fixture(autouse=True)
def clean_db():
    s = get_session()
    try:
        s.query(Referrer).delete(); s.commit()
    finally:
        s.close()
    yield
    s = get_session()
    try:
        s.query(Referrer).delete(); s.commit()
    finally:
        s.close()


def _mk_referrer(**kw):
    s = get_session()
    try:
        r = Referrer(name=kw.get('name', 'Ed'), code=kw.get('code', 'GR-ED'),
                     token=kw.get('token', secrets.token_hex(16)),
                     default_percent=10.0, telegram=kw.get('telegram', '@ed_test'),
                     auth_mode=kw.get('auth_mode', 'link'),
                     telegram_user_id=kw.get('telegram_user_id'))
        s.add(r); s.commit()
        return r.to_dict()
    finally:
        s.close()


def test_referrer_defaults_to_link_mode():
    d = _mk_referrer()
    assert d['auth_mode'] == 'link'
    assert d['telegram_user_id'] is None


def _signed(data: dict, token='111:TEST_TOKEN'):
    """Собрать валидную подпись Telegram для data."""
    secret = hashlib.sha256(token.encode()).digest()
    check = '\n'.join(f'{k}={data[k]}' for k in sorted(data) if k != 'hash')
    data = dict(data)
    data['hash'] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return data


def test_verify_ok():
    d = _signed({'id': 42, 'first_name': 'Ed', 'auth_date': int(time.time())})
    assert verify_telegram_auth(d, '111:TEST_TOKEN') is True


def test_verify_bad_hash():
    d = _signed({'id': 42, 'first_name': 'Ed', 'auth_date': int(time.time())})
    d['hash'] = 'deadbeef'
    assert verify_telegram_auth(d, '111:TEST_TOKEN') is False


def test_verify_expired():
    d = _signed({'id': 42, 'first_name': 'Ed', 'auth_date': int(time.time()) - 90000})
    assert verify_telegram_auth(d, '111:TEST_TOKEN', max_age_sec=86400) is False


def test_verify_tampered_field():
    d = _signed({'id': 42, 'first_name': 'Ed', 'auth_date': int(time.time())})
    d['id'] = 999  # подменили после подписи
    assert verify_telegram_auth(d, '111:TEST_TOKEN') is False


def _get_referrer(rid_or_token):
    s = get_session()
    try:
        return s.query(Referrer).filter(Referrer.token == rid_or_token).first()
    finally:
        s.close()


def test_bind_by_username_match():
    d = _mk_referrer(telegram='@ed_test', token='t1')
    r = _get_referrer('t1')
    ok, err = apply_referrer_tg_binding(r, tg_id=42, tg_username='ed_test')
    assert ok is True and err is None
    assert _get_referrer('t1').telegram_user_id == 42


def test_bind_by_username_mismatch():
    _mk_referrer(telegram='@ed_test', token='t2')
    r = _get_referrer('t2')
    ok, err = apply_referrer_tg_binding(r, tg_id=42, tg_username='someone_else')
    assert ok is False and err


def test_bind_empty_username_trusts_first():
    _mk_referrer(telegram='', token='t3')
    r = _get_referrer('t3')
    ok, err = apply_referrer_tg_binding(r, tg_id=77, tg_username=None)
    assert ok is True
    assert _get_referrer('t3').telegram_user_id == 77


def test_prebound_id_must_match():
    _mk_referrer(telegram='@ed_test', token='t4', telegram_user_id=42)
    r = _get_referrer('t4')
    assert apply_referrer_tg_binding(r, tg_id=42, tg_username='ed_test')[0] is True
    r = _get_referrer('t4')
    ok, err = apply_referrer_tg_binding(r, tg_id=999, tg_username='ed_test')
    assert ok is False and err


def test_stats_link_mode_open():
    _mk_referrer(auth_mode='link', token='s1')
    with app.test_client() as c:
        r = c.get('/api/ref/s1/stats')
    assert r.status_code == 200 and r.get_json()['success'] is True


def test_stats_telegram_mode_requires_auth():
    _mk_referrer(auth_mode='telegram', telegram='@ed_test', token='s2')
    with app.test_client() as c:
        r = c.get('/api/ref/s2/stats')
    assert r.status_code == 401
    assert r.get_json().get('auth_required') is True


def test_tg_login_grants_access():
    _mk_referrer(auth_mode='telegram', telegram='@ed_test', token='s3')
    with app.test_client() as c:
        payload = _signed({'id': 42, 'first_name': 'Ed', 'username': 'ed_test',
                           'auth_date': int(time.time())})
        r = c.post('/api/ref/s3/tg-login', json=payload)
        assert r.status_code == 200 and r.get_json()['success'] is True
        r2 = c.get('/api/ref/s3/stats')
        assert r2.status_code == 200 and r2.get_json()['success'] is True


def test_tg_login_wrong_account_rejected():
    _mk_referrer(auth_mode='telegram', telegram='@ed_test', token='s4')
    with app.test_client() as c:
        payload = _signed({'id': 42, 'first_name': 'X', 'username': 'intruder',
                           'auth_date': int(time.time())})
        r = c.post('/api/ref/s4/tg-login', json=payload)
        assert r.status_code == 403


def test_tg_login_bad_signature_rejected():
    _mk_referrer(auth_mode='telegram', telegram='@ed_test', token='s5')
    with app.test_client() as c:
        payload = _signed({'id': 42, 'first_name': 'Ed', 'username': 'ed_test',
                           'auth_date': int(time.time())})
        payload['hash'] = 'deadbeef'
        r = c.post('/api/ref/s5/tg-login', json=payload)
        assert r.status_code == 403


def test_payout_request_blocked_without_tg_auth():
    _mk_referrer(auth_mode='telegram', telegram='@ed_test', token='p1')
    with app.test_client() as c:
        r = c.post('/api/ref/p1/payout-request',
                   json={'wallet': 'x', 'contact_method': 'telegram', 'contact_value': '@ed_test'})
    assert r.status_code == 401


def test_create_referrer_with_telegram_mode():
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess['user_id'] = 1  # CRUD-ручки рефереров требуют админ-сессию
        r = c.post('/api/referrers', json={'name': 'Zed', 'auth_mode': 'telegram', 'telegram': '@zed'})
        assert r.status_code == 200
        assert r.get_json()['referrer']['auth_mode'] == 'telegram'


def test_update_referrer_auth_mode_validated():
    rid = _mk_referrer(token='u1')['id']
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess['user_id'] = 1
        c.put(f'/api/referrers/{rid}', json={'auth_mode': 'garbage'})
        r = c.get('/api/ref/u1/stats')  # мусор → остался link → открыт
    assert r.status_code == 200


def test_referrer_bot_login_flow(monkeypatch):
    """Вход реферера через бота: tg-start → webhook /start → tg-poll выдаёт ref_auth."""
    import app as app_module
    monkeypatch.setattr('app.requests.post', lambda *a, **k: type('R', (), {'status_code': 200})())
    monkeypatch.setattr(app_module, '_login_bot_username_cache', 'testbot')
    os.environ['REF_LK_WEBHOOK_SECRET'] = 'whsecret'
    _mk_referrer(auth_mode='telegram', telegram='@ed_test', token='bt1')
    with app.test_client() as c:
        r = c.post('/api/ref/bt1/tg-start')
        assert r.status_code == 200, r.get_json()
        nonce = r.get_json()['nonce']
        assert c.get(f'/api/ref/bt1/tg-poll?nonce={nonce}').get_json()['status'] == 'pending'
        upd = {'message': {'text': f'/start login_{nonce}', 'chat': {'id': 42},
                           'from': {'id': 42, 'username': 'ed_test'}}}
        assert c.post('/api/tg/lk-webhook', json=upd,
                      headers={'X-Telegram-Bot-Api-Secret-Token': 'whsecret'}).status_code == 200
        d = c.get(f'/api/ref/bt1/tg-poll?nonce={nonce}').get_json()
        assert d['status'] == 'ok', d
        # сессия выдана → stats открыт
        assert c.get('/api/ref/bt1/stats').status_code == 200
        # nonce одноразовый
        assert c.get(f'/api/ref/bt1/tg-poll?nonce={nonce}').status_code == 404


def test_referrer_bot_login_wrong_account(monkeypatch):
    """Чужой аккаунт (username не совпал) → denied, stats закрыт."""
    import app as app_module
    monkeypatch.setattr('app.requests.post', lambda *a, **k: type('R', (), {'status_code': 200})())
    monkeypatch.setattr(app_module, '_login_bot_username_cache', 'testbot')
    os.environ['REF_LK_WEBHOOK_SECRET'] = 'whsecret'
    _mk_referrer(auth_mode='telegram', telegram='@ed_test', token='bt2')
    with app.test_client() as c:
        nonce = c.post('/api/ref/bt2/tg-start').get_json()['nonce']
        upd = {'message': {'text': f'/start login_{nonce}', 'chat': {'id': 999},
                           'from': {'id': 999, 'username': 'intruder'}}}
        c.post('/api/tg/lk-webhook', json=upd,
               headers={'X-Telegram-Bot-Api-Secret-Token': 'whsecret'})
        assert c.get(f'/api/ref/bt2/tg-poll?nonce={nonce}').get_json()['status'] == 'denied'
        assert c.get('/api/ref/bt2/stats').status_code == 401


def test_referrer_logout(monkeypatch):
    """Выход из кабинета: после logout stats снова требует вход."""
    import app as app_module
    monkeypatch.setattr('app.requests.post', lambda *a, **k: type('R', (), {'status_code': 200})())
    monkeypatch.setattr(app_module, '_login_bot_username_cache', 'testbot')
    os.environ['REF_LK_WEBHOOK_SECRET'] = 'whsecret'
    _mk_referrer(auth_mode='telegram', telegram='@ed_test', token='bt3')
    with app.test_client() as c:
        nonce = c.post('/api/ref/bt3/tg-start').get_json()['nonce']
        upd = {'message': {'text': f'/start login_{nonce}', 'chat': {'id': 42},
                           'from': {'id': 42, 'username': 'ed_test'}}}
        c.post('/api/tg/lk-webhook', json=upd,
               headers={'X-Telegram-Bot-Api-Secret-Token': 'whsecret'})
        c.get(f'/api/ref/bt3/tg-poll?nonce={nonce}')
        assert c.get('/api/ref/bt3/stats').status_code == 200
        assert c.post('/api/ref/bt3/logout').status_code == 200
        assert c.get('/api/ref/bt3/stats').status_code == 401


def test_referrer_owner_notified_on_foreign_attempt(monkeypatch):
    """Чужая попытка входа в привязанный кабинет → владельцу уходит DM-предупреждение."""
    import app as app_module
    captured = []
    monkeypatch.setattr('app.requests.post',
                        lambda url, **k: captured.append(k.get('json')) or type('R', (), {'status_code': 200})())
    monkeypatch.setattr(app_module, '_login_bot_username_cache', 'testbot')
    os.environ['REF_LK_WEBHOOK_SECRET'] = 'whsecret'
    _mk_referrer(auth_mode='telegram', telegram='@ed_test', token='bt4', telegram_user_id=42)
    with app.test_client() as c:
        nonce = c.post('/api/ref/bt4/tg-start').get_json()['nonce']
        upd = {'message': {'text': f'/start login_{nonce}', 'chat': {'id': 999},
                           'from': {'id': 999, 'username': 'intruder', 'first_name': 'X'}}}
        c.post('/api/tg/lk-webhook', json=upd,
               headers={'X-Telegram-Bot-Api-Secret-Token': 'whsecret'})
    owner_msgs = [m for m in captured if m and m.get('chat_id') == 42]
    assert owner_msgs, 'владелец не получил предупреждение'
    assert 'Попытка входа' in owner_msgs[-1]['text']
    assert '@intruder' in owner_msgs[-1]['text']
