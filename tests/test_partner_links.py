"""Курс партнёрских ссылок и доступ к ним.

Стакан и Rapira подставляем фиксированные — тесты не ходят в сеть.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import partner_rates as pr

# Стакан с достаточной глубиной: 33.00 на 5000 USDT, дальше хуже.
BIDS = [(33.00, 5000.0), (32.90, 5000.0), (32.80, 20000.0)]
ASK = 85.0


def q(**kw):
    kw.setdefault('ask', ASK)
    kw.setdefault('bids', BIDS)
    return pr.quote(**kw)


def test_naценка_партнёра_поднимает_цену_клиенту():
    """Наценка партнёра идёт СВЕРХУ нашей — платит её клиент, а не мы."""
    base = q(thb_amount=35000, partner_markup=0)
    with_markup = q(thb_amount=35000, partner_markup=1)
    assert with_markup['amount_rub'] > base['amount_rub']
    assert with_markup['amount_thb'] == base['amount_thb']   # баты клиенту те же
    assert with_markup['our_usdt'] == pytest.approx(base['our_usdt'], abs=0.01)  # наш заработок не тронут
    assert with_markup['partner_usdt'] > base['partner_usdt']


def test_revshare_делится_из_нашей_прибыли():
    """Revshare клиента не касается: цена та же, наш заработок падает на долю партнёра."""
    base = q(thb_amount=35000, partner_revshare=0)
    with_rev = q(thb_amount=35000, partner_revshare=30)
    assert with_rev['amount_rub'] == pytest.approx(base['amount_rub'], abs=0.01)
    assert with_rev['partner_usdt'] == pytest.approx(base['our_usdt'] * 0.3, rel=1e-6)
    assert with_rev['our_usdt'] == pytest.approx(base['our_usdt'] * 0.7, rel=1e-6)


def test_комбинация_наценка_плюс_revshare():
    """Каскад: партнёр снимает наценку с верха, потом процент от ОСТАВШЕЙСЯ нашей прибыли."""
    r = q(thb_amount=35000, base_markup=3.5, partner_markup=1, partner_revshare=30)
    assert r['partner_usdt'] == pytest.approx(r['partner_markup_usdt'] + r['partner_revshare_usdt'], abs=0.01)
    # revshare считается от базы (3.5%), а не от всей прибыли (4.5%)
    assert r['partner_revshare_usdt'] == pytest.approx(r['usdt'] * 0.035 * 0.3, abs=0.01)
    assert r['our_usdt'] + r['partner_usdt'] == pytest.approx(r['total_profit_usdt'], abs=0.01)


def test_прибыль_сходится_с_разложением():
    r = q(thb_amount=50000, base_markup=3.5, partner_markup=1.5, partner_revshare=20)
    assert r['total_profit_usdt'] == pytest.approx(
        r['our_usdt'] + r['partner_usdt'], abs=0.01)


def test_round_trip_рубли_баты():
    """Ввод в ₽ и в ฿ на одной сделке даёт согласованную пару."""
    a = q(thb_amount=35000, partner_revshare=30)
    b = q(rub_amount=a['amount_rub'], partner_revshare=30)
    assert b['amount_thb'] == pytest.approx(35000, rel=1e-4)


def test_vwap_учитывает_глубину():
    """Крупный объём выгребает верхние уровни — курс хуже, чем по топ-биду."""
    small = q(thb_amount=10000)
    large = q(thb_amount=300000)
    assert large['usdt_thb_vwap'] < small['usdt_thb_vwap']


def test_стакан_не_покрыл_объём():
    with pytest.raises(pr.RateError):
        q(thb_amount=50_000_000)


def test_нужна_ровно_одна_сумма():
    with pytest.raises(pr.RateError):
        q(thb_amount=1000, rub_amount=1000)
    with pytest.raises(pr.RateError):
        q()


def test_фикс_20_бат_вычитается():
    """Клиент получает ровно запрошенное, фикс сидит в объёме USDT, который мы продаём."""
    r = q(thb_amount=35000, base_markup=0)
    # без наценки прибыль нулевая, а USDT покрывает баты + 20 ฿ + комиссию биржи
    assert r['total_profit_usdt'] == pytest.approx(0, abs=0.01)
    assert r['usdt'] * r['usdt_thb_nett'] == pytest.approx(35020, rel=1e-4)


def test_наценка_по_умолчанию_из_env():
    """base_markup=None → глобальная наценка, не ноль."""
    r = q(thb_amount=35000, base_markup=None)
    assert r['base_markup_percent'] == pytest.approx(pr.DEFAULT_BASE_MARKUP)
    assert r['total_profit_usdt'] > 0
