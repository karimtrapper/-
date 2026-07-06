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
