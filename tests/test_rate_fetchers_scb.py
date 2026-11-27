"""fetch_scb(): Scrapling Fetcher с impersonate=chrome вместо прямого urlopen (403 с серверов Railway)."""
import json
from decimal import Decimal
from types import SimpleNamespace

import pytest

from BankRates import rate_fetchers as rf


def _fake_scrapling(monkeypatch, status, body):
    fetcher = SimpleNamespace(get=lambda *a, **k: SimpleNamespace(status=status, body=body))
    module = SimpleNamespace(Fetcher=fetcher)
    monkeypatch.setitem(__import__('sys').modules, 'scrapling.fetchers', module)


def test_fetch_scb_ok(monkeypatch):
    payload = json.dumps({
        'exchangeRates': [{'curCode': 'USD', 'buyTT': '33.10', 'runDate': '28/10/2026', 'runTime': '09:00:00'}]
    }).encode()
    _fake_scrapling(monkeypatch, 200, payload)
    result = rf.fetch_scb()
    assert result.value == Decimal('33.10')


def test_fetch_scb_403(monkeypatch):
    _fake_scrapling(monkeypatch, 403, b'forbidden')
    with pytest.raises(rf.RateSourceError):
        rf.fetch_scb()
