"""
Дедупликация переводов TronScan.

Регресс 04.08: ключом дедупа были сумма + 15-минутное окно, поэтому выплата
500 000 USDT пятью переводами по 100 000 показывалась в дропдауне возмещений
как три — два реальных перевода на $200 000 исчезали молча.

Запуск: cd Dev/CalcCRM && python -m pytest tests/test_tronscan_dedupe.py -v
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ['SECRET_KEY'] = 'test-secret-key-for-pytest'

from app import _dedupe_transfers


def _tx(h, amount, ts):
    return {'tx_hash': h, 'amount_usdt': amount, 'timestamp': ts,
            'from_address': 'TXW2hYJZvikmPQCnvTXGz9PS87yjGZVtXJ',
            'to_address': 'TZG8xz2sSvtge3W0000000000000t9kjpcX'}


# Реальный кейс с прода: 03.08, пять переводов по 100k подряд + 8828
REAL_CASE = [
    _tx('ce10ab832738', 8828, '2026-08-03T15:01:24'),
    _tx('5a1edb979044', 100000, '2026-08-03T14:56:27'),
    _tx('05988fca8277', 100000, '2026-08-03T14:53:00'),
    _tx('43d19347ce5e', 100000, '2026-08-03T14:49:36'),
    _tx('ccc683411df2', 100000, '2026-08-03T14:31:12'),
    _tx('e68c2832dea7', 100000, '2026-08-03T14:15:06'),
]


def test_real_case_keeps_all_five_hundred_k():
    """Главный регресс: 14:56, 14:53 и 14:49 попадали в одно 15-мин окно."""
    out = _dedupe_transfers(REAL_CASE)
    assert len(out) == 6
    assert sum(t['amount_usdt'] for t in out) == 508828


def test_same_amount_same_minute_kept():
    """Два перевода одной суммы в одну минуту — разные переводы, не дубль."""
    out = _dedupe_transfers([
        _tx('aaa', 100000, '2026-08-03T14:56:00'),
        _tx('bbb', 100000, '2026-08-03T14:56:00'),
    ])
    assert len(out) == 2


def test_same_hash_collapsed():
    """Настоящий дубль (стык страниц TronScan / перевод виден с двух кошельков)."""
    out = _dedupe_transfers([
        _tx('aaa', 100000, '2026-08-03T14:56:00'),
        _tx('aaa', 100000, '2026-08-03T14:56:00'),
    ])
    assert len(out) == 1


def test_order_preserved():
    """Порядок (время ↓) не меняется — дропдаун показывает свежие сверху."""
    out = _dedupe_transfers(REAL_CASE)
    assert [t['tx_hash'] for t in out] == [t['tx_hash'] for t in REAL_CASE]


def test_empty_list():
    assert _dedupe_transfers([]) == []


def test_missing_hash_not_dropped():
    """Перевод без хэша не считаем дублем — лучше показать лишнее, чем потерять."""
    out = _dedupe_transfers([
        {'amount_usdt': 100, 'timestamp': '2026-08-03T14:00:00'},
        {'amount_usdt': 100, 'timestamp': '2026-08-03T14:00:00'},
    ])
    assert len(out) == 2
