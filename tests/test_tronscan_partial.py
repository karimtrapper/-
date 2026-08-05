"""
Частичный ответ TronScan не должен обнулять переводы в выборке.

Инцидент 05.08: TronScan отдал 429 по 4 кошелькам из 5, код молча их пропустил
и записал результат в кэш — в дропдауне осталось 4 перевода вместо 35, причём
без единого признака, что данные неполные. Оператор ищет свой приход, не находит
и думает, что перевода не было.

Запуск: cd Dev/CalcCRM && python -m pytest tests/test_tronscan_partial.py -v
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ['SECRET_KEY'] = 'test-secret-key-for-pytest'

import app as A
from app import _merge_partial_with_cache, TRONSCAN_CACHE

W1 = 'TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn'
W2 = 'TXW2hYJZvikmPQCnvTXGz9PS87yjGZVtXJ'


def tx(h, addr, ts, field='to_address'):
    return {'tx_hash': h, field: addr, 'timestamp': ts, 'amount_usdt': 100}


def setup_function():
    TRONSCAN_CACHE['incoming'] = {'data': [], 'timestamp': 0}
    TRONSCAN_CACHE['outgoing'] = {'data': [], 'timestamp': 0}


def test_failed_wallet_rescued_from_cache():
    """Кошелёк ответил 429 — его переводы берём из прошлого кэша."""
    TRONSCAN_CACHE['incoming'] = {
        'data': [tx('old1', W2, '2026-08-03T10:00:00'),
                 tx('old2', W2, '2026-08-03T11:00:00')],
        'timestamp': 1}
    fresh = [tx('new1', W1, '2026-08-05T10:00:00')]
    merged = _merge_partial_with_cache(fresh, 'incoming', {W2}, 'to_address')
    hashes = {t['tx_hash'] for t in merged}
    assert hashes == {'new1', 'old1', 'old2'}


def test_no_failures_returns_fresh_unchanged():
    TRONSCAN_CACHE['incoming'] = {'data': [tx('old1', W2, '2026-08-03T10:00:00')], 'timestamp': 1}
    fresh = [tx('new1', W1, '2026-08-05T10:00:00')]
    assert _merge_partial_with_cache(fresh, 'incoming', set(), 'to_address') == fresh


def test_only_failed_wallets_rescued():
    """Кошелёк ответил нормально и переводов не дал — старые не воскрешаем."""
    TRONSCAN_CACHE['incoming'] = {
        'data': [tx('old1', W1, '2026-08-03T10:00:00'),
                 tx('old2', W2, '2026-08-03T11:00:00')],
        'timestamp': 1}
    merged = _merge_partial_with_cache([], 'incoming', {W2}, 'to_address')
    assert {t['tx_hash'] for t in merged} == {'old2'}


def test_no_duplicates_when_cache_overlaps():
    TRONSCAN_CACHE['incoming'] = {'data': [tx('same', W2, '2026-08-03T10:00:00')], 'timestamp': 1}
    merged = _merge_partial_with_cache([tx('same', W2, '2026-08-03T10:00:00')],
                                       'incoming', {W2}, 'to_address')
    assert len(merged) == 1


def test_sorted_newest_first():
    TRONSCAN_CACHE['incoming'] = {'data': [tx('old', W2, '2026-08-01T10:00:00')], 'timestamp': 1}
    merged = _merge_partial_with_cache([tx('new', W1, '2026-08-05T10:00:00')],
                                       'incoming', {W2}, 'to_address')
    assert [t['tx_hash'] for t in merged] == ['new', 'old']


def test_outgoing_uses_from_address():
    TRONSCAN_CACHE['outgoing'] = {'data': [tx('o1', W2, '2026-08-03T10:00:00', 'from_address')],
                                  'timestamp': 1}
    merged = _merge_partial_with_cache([], 'outgoing', {W2}, 'from_address')
    assert {t['tx_hash'] for t in merged} == {'o1'}


def test_empty_cache_does_not_crash():
    assert _merge_partial_with_cache([], 'incoming', {W2}, 'to_address') == []


def test_outgoing_fetch_reports_failures(monkeypatch):
    """Сбор исходящих сообщает, какие кошельки не ответили."""
    class Resp:
        status_code = 429
        def json(self): return {}
    monkeypatch.setattr(A.requests, 'get', lambda *a, **k: Resp())
    monkeypatch.setattr(A.time, 'sleep', lambda *_: None)

    class W:
        def __init__(self, a): self.address = a
    out, failed = A._tronscan_fetch_outgoing([W(W1), W(W2)], set(), with_errors=True)
    assert out == []
    assert set(failed) == {W1, W2}, 'оба кошелька должны попасть в список ошибок'


def test_outgoing_fetch_backward_compatible(monkeypatch):
    """Без with_errors сигнатура прежняя — фоновый прогрев не ломается."""
    class Resp:
        status_code = 429
        def json(self): return {}
    monkeypatch.setattr(A.requests, 'get', lambda *a, **k: Resp())
    monkeypatch.setattr(A.time, 'sleep', lambda *_: None)

    class W:
        def __init__(self, a): self.address = a
    assert A._tronscan_fetch_outgoing([W(W1)], set()) == []
