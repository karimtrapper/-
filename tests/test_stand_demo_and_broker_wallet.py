"""Живой стенд без DEMO и фактический кошелёк прихода брокера."""
import copy
import json
import time
from pathlib import Path

import pytest
import app as m
from stand_transfers import verify_transfer
from tests.test_stand_freehold_e2e_fixes import (
    api, base_api, chain, initial_board, prepare_after_rub, send_broker, receive_broker,
    ipps_order, send_ipps, close_via_roles, post, edit, tx,
)
from tests.test_stand_prepay import seed, COMPANY, TEODOR, FOUNDER, IPPS


@pytest.fixture(autouse=True)
def live_mode(monkeypatch):
    monkeypatch.delenv('STAND_ALLOW_DEMO', raising=False)


def test_demo_webhook_requires_environment_opt_in(api):
    response = api[0].post('/api/stand/transfers/demo', json={
        'dealId': 1473, 'ref': 'demo:1473:send', 'outcome': 'confirmed'})
    assert response.status_code == 403


def test_demo_verifier_requires_environment_opt_in(monkeypatch):
    args = ('demo:1473:send', 'TRC-20', TEODOR, IPPS, 100)
    assert verify_transfer(*args, demo=True, demo_outcome='confirmed')['status'] == 'mismatch'
    monkeypatch.setenv('STAND_ALLOW_DEMO', '1')
    assert verify_transfer(*args, demo=True, demo_outcome='confirmed')['status'] == 'confirmed'


def snapshot_1473():
    return json.loads((Path(__file__).parent / 'fixtures/stand_1473_demo_anonymized.json').read_text())


def test_1473_demo_income_history_is_preserved(api):
    state = snapshot_1473()
    seed(state)
    response = api[0].get('/api/stand/state').json
    deal = response['data']['deals'][0]
    assert deal['demoTransfers'] is True
    assert deal['payinHashes'] == state['deals'][0]['payinHashes']
    assert response['demoWarnings'] == [1473]
    assert response['demoEnabled'] is False


def test_flag_without_demo_money_is_repaired_once(api):
    state = snapshot_1473()
    deal = state['deals'][0]
    # Синтетический вариант: ошибочный флаг без проведённых DEMO-приходов.
    deal.update(payinHashes=[], pay={}, log=[])
    seed(state)
    first = api[0].get('/api/stand/state').json
    second = api[0].get('/api/stand/state').json
    assert first['data']['deals'][0]['demoTransfers'] is False
    assert first['version'] == 2 == second['version']
    assert first['data']['deals'][0]['log']
    assert first['demoWarnings'] == []
    assert api[0].put('/api/stand/state', json={'version': 1, 'data': state}).status_code == 409


@pytest.mark.parametrize('location', ['payinParts', 'transfer', 'convs', 'income'])
def test_migration_keeps_any_demo_money_evidence(api, location):
    state = snapshot_1473(); d = state['deals'][0]
    d.update(payinHashes=[], pay={}, log=[])
    if location == 'payinParts': d['payinParts'] = [{'demo': True, 'amountRub': 10}]
    if location == 'transfer': d['transfer'] = {'sends': [{'ref': 'demo:1473:send'}]}
    if location == 'convs':
        d['cnvId'] = 1
        state['convs'] = [{'id': 1, 'txs': [{'hash': 'demo:incoming:1:a'}]}]
    if location == 'income':
        d['payinParts'] = [{'incId': 1}]
        state['incomes'] = [{'id': 1, 'demo': True}]
    seed(state)
    result = api[0].get('/api/stand/state').json
    assert result['data']['deals'][0]['demoTransfers'] is True
    assert result['demoWarnings'] == [1473]


def test_cannot_enable_demo_by_board_save(api):
    saved = initial_board(api)
    saved['data']['deals'][0]['demoTransfers'] = True
    response = api[0].put('/api/stand/state', json={'version': saved['version'], 'data': saved['data']})
    assert response.status_code == 409


def test_sequential_freehold_real_hash_to_close(api, chain):
    initial_board(api); prepare_after_rub(api); send_broker(api)
    receive_broker(api, chain); ipps_order(api, IPPS)
    sent = send_ipps(api, chain, personal=False)['data']['deals'][0]
    assert not sent['demoTransfers']
    assert all(not h.get('demo') and not h['ref'].startswith('demo:') for h in sent['transfer']['sends'])
    assert close_via_roles(api)['deal']['net_profit_usdt'] == 870


@pytest.mark.parametrize('actual', ['founder', 'teodor'])
def test_prepay_actual_broker_wallet_to_close(api, chain, actual):
    initial_board(api); saved = prepare_after_rub(api)
    post(api, 'operator', '/api/stand/prepay', action='start', dealId=1484,
         walletId='teodor', version=saved['version'])
    ipps_order(api, IPPS); send_ipps(api, chain, personal=True)
    saved = send_broker(api)
    result = post(api, 'operator', '/api/stand/incoming/wallet', dealId=1484,
                  walletId=actual, version=saved['version'])
    assert result['data']['deals'][0]['prepay']['wallet']['addr'] == TEODOR
    target = FOUNDER if actual == 'founder' else TEODOR
    chain.append(tx(901, 11000, sender=COMPANY, to=target, ts=int(time.time()*1000)+1000))
    post(api, 'operator', '/api/stand/incoming/check', dealId=1484, hash=chain.ref(901), network='TRC-20')
    def receive(s,d):
        s['convs'][0]['sources'][0]['usdtFact'] = 11000
        s['convs'][0]['status'] = 'received'
        d['pay'].update(usdt=11000, hash=chain.ref(901))
        d['payinHashes'] = [{'hash': chain.ref(901), 'amount': 11000, 'net': 'TRC-20'}]
        d['prepay']['brokerStep'] = 'done'
    saved = edit(api, 'operator', receive)
    if actual == 'founder':
        chain.append(tx(903, 10130, sender=FOUNDER, to=TEODOR, ts=int(time.time()*1000)+1000))
        saved = post(api, 'teodor', '/api/stand/prepay/reimburse', dealId=1484, hash=chain.ref(903))
    assert saved['data']['deals'][0]['payout']['reimbursement']['usdt'] == 10130
    assert close_via_roles(api)['deal']['net_profit_usdt'] == 870


@pytest.mark.parametrize('case', ['manager', 'stale', 'unknown', 'unregistered', 'confirmed', 'not_waiting', 'sent', 'other_member'])
def test_incoming_wallet_change_is_narrow(api, case):
    initial_board(api); prepare_after_rub(api); saved = send_broker(api)
    if case in ('confirmed', 'not_waiting', 'sent', 'other_member', 'unregistered'):
        state = saved['data']; d = state['deals'][0]
        if case == 'confirmed': state['convs'][0]['txs'] = [{'status': 'confirmed', 'hash': 'a'*64}]
        if case == 'not_waiting': d['step'] = 's18'
        if case == 'sent': d['transfer'] = {'sends': [{'ref': 'a'*64}]}
        if case == 'other_member':
            state['deals'].append({'id': 2, 'step': 's23', 'cnvId': 1})
        if case == 'unregistered': state['wallets'][1]['addr'] = IPPS
        seed(state); saved = api[0].get('/api/stand/state').json
    api[1][0] = 'manager' if case == 'manager' else 'operator'
    before = copy.deepcopy(saved['data'])
    response = api[0].post('/api/stand/incoming/wallet', json={'dealId': 1484,
        'walletId': 'unknown' if case == 'unknown' else 'founder',
        'version': -1 if case == 'stale' else saved['version']})
    assert response.status_code == (403 if case == 'manager' else 409), response.json
    assert api[0].get('/api/stand/state').json['data'] == before


def test_broker_checks_actual_receiver_and_locks_after_first_part(api, chain):
    initial_board(api); prepare_after_rub(api); saved = send_broker(api)
    chain.append(tx(901, 100, sender=TEODOR, to=FOUNDER, ts=int(time.time()*1000)+1000))
    payload = {'dealId': 1484, 'hash': chain.ref(901), 'network': 'TRC-20'}
    assert api[0].post('/api/stand/incoming/check', json=payload).status_code == 422
    post(api, 'operator', '/api/stand/incoming/wallet', dealId=1484, walletId='founder', version=saved['version'])
    checked = post(api, 'operator', '/api/stand/incoming/check', **payload)
    assert checked['tx']['to'] == FOUNDER
    response = api[0].post('/api/stand/incoming/wallet', json={'dealId': 1484,
        'walletId': 'company', 'version': checked['version']})
    assert response.status_code == 409


def test_1473_cannot_clear_history_or_advance_by_save(api):
    seed(snapshot_1473())
    saved = api[0].get('/api/stand/state').json
    for change in ({'demoTransfers': False}, {'step': 's23'}):
        state = copy.deepcopy(saved['data']); state['deals'][0].update(change)
        response = api[0].put('/api/stand/state', json={'version': saved['version'], 'data': state})
        assert response.status_code == 409


def test_cannot_claim_old_unbound_demo_income_without_opt_in(api):
    saved = initial_board(api)
    state = saved['data']; state['incomes'][0]['demo'] = True
    seed(state); saved = api[0].get('/api/stand/state').json
    saved['data']['deals'][0]['payinParts'] = [{'incId': 1, 'amountRub': 900000}]
    saved['data']['incomes'][0]['dealId'] = 1484
    api[1][0] = 'manager'
    response = api[0].put('/api/stand/state', json={'version': saved['version'], 'data': saved['data']})
    assert response.status_code == 409
    assert 'DEMO' in response.json['error']


def test_wallet_change_keeps_waiting_batch_sources_and_paid_payer(api):
    initial_board(api); prepare_after_rub(api); saved = send_broker(api)
    state = saved['data']
    state['convs'][0]['sources'].append({'dealId': 2, 'rub': 10000})
    state['deals'].append({'id': 2, 'step': 'ready', 'cnvId': 1, 'walletId': 'company'})
    seed(state); saved = api[0].get('/api/stand/state').json
    result = post(api, 'operator', '/api/stand/incoming/wallet', dealId=1484,
                  walletId='founder', version=saved['version'])
    assert [d['walletId'] for d in result['data']['deals']] == ['founder', 'founder']
    assert result['data']['convs'][0]['sources'] == state['convs'][0]['sources']
