import os
import sys
import asyncio
import tempfile
from unittest.mock import patch, MagicMock
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'ChannelsWorker'))
import tg_qr_login

# Ensure TelegramClient exists for patching
if not hasattr(tg_qr_login, "TelegramClient"):
    tg_qr_login.TelegramClient = None
if not hasattr(tg_qr_login, "SessionPasswordNeededError"):
    class DummyError(Exception): pass
    tg_qr_login.SessionPasswordNeededError = DummyError

class FakeQRLogin:
    def __init__(self, mode):
        self.url = "tg://login?token=fake1"
        self.mode = mode
        self.recreate_called = 0
        from datetime import datetime, timezone, timedelta
        self.expires = datetime.now(timezone.utc) + timedelta(seconds=30)

    async def wait(self, timeout=None):
        from unittest.mock import MagicMock
        if self.mode == "success" or self.mode.startswith("success_"):
            return MagicMock()
        elif self.mode == "timeout_then_success":
            if self.recreate_called == 0:
                await asyncio.sleep(0.1)
                raise asyncio.TimeoutError()
            else:
                return MagicMock()
        elif self.mode == "2fa":
            from unittest.mock import MagicMock
            raise tg_qr_login.SessionPasswordNeededError(request=MagicMock())
        elif self.mode == "error":
            raise ValueError("Some network error")

    async def recreate(self):
        self.recreate_called += 1
        self.url = f"tg://login?token=fake{self.recreate_called+1}"

class FakeTelegramClient:
    def __init__(self, session, api_id, api_hash, mode):
        self.session = session
        self.api_id = api_id
        self.api_hash = api_hash
        self.mode = mode
        self.disconnected = False
        self.logged_out = False

    async def connect(self):
        pass

    async def disconnect(self):
        self.disconnected = True

    async def log_out(self):
        self.logged_out = True

    async def is_user_authorized(self):
        return self.mode == "already_authorized" or self.mode.startswith("already_authorized_")

    async def get_me(self):
        me = MagicMock()
        if self.mode.endswith("_wrong_phone"):
            me.phone = "12345"
        else:
            me.phone = "66840915772"
        return me

    async def qr_login(self):
        return FakeQRLogin(self.mode)

    async def sign_in(self, password=None):
        if password == "correct_pass":
            pass
        else:
            raise ValueError("Wrong password")

@pytest.fixture
def fake_env(monkeypatch, tmp_path):
    monkeypatch.setenv("SYNC_TG_API_ID_ELIZAVETA", "123")
    monkeypatch.setenv("SYNC_TG_API_HASH_ELIZAVETA", "abc")
    monkeypatch.setenv("SYNC_TG_SESSION_FILE_ELIZAVETA", str(tmp_path / "test.session"))
    
    # Override FILE paths
    url_file = str(tmp_path / "url.txt")
    status_file = str(tmp_path / "status.txt")
    monkeypatch.setattr(tg_qr_login, "URL_FILE", url_file)
    monkeypatch.setattr(tg_qr_login, "STATUS_FILE", status_file)
    return tmp_path, url_file, status_file

@pytest.mark.anyio
async def test_qr_login_already_authorized(fake_env, monkeypatch):
    tmp_path, url_file, status_file = fake_env
    
    with patch("tg_qr_login.TelegramClient", lambda s, i, h: FakeTelegramClient(s, i, h, "already_authorized")):
        await tg_qr_login.main()
        
    with open(status_file, "r") as f:
        assert f.read() == "authorized"
    assert not os.path.exists(url_file)

@pytest.mark.anyio
async def test_qr_login_success(fake_env, monkeypatch):
    tmp_path, url_file, status_file = fake_env
    
    with patch("tg_qr_login.TelegramClient", lambda s, i, h: FakeTelegramClient(s, i, h, "success")):
        # Mock wait_for to just await the coroutine (since we don't actually sleep)
        with patch("asyncio.wait_for", lambda coro, timeout: coro):
            await tg_qr_login.main()
        
    with open(status_file, "r") as f:
        assert f.read() == "authorized"
    assert not os.path.exists(url_file)

@pytest.mark.anyio
async def test_qr_login_timeout_recreate(fake_env, monkeypatch):
    tmp_path, url_file, status_file = fake_env
    
    with patch("tg_qr_login.TelegramClient", lambda s, i, h: FakeTelegramClient(s, i, h, "timeout_then_success")):
        # Mock wait_for to let our fake raise TimeoutError
        async def fake_wait_for(coro, timeout):
            return await coro
        with patch("asyncio.wait_for", fake_wait_for):
            await tg_qr_login.main()
        
    with open(status_file, "r") as f:
        assert f.read() == "authorized"
    assert not os.path.exists(url_file)

@pytest.mark.anyio
async def test_qr_login_2fa(fake_env, monkeypatch):
    tmp_path, url_file, status_file = fake_env
    
    with patch("tg_qr_login.TelegramClient", lambda s, i, h: FakeTelegramClient(s, i, h, "2fa")):
        with patch("asyncio.wait_for", lambda coro, timeout: coro):
            await tg_qr_login.main()
        
    with open(status_file, "r") as f:
        assert f.read() == "2fa_required"
    assert not os.path.exists(url_file)

@pytest.mark.anyio
async def test_qr_login_error(fake_env, monkeypatch):
    tmp_path, url_file, status_file = fake_env
    
    with patch("tg_qr_login.TelegramClient", lambda s, i, h: FakeTelegramClient(s, i, h, "error")):
        with patch("asyncio.wait_for", lambda coro, timeout: coro):
            await tg_qr_login.main()
        
    with open(status_file, "r") as f:
        assert f.read() == "error"
    assert not os.path.exists(url_file)

@pytest.mark.anyio
async def test_qr_login_wrong_account(fake_env, monkeypatch):
    tmp_path, url_file, status_file = fake_env
    monkeypatch.setenv("SYNC_TG_EXPECTED_PHONE_ELIZAVETA", "66840915772")
    
    # Mode success_wrong_phone will cause qr.wait to succeed, then get_me returns wrong phone
    client_instance = FakeTelegramClient(None, None, None, "success_wrong_phone")
    with patch("tg_qr_login.TelegramClient", lambda s, i, h: client_instance):
        with patch("asyncio.wait_for", lambda coro, timeout: coro):
            await tg_qr_login.main()
        
    with open(status_file, "r") as f:
        assert f.read() == "wrong_account"
    assert client_instance.logged_out is True
    assert client_instance.disconnected is True

@pytest.mark.anyio
async def test_qr_login_already_wrong_account(fake_env, monkeypatch):
    tmp_path, url_file, status_file = fake_env
    monkeypatch.setenv("SYNC_TG_EXPECTED_PHONE_ELIZAVETA", "66840915772")
    
    client_instance = FakeTelegramClient(None, None, None, "already_authorized_wrong_phone")
    with patch("tg_qr_login.TelegramClient", lambda s, i, h: client_instance):
        await tg_qr_login.main()
        
    with open(status_file, "r") as f:
        assert f.read() == "wrong_account"
    assert client_instance.logged_out is True
    assert client_instance.disconnected is True

@pytest.mark.anyio
async def test_qr_login_disconnect_on_error(fake_env, monkeypatch):
    tmp_path, url_file, status_file = fake_env
    client_instance = FakeTelegramClient(None, None, None, "error")
    with patch("tg_qr_login.TelegramClient", lambda s, i, h: client_instance):
        await tg_qr_login.main()
    assert client_instance.disconnected is True


@pytest.mark.anyio
async def test_qr_login_2fa_with_password(fake_env, monkeypatch):
    tmp_path, url_file, status_file = fake_env
    monkeypatch.setenv("SYNC_TG_2FA_PASSWORD_ELIZAVETA", "correct_pass")
    
    with patch("tg_qr_login.TelegramClient", lambda s, i, h: FakeTelegramClient(s, i, h, "2fa")):
        await tg_qr_login.main()
        
    with open(status_file, "r") as f:
        assert f.read() == "authorized"
    assert not os.path.exists(url_file)
