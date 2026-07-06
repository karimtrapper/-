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
