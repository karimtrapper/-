"""Переводы на свой же monitored-кошелёк не должны пропадать из подбора возмещений.

18.08.2026 с кошелька Виталия ушли два перевода — 305.40 на TKTchh…86t9K и
379.88 на TWyLcj…RGcHb. Оба адреса заведены в CRM как monitored, поэтому
_tronscan_fetch_outgoing выбрасывал их как «внутренние», и в форме возмещения
этих переводов просто не было — при том что рядом лежащий перевод на чужой
адрес (47.11) отображался.

Теперь внутренние помечаются is_internal и скрыты только по умолчанию;
форма возмещений запрашивает их флагом include_internal=1.

Запуск: cd Dev/CalcCRM && python -m pytest tests/test_outgoing_internal_transfers.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('SECRET_KEY', 'test-secret-key-for-pytest')
os.environ['REESTR_SYNC_ENABLED'] = '0'

import pytest

import app as appmod
from app import _tronscan_fetch_outgoing

OURS = 'TKkeEVf2zySaWTLyX2qPwvi6kcdHRuPxkJ'      # кошелёк Виталия
INTERNAL = 'TKTchhXduB6bxD5y7B7Ly6rZdhXx786t9K'  # наш же monitored (#21)
OUTSIDE = 'TGaVecQAdJ5Cagyp7Y2VgQjXfHZ9uX9uXjoP'  # чужой адрес


class _Wallet:
    def __init__(self, address):
        self.address = address


class _Resp:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


@pytest.fixture
def chain(monkeypatch):
    """Три перевода: два наружу, один на свой же кошелёк."""
    transfers = [
        {'transaction_id': 'hash_internal', 'from_address': OURS, 'to_address': INTERNAL,
         'quant': '305400000', 'block_ts': 1755500000000, 'confirmed': True},
        {'transaction_id': 'hash_outside', 'from_address': OURS, 'to_address': OUTSIDE,
         'quant': '47110000', 'block_ts': 1755400000000, 'confirmed': True},
        {'transaction_id': 'hash_incoming', 'from_address': OUTSIDE, 'to_address': OURS,
         'quant': '2265000000', 'block_ts': 1755300000000, 'confirmed': True},
    ]
    monkeypatch.setattr(appmod.requests, 'get',
                        lambda *a, **kw: _Resp({'token_transfers': transfers}))
    monkeypatch.setattr(appmod.time, 'sleep', lambda *a: None)
    return transfers


def _fetch(chain):
    return _tronscan_fetch_outgoing([_Wallet(OURS)], {OURS, INTERNAL}, result_limit=50)


def test_internal_transfer_is_returned(chain):
    """Перевод на свой кошелёк больше не выбрасывается молча."""
    txs = _fetch(chain)
    assert 'hash_internal' in {t['tx_hash'] for t in txs}


def test_internal_transfer_is_flagged(chain):
    """Он помечен is_internal — фронт покажет пометку «на свой кошелёк»."""
    tx = next(t for t in _fetch(chain) if t['tx_hash'] == 'hash_internal')
    assert tx['is_internal'] is True
    assert tx['amount_usdt'] == 305.4


def test_outside_transfer_not_flagged(chain):
    """Перевод наружу остаётся обычным."""
    tx = next(t for t in _fetch(chain) if t['tx_hash'] == 'hash_outside')
    assert tx['is_internal'] is False


def test_incoming_is_not_listed(chain):
    """Входящий перевод в исходящие не попадает."""
    assert 'hash_incoming' not in {t['tx_hash'] for t in _fetch(chain)}
