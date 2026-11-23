"""Калькулятор авто использует тот же точный расчёт, что задача s6."""
import pytest

import app as m


@pytest.fixture
def stand_client(monkeypatch):
    monkeypatch.setattr(m, 'STAND_MODE', True)
    with m.SessionLocal() as db:
        user = m.AdminUser(username='t-auto-calculator', password_hash='unused', role='manager')
        db.add(user)
        db.commit()
        user_id = user.id
    with m.app.test_client() as client:
        with client.session_transaction() as session:
            session['user_id'] = user_id
        yield client
    with m.SessionLocal() as db:
        db.query(m.AdminUser).filter_by(id=user_id).delete()
        db.commit()


@pytest.mark.parametrize('direction,amount,tariff,margin', [
    ('target', 79800, 'soft', 3),
    ('amount', 6928794.86, 'soft', 3),
    ('target', 45000, 'bank', 4.5),
    ('target', 45000, 'bank', 1),
    ('amount', 4000000, 'soft', 1),
])
def test_auto_calculate_matches_task_quote(stand_client, monkeypatch, direction, amount, tariff, margin):
    async def no_rates():
        raise AssertionError('Авто расчёт не должен запрашивать курсы биржи')
    monkeypatch.setattr(m.ExchangeRateProvider, 'get_all_rates', no_rates)
    response = stand_client.post('/api/calculate', json={
        'deal_category': 'property_auto', 'scenario': 'rub-to-usdt',
        'direction': direction, 'amount': amount, 'custom_rub_usdt': 83,
        'tariff': tariff, 'profit_margin': margin,
    })
    assert response.status_code == 200, response.json
    body = response.json
    deal = {'autoPayment': True, 'step': 's6', 'ippsTariff': tariff,
            'autoRequestMode': 'usd' if direction == 'target' else 'rub',
            'requestedUsd': amount if direction == 'target' else None,
            'requestedRub': amount if direction == 'amount' else None,
            'autoMarkupPct': margin, 'rates': {'rubUsdt': '83'}}
    assert m._stand_auto_quote_calculate(deal)
    assert body['rub_paid'] == deal['amountRub']
    assert body['invoice_usd'] == deal['invoiceUsd']
    assert body['direction'] == direction
    assert body['profit_percent'] == margin
    assert body['profit_percent_actual'] == margin
    if direction == 'target' and amount == 79800:
        assert body['rub_paid'] == 6928794.86
        assert body['ipps_send_usdt'] == 81047
    assert 'broker_net_rub' not in body
    assert 'incoming_usdt' not in body
    assert 'outgoing_usdt' not in body
    assert 'profit_usdt' not in body


def test_auto_calculate_matches_old_freehold_quote_at_exact_broker_rate():
    with m.app.test_client() as client:
        response = client.post('/api/calculate', json={
            'deal_category': 'property_auto', 'scenario': 'rub-to-usdt',
            'direction': 'target', 'amount': 79800, 'custom_rub_usdt': 83.498,
            'tariff': 'soft', 'profit_margin': 3,
        })
    assert response.status_code == 200, response.json
    assert response.json['rub_paid'] == 6970367.62
    assert response.json['final_rate'] == pytest.approx(87.347965163)


@pytest.mark.parametrize('override', [
    {'tariff': 'arbitrary'}, {'profit_margin': 0.99}, {'profit_margin': 5.1},
    {'custom_rub_usdt': -83}, {'custom_rub_usdt': '1e-1000'},
    {'amount': 0}, {'amount': 'NaN'},
    {'amount': 100.001}, {'amount': 1e100}, {'scenario': 'rub-to-thb'},
])
def test_auto_calculate_rejects_invalid_parameters(stand_client, override):
    payload = {'deal_category': 'property_auto', 'scenario': 'rub-to-usdt',
               'direction': 'target', 'amount': 79800,
               'custom_rub_usdt': 83, 'tariff': 'soft', 'profit_margin': 3}
    payload.update(override)
    response = stand_client.post('/api/calculate', json=payload)
    assert response.status_code == 400, response.json


def test_auto_calculate_keeps_production_profit_floor(monkeypatch):
    monkeypatch.setattr(m, 'STAND_MODE', False)
    with m.app.test_client() as client:
        response = client.post('/api/calculate', json={
            'deal_category': 'property_auto', 'scenario': 'rub-to-usdt',
            'direction': 'target', 'amount': 45000, 'custom_rub_usdt': 83,
            'tariff': 'bank', 'profit_margin': 1,
        })
    assert response.status_code == 400
