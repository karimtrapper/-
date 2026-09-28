"""Изолированный pytest: временная БД, выключенный фон, сеть только loopback.

Настройка выполняется ДО импорта app при collection: fixture для этого поздно.
Никакие DATABASE_URL/ключи из shell и local.db в тестах не используются.
"""
import os
from pathlib import Path
import re
import sys
import tempfile

import pytest
import requests
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
if os.environ.get('CALCCRM_FENCE_ACTIVE') != '1':
    raise RuntimeError('Tests require scripts/run_fenced_pytest.py (pre-import OS/Python network fence)')
sys.path.insert(0, str(ROOT))
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
    'STAND_SBER_MIRROR_ENABLED': '0',
    'STAND_TG_UPDATES_ENABLED': '0',
    'STAND_TRANSFER_POLL_ENABLED': '0',
    'METRIKA_TOKEN': '',
})

@pytest.fixture(autouse=True)
def isolated_runtime(monkeypatch):
    """Не переносим Flask config, лимиты и незакрытую сессию между тестами."""
    import app as module
    before = dict(module.app.config)
    module.limiter.reset()
    monkeypatch.setenv('LOCAL_NO_AUTH', '0')
    # calculator.py подгружает локальный .env уже после начальной очистки.
    # Интеграционные ключи не должны менять поведение изолированных тестов;
    # тесты Etherscan включают свой фиктивный ключ явно.
    monkeypatch.delenv('ETHERSCAN_API_KEY', raising=False)
    # Не читаем локальный service-account даже при заблокированном интернете.
    monkeypatch.setattr(module, 'get_gsheet_client', lambda: None)
    # Business tests create synthetic transfer hashes. A missing transaction is
    # the controlled TronScan response for those hashes; endpoint-specific
    # tests replace requests.get with their own fake transport.
    real_get = requests.get
    real_post = requests.post

    def is_test_telegram(url):
        return urlsplit(url).hostname == 'api.telegram.org'

    def fake_tronscan_get(url, *args, **kwargs):
        if is_test_telegram(url):
            raise requests.ConnectionError('synthetic Telegram transport unavailable')
        if urlsplit(url).hostname == 'apilist.tronscanapi.com':
            response = requests.Response()
            response.status_code = 404
            response._content = b'{}'
            return response
        return real_get(url, *args, **kwargs)

    def fake_telegram_post(url, *args, **kwargs):
        if is_test_telegram(url):
            raise requests.ConnectionError('synthetic Telegram transport unavailable')
        return real_post(url, *args, **kwargs)

    monkeypatch.setattr(requests, 'get', fake_tronscan_get)
    monkeypatch.setattr(requests, 'post', fake_telegram_post)
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
    _database_dir.cleanup()
    # Keep the early fence and disabled pollers active until process exit.
