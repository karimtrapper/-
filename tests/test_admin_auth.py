"""Тесты passwordless-входа админов через Telegram."""
import pytest, sys, os, secrets, hmac, hashlib, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ['SECRET_KEY'] = 'test-secret-key-for-pytest'
os.environ['REF_LOGIN_BOT_TOKEN'] = '111:TEST_TOKEN'

from app import app, get_session, AdminUser, _match_admin_by_tg


@pytest.fixture(autouse=True)
def clean_admins():
    s = get_session()
    try:
        s.query(AdminUser).delete(); s.commit()
    finally:
        s.close()
    yield
    s = get_session()
    try:
        s.query(AdminUser).delete(); s.commit()
    finally:
        s.close()


def _mk_admin(**kw):
    s = get_session()
    try:
        a = AdminUser(username=kw.get('username', 'u' + secrets.token_hex(2)),
                      display_name=kw.get('display_name', 'Admin'),
                      password_hash=AdminUser.hash_password('x'),
                      telegram=kw.get('telegram'),
                      telegram_user_id=kw.get('telegram_user_id'))
        s.add(a); s.commit()
        return a.id
    finally:
        s.close()


def _signed(data, token='111:TEST_TOKEN'):
    secret = hashlib.sha256(token.encode()).digest()
    check = '\n'.join(f'{k}={data[k]}' for k in sorted(data) if k != 'hash')
    data = dict(data)
    data['hash'] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return data


def test_admin_to_dict_has_tg_fields():
    aid = _mk_admin(telegram='@kareem', telegram_user_id=None)
    s = get_session(); a = s.query(AdminUser).get(aid); d = a.to_dict(); s.close()
    assert d['telegram'] == '@kareem' and d['bound'] is False


def test_tg_login_matches_by_username_and_binds():
    _mk_admin(telegram='@kareem', telegram_user_id=None)
    with app.test_client() as c:
        payload = _signed({'id': 555, 'first_name': 'K', 'username': 'kareem', 'auth_date': int(time.time())})
        r = c.post('/api/auth/tg-login', json=payload)
        assert r.status_code == 200 and r.get_json()['success'] is True
        r2 = c.get('/api/auth/me')
        assert r2.status_code == 200


def test_tg_login_not_whitelisted_rejected():
    _mk_admin(telegram='@someone', telegram_user_id=None)
    with app.test_client() as c:
        payload = _signed({'id': 555, 'first_name': 'X', 'username': 'intruder', 'auth_date': int(time.time())})
        r = c.post('/api/auth/tg-login', json=payload)
        assert r.status_code == 403


def test_tg_login_bad_signature():
    _mk_admin(telegram='@kareem')
    with app.test_client() as c:
        payload = _signed({'id': 555, 'first_name': 'K', 'username': 'kareem', 'auth_date': int(time.time())})
        payload['hash'] = 'bad'
        r = c.post('/api/auth/tg-login', json=payload)
        assert r.status_code == 403


def test_tg_config_public():
    with app.test_client() as c:
        r = c.get('/api/auth/tg-config')
        assert r.status_code == 200 and 'bot_id' in r.get_json()


def _login(c):
    """Логинит тест-клиент как реально существующий админ (создаёт, если список пуст).
    Нужен реальный id: check_auth теперь ревалидирует сессию по БД."""
    s = get_session()
    try:
        a = s.query(AdminUser).first()
        if not a:
            a = AdminUser(username='sess_admin', display_name='S',
                          password_hash=AdminUser.hash_password('x'), telegram='@sess')
            s.add(a); s.commit()
        aid = a.id
    finally:
        s.close()
    with c.session_transaction() as sess:
        sess['user_id'] = aid


def test_create_admin_with_telegram():
    with app.test_client() as c:
        _login(c)
        r = c.post('/api/admins', json={'display_name': 'Валера', 'telegram': '@valera'})
        assert r.status_code == 200
        assert r.get_json()['admin']['telegram'] == '@valera'


def test_create_admin_requires_telegram():
    with app.test_client() as c:
        _login(c)
        r = c.post('/api/admins', json={'display_name': 'Ноль'})
        assert r.status_code == 400


def test_delete_last_admin_blocked():
    aid = _mk_admin(telegram='@solo')
    with app.test_client() as c:
        _login(c)
        r = c.delete(f'/api/admins/{aid}')
    assert r.status_code == 400


def test_deleted_admin_session_revoked():
    """Сессия удалённого админа (несуществующий user_id) не даёт доступа к защищённым API."""
    aid = _mk_admin(telegram='@live')
    with app.test_client() as c:
        # валидный админ → доступ есть
        with c.session_transaction() as sess:
            sess['user_id'] = aid
        assert c.get('/api/admins').status_code == 200
        # тот же клиент, но user_id указывает на несуществующего админа → разлог
        with c.session_transaction() as sess:
            sess['user_id'] = 999999
        assert c.get('/api/admins').status_code == 401


def test_bot_login_flow(monkeypatch):
    """Вход через бота: tg-start → webhook /start login_<nonce> → tg-poll выдаёт сессию."""
    import app as app_module
    monkeypatch.setattr('app.requests.post', lambda *a, **k: type('R', (), {'status_code': 200})())
    monkeypatch.setattr(app_module, '_login_bot_username_cache', 'testbot')
    os.environ['REF_LK_WEBHOOK_SECRET'] = 'whsecret'
    _mk_admin(telegram='@kareem', telegram_user_id=None)
    with app.test_client() as c:
        r = c.post('/api/auth/tg-start')
        assert r.status_code == 200, r.get_json()
        j = r.get_json()
        nonce = j['nonce']
        assert f'login_{nonce}' in j['link']
        # до подтверждения — pending
        assert c.get(f'/api/auth/tg-poll?nonce={nonce}').get_json()['status'] == 'pending'
        # webhook: юзер нажал Start с whitelisted-аккаунта
        upd = {'message': {'text': f'/start login_{nonce}', 'chat': {'id': 555},
                           'from': {'id': 555, 'username': 'kareem'}}}
        rw = c.post('/api/tg/lk-webhook', json=upd,
                    headers={'X-Telegram-Bot-Api-Secret-Token': 'whsecret'})
        assert rw.status_code == 200
        # поллинг → сессия
        d = c.get(f'/api/auth/tg-poll?nonce={nonce}').get_json()
        assert d['status'] == 'ok', d
        assert c.get('/api/auth/me').status_code == 200
        # nonce одноразовый
        assert c.get(f'/api/auth/tg-poll?nonce={nonce}').status_code == 404


def test_bot_login_denied_for_stranger(monkeypatch):
    """Не-whitelisted аккаунт получает denied, сессия не выдаётся."""
    import app as app_module
    monkeypatch.setattr('app.requests.post', lambda *a, **k: type('R', (), {'status_code': 200})())
    monkeypatch.setattr(app_module, '_login_bot_username_cache', 'testbot')
    os.environ['REF_LK_WEBHOOK_SECRET'] = 'whsecret'
    _mk_admin(telegram='@kareem', telegram_user_id=None)
    with app.test_client() as c:
        nonce = c.post('/api/auth/tg-start').get_json()['nonce']
        upd = {'message': {'text': f'/start login_{nonce}', 'chat': {'id': 999},
                           'from': {'id': 999, 'username': 'intruder'}}}
        c.post('/api/tg/lk-webhook', json=upd,
               headers={'X-Telegram-Bot-Api-Secret-Token': 'whsecret'})
        d = c.get(f'/api/auth/tg-poll?nonce={nonce}').get_json()
        assert d['status'] == 'denied'
        assert c.get('/api/auth/me').status_code == 401
