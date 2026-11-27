"""Regression checks for IPPS amount rounding and transfer timing."""
import copy
import pytest
from tests.test_stand_prepay import api, board, seed, put, IPPS

@pytest.mark.usefixtures('stand_demo_environment')
@pytest.mark.parametrize('amount,status', [(1005.11, 200), (1005.12, 200), (1005.13, 409)])
def test_soft_tariff_rounds_half_up_and_allows_discount(api, amount, status):
    state = board(step='s18w')
    d = state['deals'][0]
    d.update(invoiceUsd=941, ippsTariff='soft')
    d['payTo']['amount'] = 941
    d['payTo']['pobo'] = 'Synthetic beneficiary'
    seed(state)
    response = api[0].post('/api/stand/prepay', json={
        'action': 'start', 'dealId': 1484, 'walletId': 'teodor', 'version': 1})
    assert response.status_code == 200, response.json
    saved = response.json
    d = saved['data']['deals'][0]
    assert d['prepay']['amount'] == 1005.12
    d['payToConfirm'] = {'payTo': copy.deepcopy(d['payTo']), 'at': 'confirmed'}
    d['reqTask'] = 'done'
    saved = put(api, saved, 'manager')
    d = saved['data']['deals'][0]
    d.update(step='s23', _ippsPayoutInstruction=True,
             transfer={'amount': amount, 'to': 'IPPS', 'addr': IPPS,
                       'net': 'TRC-20', 'sends': []})
    api[1][0] = 'operator'
    response = api[0].put('/api/stand/state', json={
        'version': saved['version'], 'data': saved['data']})
    assert response.status_code == status, response.json
    if status == 200:
        assert response.json['data']['deals'][0]['ippsPayoutOrder']['amount'] == amount
    else:
        assert 'Сумма поручения' in response.json['error']

from tests.test_stand_outgoing_review import network, setup_send, tx, action, MARKER

@pytest.mark.usefixtures('stand_demo_environment')
def test_transfer_before_order_needs_explicit_checkbox(api, network):
    setup_send(api)
    ref = f'{31:064x}'
    network.append(tx(31, 10130, ts=MARKER-1))
    api[1][0] = 'teodor'
    sent = action(api)
    assert sent.status_code == 200
    d = sent.json['data']['deals'][0]
    assert d['step'] == 's23'
    assert any(c['hash'] == ref and c['beforeOrder'] for c in d['outgoingReview']['candidates'])
    api[1][0] = 'operator'
    denied = action(api, 'select', hashes=[ref])
    print('old_transfer_without_checkbox', denied.status_code, denied.json['error'])
    assert denied.status_code == 409
    assert 'до поручения' in denied.json['error']
    accepted = action(api, 'select', hashes=[ref], confirmBeforeOrder=True)
    print('old_transfer_with_checkbox', accepted.status_code,
          accepted.json['data']['deals'][0]['step'] if accepted.status_code == 200 else accepted.json['error'])
    assert accepted.status_code == 200
    assert accepted.json['data']['deals'][0]['step'] == 's26'
