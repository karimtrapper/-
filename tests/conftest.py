"""Изолированный pytest: временная БД, выключенный фон, сеть только loopback.

Настройка выполняется ДО импорта app при collection: fixture для этого поздно.
Никакие DATABASE_URL/ключи из shell и local.db в тестах не используются.
"""
import os
from pathlib import Path
import re
import socket
import sys
import tempfile
from urllib.parse import urlsplit

import pytest
import requests


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_environment_before = dict(os.environ)
for source in ROOT.glob('*.py'):
    for key in re.findall(r"os\.(?:environ\.get|getenv)\(['\"]([A-Z][A-Z0-9_]*)", source.read_text()):
        os.environ.pop(key, None)
_database_dir = tempfile.TemporaryDirectory(prefix='calccrm-pytest-')
os.environ.update({
    'DATABASE_URL': f'sqlite:///{_database_dir.name}/test.db',
    'SECRET_KEY': 'test-secret-key-for-pytest',
    'LOCAL_NO_AUTH': '0',
    'REESTR_SYNC_ENABLED': '0',
    'PAYIN_ADDR_BACKFILL': '0',
    'TRONSCAN_WARM_ENABLED': '0',
    'PAYMENT_POLL_ENABLED': '0',
    'KYC_RETENTION_ENABLED': '0',
    'METRIKA_TOKEN': '',
})

_original_connect = socket.socket.connect
_original_connect_ex = socket.socket.connect_ex


def _check_address(address):
    """Разрешаем только локальный HTTP-стенд и IPC Playwright."""
    if isinstance(address, tuple) and address[0] not in ('127.0.0.1', '::1', 'localhost'):
        raise RuntimeError('Внешняя сеть запрещена в pytest; замокайте интеграцию')


def _local_connect(sock, address):
    _check_address(address)
    return _original_connect(sock, address)


def _local_connect_ex(sock, address):
    _check_address(address)
    return _original_connect_ex(sock, address)


socket.socket.connect = _local_connect
socket.socket.connect_ex = _local_connect_ex


@pytest.fixture(autouse=True)
def isolated_runtime(monkeypatch):
    """Не переносим Flask config, лимиты и незакрытую сессию между тестами."""
    import app as module
    before = dict(module.app.config)
    module.limiter.reset()
    monkeypatch.setenv('LOCAL_NO_AUTH', '0')
    # Не читаем локальный service-account даже при заблокированном интернете.
    monkeypatch.setattr(module, 'get_gsheet_client', lambda: None)
    original_request = requests.sessions.Session.request

    def local_request(session, method, url, *args, **kwargs):
        if urlsplit(url).hostname not in ('127.0.0.1', '::1', 'localhost'):
            raise requests.ConnectionError('Внешний HTTP запрещён в pytest: требуется mock')
        return original_request(session, method, url, *args, **kwargs)

    monkeypatch.setattr(requests.sessions.Session, 'request', local_request)
    yield
    module.Session.remove()
    module.app.config.clear()
    module.app.config.update(before)


def pytest_addoption(parser):
    parser.addoption('--browser', action='store_true', help='Запустить Chromium UI-тесты')


def pytest_collection_modifyitems(config, items):
    if not config.getoption('--browser'):
        skip = pytest.mark.skip(reason='UI: включите --browser (требуется Chromium)')
        for item in items:
            if item.get_closest_marker('browser'):
                item.add_marker(skip)


def pytest_unconfigure(config):
    module = sys.modules.get('app')
    if module is not None:
        module.Session.remove()
        module.engine.dispose()
    socket.socket.connect = _original_connect
    socket.socket.connect_ex = _original_connect_ex
    _database_dir.cleanup()
    os.environ.clear()
    os.environ.update(_environment_before)
