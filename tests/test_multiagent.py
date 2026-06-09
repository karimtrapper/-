"""
Тесты мультиагентного каскада CalcCRM (compute_agent_cascade).
Покрывает: каскад по уровням, «в долю» (один tier), 3 модели (revshare/markup/fixed),
реальный кейс сделки 364, граничные случаи.

Запуск: cd Dev/CalcCRM && python -m pytest tests/test_multiagent.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ['SECRET_KEY'] = 'test-secret-key-for-pytest'

from app import compute_agent_cascade


def _agents(*specs):
    """specs: (tier, model, value) → list[dict]. value = percent или fixed$."""
    out = []
    for tier, model, val in specs:
        a = {'tier': tier, 'comp_model': model}
        if model == 'fixed':
            a['fixed_usdt'] = val
        else:
            a['percent'] = val
        out.append(a)
    return out


def test_single_agent_revshare():
    """Один агент revshare = как старая система: 50% от прибыли."""
    res, net = compute_agent_cascade(2793.15, 58409, _agents((1, 'revshare', 50)))
    assert res[0]['_payout'] == 1396.58  # round(2793.15*0.5, 2)
    assert net == 1396.57


def test_cascade_two_levels():
    """Каскад: ур.1 20% от прибыли, ур.2 50% от остатка (реальный кейс 364)."""
    res, net = compute_agent_cascade(2793.15, 58409, _agents(
        (1, 'revshare', 20),
        (2, 'revshare', 50),
    ))
    a1, a2 = res
    assert a1['_payout'] == 558.63          # 20% × 2793.15
    assert a1['_base'] == 2793.15
    assert a2['_base'] == 2234.52           # остаток после ур.1
    assert a2['_payout'] == 1117.26         # 50% × 2234.52
    assert net == 1117.26


def test_flat_same_tier_differs_from_cascade():
    """«В долю» (оба ур.1) ≠ каскад: оба берут от ПОЛНОЙ прибыли."""
    res, net = compute_agent_cascade(2793.15, 58409, _agents(
        (1, 'revshare', 20),
        (1, 'revshare', 50),
    ))
    a1, a2 = res
    assert a1['_payout'] == 558.63          # 20% × 2793.15
    assert a2['_payout'] == 1396.58         # 50% × 2793.15 (а не от остатка!)
    assert a2['_base'] == 2793.15
    assert net == 837.94                    # 2793.15 − 558.63 − 1396.58


def test_three_levels():
    """Три уровня каскадом."""
    res, net = compute_agent_cascade(2793.15, 58409, _agents(
        (1, 'revshare', 20),
        (2, 'revshare', 50),
        (3, 'revshare', 10),
    ))
    assert res[0]['_payout'] == 558.63
    assert res[1]['_payout'] == 1117.26
    assert res[2]['_payout'] == 111.73      # 10% × 1117.26
    assert net == 1005.53


def test_markup_uses_volume():
    """markup считается от ОБЪЁМА, не от прибыли."""
    res, net = compute_agent_cascade(2793.15, 50000, _agents((1, 'markup', 2)))
    assert res[0]['_payout'] == 1000.0      # 2% × 50000
    assert net == 1793.15                   # прибыль − выплата


def test_fixed_amount():
    """fixed — фиксированная сумма $, независимо от прибыли/объёма."""
    res, net = compute_agent_cascade(2793.15, 50000, _agents((1, 'fixed', 300)))
    assert res[0]['_payout'] == 300.0
    assert net == 2493.15


def test_mixed_models_cascade():
    """Смешанный каскад: markup ур.1 (от объёма) → revshare ур.2 (от остатка)."""
    res, net = compute_agent_cascade(3000, 50000, _agents(
        (1, 'markup', 2),       # 1000 от объёма
        (2, 'revshare', 50),    # 50% от (3000−1000)=2000 → 1000
    ))
    assert res[0]['_payout'] == 1000.0
    assert res[1]['_base'] == 2000.0
    assert res[1]['_payout'] == 1000.0
    assert net == 1000.0


def test_no_agents():
    """Без агентов: вся прибыль остаётся нам."""
    res, net = compute_agent_cascade(2793.15, 58409, [])
    assert res == []
    assert net == 2793.15


def test_zero_profit():
    """Нулевая прибыль — выплаты revshare нулевые, fixed/markup всё равно платятся."""
    res, net = compute_agent_cascade(0, 50000, _agents(
        (1, 'revshare', 50),
        (1, 'markup', 1),
    ))
    payouts = {a['comp_model']: a['_payout'] for a in res}
    assert payouts['revshare'] == 0.0
    assert payouts['markup'] == 500.0       # 1% × 50000 (от объёма, не зависит от прибыли)
    assert net == -500.0                    # ушли в минус — markup съел больше чем прибыль
