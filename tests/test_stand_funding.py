"""Regression for RUB batch source admission and exact USDT coverage."""

import copy

import pytest

from stand_funding import check_batch, check_state


def board():
    incomes = [{'id': 1, 'rub': 931000, 'dealId': 10, 'demo': True},
               {'id': 2, 'rub': 100000, 'dealId': 11, 'demo': True}]
    deals = []
    for did, rub, route, amount, inc_id in ((10, 931000, 'coins', 11330.13, 1),
                                             (11, 100000, 'refund', 1185.90, 2)):
        deals.append({'id': did, 'cnvId': 1, 'amountRub': rub, 'incomeAmount': rub,
                      'payinParts': [{'incId': inc_id, 'amountRub': rub}],
                      'postConv': route, 'step': 's22',
                      'transfer': {'amount': amount, 'walletId': 'founder' if route == 'refund' else None}})
    return {'incomes': incomes, 'deals': deals,
            'convs': [{'id': 1, 'walletId': 'grusha',
                       'sources': [{'dealId': 10, 'rub': 931000}, {'dealId': 11, 'rub': 100000}],
                       'txs': [{'hash': 'a' * 64, 'net': 'TRC-20', 'status': 'confirmed',
                                'amount': 12627.36}]}]}


def test_qa_zero_rub_source_and_rounded_dust_cannot_enter_batch():
    old = board()
    new = copy.deepcopy(old)
    new['deals'].append({'id': 12, 'cnvId': 1, 'amountRub': None, 'incomeAmount': None,
                         'payinParts': [], 'postConv': 'coins', 'step': 'ready',
                         'transfer': {'amount': 3205.13}})
    new['convs'][0]['sources'].append({'dealId': 12, 'rub': 0, 'usdtFact': 0.02})
    assert 'положительный' in check_batch(new, new['convs'][0])
    assert check_state(old, new)


def test_positive_rub_without_registered_payin_is_rejected():
    state = board()
    state['deals'][1]['payinParts'] = []
    assert check_batch(state, state['convs'][0])
    state = board()
    state['convs'][0]['sources'][1]['rub'] = 200000
    assert check_batch(state, state['convs'][0])


def test_exact_funding_boundary_and_mixed_coins_refund():
    state = board()
    conv = state['convs'][0]
    state['deals'][1]['transfer']['amount'] = 1297.23
    assert check_batch(state, conv, dispatch=True) is None
    state['deals'][1]['transfer']['amount'] = 1297.24
    assert 'не хватает 0.01' in check_batch(state, conv, dispatch=True)
    state['deals'][1]['postConv'] = 'keep'
    assert check_batch(state, conv, dispatch=True) is None
    state['deals'][1]['postConv'] = 'ipps'
    assert check_batch(state, conv, dispatch=True) is None
    state['deals'][1]['transfer']['back'] = True
    assert check_batch(state, conv, dispatch=True)
    state['deals'][1]['postConv'] = 'refund'
    state['deals'][1]['transfer']['walletId'] = 'grusha'
    assert check_batch(state, conv, dispatch=True) is None


@pytest.mark.parametrize('bad', [-1, 0, None, 'NaN', 'Infinity', '12.345',
                                 '1e4', True, '9' * 1000, 'abc'])
def test_bad_send_amount_rejected(bad):
    state = board()
    state['deals'][0]['transfer']['amount'] = bad
    assert check_batch(state, state['convs'][0], dispatch=True)


def test_partial_incoming_and_duplicate_reuse_rejected():
    state = board()
    state['convs'][0]['txs'][0]['amount'] = '12516.02'
    assert check_batch(state, state['convs'][0], dispatch=True)
    state = board()
    state['convs'][0]['sources'].append(copy.deepcopy(state['convs'][0]['sources'][0]))
    assert check_batch(state, state['convs'][0])
    state = board()
    state['convs'][0]['txs'].append(copy.deepcopy(state['convs'][0]['txs'][0]))
    assert check_batch(state, state['convs'][0], dispatch=True)
    state = board()
    second = copy.deepcopy(state['convs'][0]); second['id'] = 2
    state['convs'].append(second)
    assert check_state(board(), state)


def test_two_registered_sends_cannot_exceed_assignment_and_failed_retry_is_free():
    state = board()
    sends = state['deals'][0]['transfer']['sends'] = [
        {'amount': '6000.00', 'status': 'pending'},
        {'amount': '5330.14', 'status': 'pending'}]
    assert check_batch(state, state['convs'][0], dispatch=True)
    sends[1]['amount'] = '5330.13'
    assert check_batch(state, state['convs'][0], dispatch=True) is None
    sends[0]['status'] = 'failed'
    sends.append({'amount': '6000.00', 'status': 'pending'})
    assert check_batch(state, state['convs'][0], dispatch=True) is None
    state['deals'][0]['postConv'] = 'keep'
    assert check_batch(state, state['convs'][0], dispatch=True)


def test_new_batch_requires_income_from_previous_server_state():
    state = board()
    before = copy.deepcopy(state)
    before['convs'] = []
    before['incomes'] = []
    assert 'до создания' in check_state(before, state)


def test_confirmed_incoming_distribution_cannot_be_forged():
    state = board()
    conv = state['convs'][0]
    conv['sources'][0]['usdtFact'] = '11402.59'
    conv['sources'][1]['usdtFact'] = '1224.77'
    assert check_batch(state, conv) is None
    conv['sources'][1]['usdtFact'] = '1224.78'
    assert check_batch(state, conv)


def test_unassigned_bank_receipt_conversion_is_not_a_deal_funding_batch():
    state = {'deals': [], 'incomes': [{'id': 5, 'rub': 1000, 'source': 'sber'}],
             'convs': [{'id': 5, 'sources': [{'incomeId': 5, 'dealId': None,
                                             'rub': 1000}], 'txs': []}]}
    assert check_state({'deals': [], 'incomes': state['incomes'], 'convs': []}, state) is None
