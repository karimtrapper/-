"""Synthetic market parity for the public rate card and calculator endpoints."""

import pytest

import app as appmod
import stand_egress


BOOK = [
    [0, 0, 0, 0, 0, 0, 33.0, 0, 500.0, 0],
    [0, 0, 0, 0, 0, 0, 32.0, 0, 1000.0, 0],
    [0, 0, 0, 0, 0, 0, 31.0, 0, 1000.0, 0],
    [0, 0, 0, 0, 0, 0, 34.0, 0, 9999.0, 1],  # ask is never liquidity for sales
]


@pytest.fixture
def market(monkeypatch):
    """Both modes receive the same quotes and orderbook without market I/O."""
    appmod.app.config['TESTING'] = True
    db = appmod.get_session()
    user = appmod.AdminUser(username='t21-market-parity', password_hash='unused', role='admin')
    db.add(user)
    db.commit()
    user_id = user.id
    db.close()

    state = {'book': BOOK, 'usdt_thb': 32.5, 'rub_usdt': 80.0, 'calls': []}

    async def rates():
        return {'usdt_thb': state['usdt_thb'], 'rub_usdt': state['rub_usdt']}

    def read_get(op, params=None, _base_url=None):
        state['calls'].append(('stand', op, params, _base_url))
        assert op == 'market_bitazza'
        assert params == {'OMSId': 1, 'InstrumentId': 5, 'Depth': 400}
        assert _base_url is None
        return (200, state['book'], None) if state['book'] is not None else (None, None, 'network_error')

    class Response:
        def json(self):
            return state['book']

    def prod_get(url, **kwargs):
        state['calls'].append(('prod', url, kwargs))
        assert url == appmod.BITAZZA_L2_URL
        assert kwargs == {'timeout': 6, 'params': {'OMSId': 1, 'InstrumentId': 5, 'Depth': 400}}
        if state['book'] is None:
            raise OSError('synthetic unavailable')
        return Response()

    monkeypatch.setattr(appmod.ExchangeRateProvider, 'get_all_rates', rates)
    monkeypatch.setattr(stand_egress, 'read_get', read_get)
    monkeypatch.setattr(appmod.requests, 'get', prod_get)

    def call(mode, path, payload=None):
        monkeypatch.setattr(appmod, 'STAND_MODE', mode == 'stand')
        appmod._BITAZZA_CACHE.update(bids=None, ts=0.0)
        with appmod.app.test_client() as client:
            if mode == 'stand':
                with client.session_transaction() as session:
                    session['user_id'] = user_id
            response = client.get(path) if payload is None else client.post(path, json=payload)
            return response.status_code, response.get_json()

    yield state, call
    appmod._BITAZZA_CACHE.update(bids=None, ts=0.0)
    db = appmod.get_session()
    db.query(appmod.AdminUser).filter_by(id=user_id).delete()
    db.commit()
    db.close()


def test_rates_same_bitazza_card_from_same_book(market):
    state, call = market
    prod_status, prod = call('prod', '/api/rates')
    stand_status, stand = call('stand', '/api/rates')
    assert prod_status == stand_status == 200
    shared = ('usdt_thb', 'rub_usdt', 'bitazza_usdt_thb', 'bitazza_raw',
              'bitazza_fee_percent', 'bitazza_fee_fixed_thb', 'success', 'errors')
    assert {key: stand[key] for key in shared} == {key: prod[key] for key in shared}
    assert stand['bitazza_raw'] == 32.5  # 500 @ 33 plus 500 @ 32
    assert stand['bitazza_usdt_thb'] == round(32.5 * (1 - 0.0015), 4)
    assert stand['bitazza_fee_percent'] == 0.15
    assert stand['bitazza_fee_fixed_thb'] == 20
    assert state['calls'][1] == ('stand', 'market_bitazza',
                                  {'OMSId': 1, 'InstrumentId': 5, 'Depth': 400}, None)


@pytest.mark.parametrize('payload,expected_source,expected_rate,expected_pct', [
    ({'scenario': 'rub-to-thb', 'amount': 80_000}, 'bitazza', 32.5, 0.15),
    ({'scenario': 'rub-to-thb', 'amount': 160_000}, 'bitazza', 32.0, 0.15),
    ({'scenario': 'rub-to-thb', 'direction': 'target', 'amount': 32_500}, 'bitazza', 32.5, 0.15),
    ({'scenario': 'usdt-to-thb', 'amount': 1_000}, 'bitazza', 32.5, 0.15),
    ({'scenario': 'thb-to-usdt', 'amount': 32_500}, 'bitazza', 32.5, 0.15),
    ({'scenario': 'rub-to-usdt', 'amount': 80_000}, 'bitazza', None, 0.15),
    ({'scenario': 'usdt-to-thb', 'amount': 3_000}, 'binance', 32.5, 0.25),
    ({'scenario': 'usdt-to-thb', 'amount': 1_000, 'rate_source': 'binance'}, 'binance', 32.5, 0.25),
    ({'scenario': 'usdt-to-thb', 'amount': 1_000, 'rate_source': 'custom',
      'custom_usdt_thb': 34.2}, 'custom', 34.2, 0.25),
    ({'scenario': 'rub-to-thb', 'amount': 80_000, 'method': 'broker'}, 'bitazza', 32.5, 0.15),
])
def test_calculate_same_money_fee_and_source(market, payload, expected_source, expected_rate, expected_pct):
    _, call = market
    payload = {'direction': 'amount', 'profit_margin': 4.0,
               'rate_source': 'bitazza', **payload}
    prod_status, prod = call('prod', '/api/calculate', payload)
    stand_status, stand = call('stand', '/api/calculate', payload)
    assert prod_status == stand_status == 200
    assert stand == prod  # includes pre-rounding fees, monetary result and source fields
    assert stand['rate_source'] == expected_source
    assert stand['withdrawal_percent_rate'] == expected_pct
    if expected_rate is not None:
        assert stand['usdt_thb_rate'] == expected_rate
    if payload['scenario'] in ('rub-to-thb', 'usdt-to-thb'):
        assert stand['withdrawal_fixed'] == 20
    assert stand['final_rate'] > 0


def test_bitazza_unavailable_fallback_and_all_sources_unavailable(market):
    state, call = market
    state['book'] = None
    for mode in ('prod', 'stand'):
        status, rates = call(mode, '/api/rates')
        assert status == 200
        assert rates['bitazza_usdt_thb'] is None
        assert rates['bitazza_raw'] is None
        assert rates['success'] is True  # Binance and RUB/USDT remain available
        status, calc = call(mode, '/api/calculate', {
            'scenario': 'usdt-to-thb', 'amount': 1_000, 'rate_source': 'bitazza'})
        assert status == 200
        assert calc['rate_source'] == 'binance'
        assert calc['withdrawal_percent_rate'] == 0.25

    state['usdt_thb'] = None
    state['rub_usdt'] = None
    for mode in ('prod', 'stand'):
        status, rates = call(mode, '/api/rates')
        assert status == 200
        assert rates['success'] is False
        assert rates['usdt_thb'] is None and rates['rub_usdt'] is None
        assert rates['bitazza_usdt_thb'] is None
        status, calc = call(mode, '/api/calculate', {
            'scenario': 'rub-to-thb', 'amount': 80_000, 'rate_source': 'bitazza'})
        assert status == 503
        assert 'недоступен' in calc['error']


def test_shallow_book_has_no_nominal_bitazza_quote(market):
    state, call = market
    state['book'] = BOOK[:1]  # 500 USDT cannot cover the 1000 USDT rate card
    for mode in ('prod', 'stand'):
        status, rates = call(mode, '/api/rates')
        assert status == 200
        assert rates['success'] is True
        assert rates['bitazza_usdt_thb'] is None
        assert rates['bitazza_raw'] is None
        status, result = call(mode, '/api/calculate', {
            'scenario': 'usdt-to-thb', 'amount': 1_000, 'rate_source': 'bitazza'})
        assert status == 200
        assert result['rate_source'] == 'binance'
        assert result['withdrawal_percent_rate'] == 0.25


def test_bitazza_only_keeps_main_partial_success_contract(market):
    state, call = market
    state['usdt_thb'] = None
    for mode in ('prod', 'stand'):
        status, rates = call(mode, '/api/rates')
        assert status == 200
        assert rates['success'] is False  # main requires both base rates
        assert rates['bitazza_usdt_thb'] == round(32.5 * (1 - 0.0015), 4)
        status, result = call(mode, '/api/calculate', {
            'scenario': 'usdt-to-thb', 'amount': 1_000, 'rate_source': 'bitazza'})
        assert status == 200
        assert result['rate_source'] == 'bitazza'
        assert result['withdrawal_percent_rate'] == 0.15
