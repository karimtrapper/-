"""QA пункта 2, путь s18w: приход USDT от брокера на чужой кошелёк пачки.

Предупреждение/ack действует только когда ожидаемый кошелёк пачки — кошелёк с политикой
(реестр: Груша Недвижимость / Груша Обменник). Старые кошельки (company, founder, teodor)
и СД-1484 остаются на прежнем поведении: неверный получатель → 422 без изменения доски.
"""
import copy
import time

import pytest

import app as m
from tests.test_stand_freehold_e2e_fixes import (
    api, base_api, chain, initial_board, prepare_after_rub, send_broker, post, tx)
from tests.test_stand_prepay import COMPANY, TEODOR, FOUNDER, seed
from tests.test_wallet_roles_qa import REALTY, EXCHANGE

pytestmark = pytest.mark.usefixtures('stand_demo_environment')


@pytest.fixture(autouse=True)
def _isolated_db():
    from tests.qa_wallet_roles_helpers import db_snapshot, db_restore
    snap = db_snapshot()
    yield
    db_restore(snap)


def conv_of(api_client):
    state = api_client.get('/api/stand/state').json
    return state['data']['convs'][0], state['version'], state['data']


def registry_id(address):
    db = m.get_session()
    try:
        return db.query(m.Wallet).filter_by(address=address).one().id
    finally:
        db.close()


def to_policy_wallet(api):
    """Пачка новой синтетической сделки ждёт приход на кошелёк реестра с политикой."""
    m._stand_seed_wallets()
    wx, wr = registry_id(EXCHANGE), registry_id(REALTY)
    state = api[0].get('/api/stand/state').json['data']
    state['wallets'] += [
        {'id': wx, 'addr': EXCHANGE, 'multisig': True, 'role': 'findir', 'owner': 'компания',
         'name': 'Груша Обменник'},
        {'id': wr, 'addr': REALTY, 'multisig': True, 'role': 'findir', 'owner': 'компания',
         'name': 'Груша Недвижимость'}]
    state['convs'][0]['walletId'] = wx
    for deal in state['deals']:
        deal['walletId'] = wx
    seed(state)
    return wx, wr


def test_legacy_wrong_receiver_keeps_old_422_and_changes_nothing(api, chain):
    """Прежнее поведение СД-1484: неверный получатель → 422, доска не меняется."""
    initial_board(api); prepare_after_rub(api); send_broker(api)
    chain.append(tx(901, 100, sender=TEODOR, to=FOUNDER, ts=int(time.time() * 1000) + 1000))
    before = api[0].get('/api/stand/state').json
    r = api[0].post('/api/stand/incoming/check', json={
        'dealId': 1484, 'hash': chain.ref(901), 'network': 'TRC-20'})
    assert r.status_code == 422, r.json
    after = api[0].get('/api/stand/state').json
    assert after['version'] == before['version'] and after['data'] == before['data']
    assert not after['data']['convs'][0].get('recipientWarnings')


def test_s18w_wrong_wallet_warning_ack_switch_wallet_then_credit(api, chain):
    initial_board(api); prepare_after_rub(api); send_broker(api)
    wx, wr = to_policy_wallet(api)
    chain.append(tx(901, 100, sender=TEODOR, to=REALTY, ts=int(time.time() * 1000) + 1000))
    payload = {'dealId': 1484, 'hash': chain.ref(901), 'network': 'TRC-20'}
    r = api[0].post('/api/stand/incoming/check', json=payload)
    assert r.status_code == 409, r.json
    warning = r.json['warning']
    assert warning['expected'] == EXCHANGE and warning['actual'] == REALTY
    assert warning['acknowledgedById'] is None
    conv, version, data = conv_of(api[0])
    assert conv['recipientWarnings'] and not conv.get('txs'), 'предупреждение сохранено, зачёта нет'
    again = api[0].post('/api/stand/incoming/check', json=payload)
    assert again.status_code == 409 and len(conv_of(api[0])[0]['recipientWarnings']) == 1
    acked = api[0].post('/api/stand/incoming/ack-recipient', json={
        'dealId': 1484, 'hash': chain.ref(901), 'expected': EXCHANGE, 'actual': REALTY,
        'version': conv_of(api[0])[1]})
    assert acked.status_code == 200, acked.json
    conv, version, data = conv_of(api[0])
    assert conv['recipientWarnings'][0]['acknowledgedById']
    assert not conv.get('txs')
    still = api[0].post('/api/stand/incoming/check', json=payload)
    assert still.status_code == 409, 'ack без смены кошелька не открывает зачёт'
    post(api, 'operator', '/api/stand/incoming/wallet', dealId=1484, walletId=wr,
         version=conv_of(api[0])[1])
    checked = post(api, 'operator', '/api/stand/incoming/check', **payload)
    assert checked['tx']['to'] == REALTY
    conv, _, _ = conv_of(api[0])
    assert conv['txs'][0]['status'] == 'confirmed' and conv['recipientWarnings'][0]['acknowledgedById']


@pytest.mark.parametrize('mutation', ['delete_conv', 'rekey_conv', 'drop_field', 'clear_list', 'forge_ack'])
def test_s18w_state_put_cannot_erase_or_forge_conv_warning(api, chain, mutation):
    initial_board(api); prepare_after_rub(api); send_broker(api)
    to_policy_wallet(api)
    chain.append(tx(901, 100, sender=TEODOR, to=REALTY, ts=int(time.time() * 1000) + 1000))
    api[0].post('/api/stand/incoming/check', json={'dealId': 1484, 'hash': chain.ref(901),
                                                    'network': 'TRC-20'})
    real = conv_of(api[0])[0]['recipientWarnings']
    assert real and real[0]['acknowledgedById'] is None
    api[1][0] = 'operator'
    mutate = {
        'delete_conv': lambda s: s.update(convs=[]),
        'rekey_conv': lambda s: (s['convs'][0].update(id=99, recipientWarnings=[]),
                                 s['deals'][0].update(cnvId=99)),
        'drop_field': lambda s: s['convs'][0].pop('recipientWarnings'),
        'clear_list': lambda s: s['convs'][0].update(recipientWarnings=[]),
        'forge_ack': lambda s: s['convs'][0]['recipientWarnings'][0].update(
            acknowledgedById=1, acknowledgedAt=1),
    }[mutation]
    snap = api[0].get('/api/stand/state').json
    forged = copy.deepcopy(snap['data'])
    mutate(forged)
    r = api[0].put('/api/stand/state', json={'version': snap['version'], 'data': forged})
    assert r.status_code in (200, 400, 403, 409)
    assert 'Правила кошелька берутся только из реестра' not in str(r.json), 'отказ не от того сторожка'
    state = api[0].get('/api/stand/state').json['data']
    assert state['convs'][0]['recipientWarnings'] == real, 'предупреждение сохранено при любой подмене'
    assert not state['convs'][0].get('txs')
    assert state['deals'][0]['cnvId'] == state['convs'][0]['id']
