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
