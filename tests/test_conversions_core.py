"""Расчётное ядро конвертаций без поднятия приложения.

Формулы теперь живут в conversions_core.py — их можно проверять напрямую,
не поднимая Flask и не трогая БД. Раньше эти же проверки требовали клиента,
фикстур и очистки за собой.

Запуск: cd Dev/CalcCRM && python -m pytest tests/test_conversions_core.py -v
"""
import os
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from conversions_core import conversion_shares, match_wl_deal, parse_sent_at


def test_доли_воспроизводят_кейс_11_08():
    """1 732,8791 USDT на три поступления — эталон из ручной правки через API."""
    shares = conversion_shares(
        [(1, 27786.44), (2, 35000.0), (3, 83000.0)], 1732.8791)
    assert shares[1] == 330.28
    assert shares[2] == 416.02
    # Наибольшая доля добирает хвост округления, сумма сходится ровно
    assert shares[3] == 986.5791
    assert sum(shares.values()) == 1732.8791


def test_доли_на_краях():
    assert conversion_shares([], 100) == {}
    assert conversion_shares([(1, 0.0)], 100) == {1: 0.0}
    assert conversion_shares([(1, 50.0)], 0) == {1: 0.0}


def test_матчинг_wl_только_однозначный():
    wl = [{'wl': 'WL-0393', 'dt': '17.08 14:20', 'rub': 112600},
          {'wl': 'WL-0392', 'dt': '10.08 09:00', 'rub': 27786.44}]
    inc = {'operation_date': '2026-08-17T12:00:00', 'gross_rub': 112600.0}
    assert match_wl_deal(inc, wl)['wl'] == 'WL-0393'
    # Две сделки на одну сумму в один день — не гадаем
    dup = [{'wl': 'A', 'dt': '17.08 10:00', 'rub': 35000},
           {'wl': 'B', 'dt': '17.08 18:00', 'rub': 35000}]
    assert match_wl_deal({'operation_date': '2026-08-17', 'gross_rub': 35000.0}, dup) is None
    # Битые данные не роняют
    assert match_wl_deal({'operation_date': 'не дата', 'gross_rub': 100}, wl) is None
    assert match_wl_deal({'gross_rub': 0}, wl) is None


def test_дата_отправки():
    assert parse_sent_at('2026-08-17') == datetime(2026, 8, 17)
    assert parse_sent_at(None) is None
    assert parse_sent_at('2026-08-17T23:45:00+03:00') == datetime(2026, 8, 17)
    before = datetime.utcnow()
    assert before <= parse_sent_at(True) <= datetime.utcnow()
    assert parse_sent_at(False) is None
    assert parse_sent_at('') is None


@pytest.mark.parametrize('value', ['мусор', '2026-02-30', '2026-08-17garbage',
                                   '2026-08-17T99:99:99', 1, 0, [], {}])
def test_неверная_дата_не_подменяется_сегодняшней(value):
    with pytest.raises(ValueError):
        parse_sent_at(value)
