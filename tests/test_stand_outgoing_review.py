"""Синтетический сценарий 1484 и проверка личных отправок через общий сетевой адаптер."""
import copy
from decimal import Decimal

import pytest
import app as m
import stand_egress
import stand_outgoing_review as review
from stand_transfer_discovery import USDT_TRC20
from tests.test_stand_prepay import api, seed, start, order, TEODOR, COMPANY, FOUNDER

MARKER = 1700000000000


def setup_send(api, route='ipps_swift', prepay=True):
    saved = order(api, start(api, 'teodor'))
    state = saved['data']
    d = state['deals'][0]
    # Сохранённая s23 без новых полей; адрес заявки отличается от подсказки IPPS.
    d.update(demoTransfers=False, walletId='teodor')
    d['transfer'].update(addr=FOUNDER, amount=10130)
    d['ippsPayoutOrder'] = {'amount': 10130, 'address': FOUNDER, 'network': 'TRC-20',
                            'confirmedAt': '2023-11-14T22:13:20Z'}
    d.pop('outgoingOrderAt', None)
    if not prepay:
        d.pop('prepay', None)
        state['convs'] = []
        d.pop('cnvId', None)
        d['payType'] = 'Крипта'
        d['payinHashes'] = [{'hash': 'b'*64, 'amount': 11000, 'verified': True}]
    if route != 'ipps_swift':
        d.update(kind='Лизхолд' if route == 'coins' else None, postConv=route)
        d.pop('ippsPayoutOrder', None)
        d['outgoingOrderAt'] = '2023-11-14T22:13:20Z'
    seed(state)
    return state


def tx(n, amount, to=FOUNDER, sender=TEODOR, ts=MARKER+1000):
    return dict(transaction_id=f'{n:064x}', quant=str(int(Decimal(str(amount))*1000000)),
                block_ts=ts, from_address=sender, to_address=to,
                contract_address=USDT_TRC20, confirmed=True, finalResult='SUCCESS',
                event_type='Transfer', contractRet='SUCCESS', status=0)


@pytest.fixture
def network(monkeypatch):
    rows=[]
    def read(op, params):
        assert op == 'tron_trc20_transfers'
        return 200, {'token_transfers': sorted(rows, key=lambda t: -t['block_ts']), 'total':len(rows)}, None
    def verify(ref, net, sender, recipient, amount, **kw):
        t=next((t for t in rows if t['transaction_id']==ref), None)
        if not t or t['from_address']!=sender or t['to_address']!=recipient:
            return {'status':'mismatch','checkError':'адрес не совпал'}
        return {'status':'confirmed','verifiedAmount':float(Decimal(t['quant'])/1000000),
                'timestampMs':t['block_ts'], 'from':sender,'to':recipient}
    monkeypatch.setattr(stand_egress,'read_get',read)
    monkeypatch.setattr(m,'verify_transfer',verify)
    return rows


def action(api, action='sent', **data):
    snap=api[0].get('/api/stand/state').json
    response = api[0].post('/api/stand/transfers/review',json={'dealId':1484,'action':action,
                       'version':snap['version'], **data})
    return response


@pytest.mark.parametrize('prepay',[True,False])
def test_saved_s23_teodor_found_automatically_to_s26(api,network,prepay):
    setup_send(api,prepay=prepay)
    network.extend([tx(1,1),tx(2,10129)])
    api[1][0]='teodor'
    r=action(api)
    assert r.status_code==200,r.json
    d=r.json['data']['deals'][0]
    assert d['step']=='s26' and d['serverTransferComplete']
    assert d['payout']['usdt']==10130
    assert len(d['payout']['hashes'])==2
    assert any('сумма совпала' in e['text'] for e in d['log'])


@pytest.mark.parametrize('amount,closed',[(10129.995,True),(10129.994,False),(10130.005,True),(10130.006,False)])
def test_exact_tolerance(api,network,amount,closed):
    setup_send(api)
    network.append(tx(1,amount))
    api[1][0]='teodor'
    d=action(api).json['data']['deals'][0]
    assert (d['step']=='s26') == closed


def test_partial_owner_handoff_and_background_poll(api,network):
    setup_send(api)
    network.append(tx(1,1))
    api[1][0]='teodor'
    r=action(api)
    d=r.json['data']['deals'][0]
    assert d['step']=='s23'
    assert m._stand_current_step_role(r.json['data'],d)=='operator'
    network.append(tx(2,10129))
    m._stand_check_transfers(poll=True)
    assert api[0].get('/api/stand/state').json['data']['deals'][0]['step']=='s26'


def test_overpay_requires_operator_and_records_actual_cost(api,network):
    setup_send(api)
    network.append(tx(1,10200))
    api[1][0]='teodor'
    r=action(api)
    d=r.json['data']['deals'][0]
    assert d['step']=='s23' and not d.get('serverTransferComplete')
    fp=d['outgoingReview']['selectionFingerprint']
    assert action(api,'accept',fingerprint=fp).status_code==403
    api[1][0]='operator'
    assert action(api,'accept',fingerprint='stale').status_code==409
    r=action(api,'accept',fingerprint=fp)
    assert r.status_code==200,r.json
    d=r.json['data']['deals'][0]
    assert d['step']=='s26' and d['payout']['usdt']==10200
    assert sum(h['amount'] for h in d['mfPayout'])==10200
    assert any('переплата 70' in e['text'] for e in d['log'])


def test_remove_extra_keeps_it_ignored_on_rescan(api,network):
    setup_send(api)
    network.extend([tx(1,10130),tx(2,1)])
    api[1][0]='teodor'
    assert action(api).json['data']['deals'][0]['step']=='s23'
    api[1][0]='operator'
    r=action(api,'remove',hash=f'{2:064x}')
    assert r.status_code==200,r.json
    d=r.json['data']['deals'][0]
    assert d['step']=='s26' and d['payout']['usdt']==10130
    assert len(d['transfer']['sends'])==1


def test_wrong_destination_and_old_transfer_not_counted(api,network):
    setup_send(api)
    network.extend([tx(1,10130,to=COMPANY),tx(2,10130,ts=MARKER-1),tx(3,10130,sender=COMPANY)])
    api[1][0]='teodor'
    r=action(api)
    d=r.json['data']['deals'][0]
    assert d['step']=='s23' and not d['transfer']['sends']
    rows=d['outgoingReview']['candidates']
    assert len(rows)==2
    assert rows[0]['beforeOrder'] and rows[0]['selectable']
    assert rows[1]['reason']=='другой адрес' and not rows[1]['selectable']


def test_stale_network_result_cannot_attach(api,network,monkeypatch):
    setup_send(api)
    network.append(tx(1,10130))
    verify=m.verify_transfer
    def race(*args,**kwargs):
        snap=api[0].get('/api/stand/state').json['data']
        snap['deals'][0]['notes']='изменилось во время поиска'
        db=m.get_session()
        try:
            row=m._stand_row(db);row.version+=1;db.commit()
        finally:db.close()
        return verify(*args,**kwargs)
    monkeypatch.setattr(m,'verify_transfer',race)
    api[1][0]='teodor'
    d=action(api).json['data']['deals'][0]
    assert d['step']=='s23' and not d['transfer']['sends']


def test_review_server_only_and_manual_fallback(api,network):
    setup_send(api)
    api[1][0]='teodor'
    saved=action(api).json
    state=copy.deepcopy(saved['data'])
    state['deals'][0]['outgoingReview']['accepted']='forged'
    assert m._stand_guard_transition(saved['data'],state,'operator')
    network.append(tx(5,10130))
    # Хеш вручную, а доказательство и сумму подтверждает общая проверка сети.
    saved['data']['deals'][0]['transfer']['sends']=[{'ref':f'{5:064x}','amount':10130,'net':'TRC-20'}]
    api[1][0]='operator'
    r=api[0].put('/api/stand/state',json={'version':saved['version'],'data':saved['data']})
    assert r.status_code==200,r.json
    r=api[0].post('/api/stand/transfers/check',json={'dealId':1484})
    assert r.json['data']['deals'][0]['step']=='s26',r.json


def test_coins_sequential_personal_send(api,network):
    setup_send(api,route='coins',prepay=False)
    network.append(tx(1,10130))
    api[1][0]='teodor'
    d=action(api).json['data']['deals'][0]
    assert d['step']=='s25' and d['serverTransferComplete']


def test_multisig_does_not_get_personal_review(api,network):
    saved=order(api,start(api,'company'))
    api[1][0]='findir'
    assert action(api).status_code==409


def test_client_personal_send(api,network):
    setup_send(api,route='client',prepay=False)
    network.append(tx(1,10130))
    api[1][0]='teodor'
    r=action(api)
    assert r.status_code==200,r.json
    d=r.json['data']['deals'][0]
    assert d['step']=='done' and d['payout']['usdt']==10130


def test_incomplete_discovery_never_attaches(api,network,monkeypatch):
    setup_send(api)
    network.append(tx(1,10130))
    monkeypatch.setattr(stand_egress,'read_get',lambda *a: (200,{'token_transfers':network},None))
    api[1][0]='teodor'
    d=action(api).json['data']['deals'][0]
    assert d['outgoingReview']['scanStatus']=='incomplete'
    assert not d['transfer']['sends'] and d['step']=='s23'


def test_claimed_hash_is_visible_but_not_counted(api,network):
    state=setup_send(api)
    state['deals'].append({'id':99,'step':'done','payinHashes':[{'hash':f'{1:064x}','amount':10130}]})
    seed(state)
    network.append(tx(1,10130))
    api[1][0]='teodor'
    d=action(api).json['data']['deals'][0]
    assert d['outgoingReview']['candidates'][0]['reason']=='хеш уже занят: СД-99'
    assert not d['transfer']['sends']


def test_overlapping_orders_need_manual_selection(api,network):
    state=setup_send(api)
    other=copy.deepcopy(state['deals'][0]);other['id']=99
    state['deals'].append(other);seed(state)
    network.append(tx(1,10130))
    api[1][0]='teodor'
    d=action(api).json['data']['deals'][0]
    assert 'нескольким' in d['outgoingReview']['candidates'][0]['reason']
    assert not d['transfer']['sends']


def test_existing_s23_confirmation_can_be_done_without_database_edit(api,network):
    state=setup_send(api)
    state['deals'][0].pop('payToConfirm');seed(state)
    api[1][0]='teodor'
    assert action(api).status_code==409
    api[1][0]='manager'
    snap=api[0].get('/api/stand/state').json
    d=snap['data']['deals'][0];d['payToConfirm']={'payTo':dict(d['payTo']),'at':'confirmed'}
    r=api[0].put('/api/stand/state',json={'version':snap['version'],'data':snap['data']})
    assert r.status_code==200,r.json
    network.append(tx(1,10130));api[1][0]='teodor'
    assert action(api).json['data']['deals'][0]['step']=='s26'


def test_custom_personal_trc_wallet_uses_same_review(api, network):
    state = setup_send(api, route='coins', prepay=False)
    d = state['deals'][0]
    d.update(walletId='custom', payinCustom={'network': 'TRC-20', 'addr': TEODOR,
                                           'owner': 'Теодор', 'multisig': False})
    seed(state)
    network.append(tx(1, 10130))
    api[1][0] = 'operator'
    r = action(api)
    assert r.status_code == 200, r.json
    assert r.json['data']['deals'][0]['step'] == 's25'


def test_changed_requisites_during_review_block_poll_and_manual_check(api, network):
    setup_send(api)
    api[1][0] = 'teodor'
    state = action(api).json['data']
    state['deals'][0]['payTo']['account'] = 'changed'
    seed(state)
    network.append(tx(1, 10130))
    m._stand_check_transfers(poll=True)
    d = api[0].get('/api/stand/state').json['data']['deals'][0]
    assert d['step'] == 's23' and not d['transfer']['sends']
    assert m._stand_check_transfers(1484)['httpStatus'] == 409


def test_settlement_rechecks_latest_requisites_snapshot(api, network):
    setup_send(api)
    api[1][0] = 'teodor'
    state = action(api).json['data']
    d = state['deals'][0]
    d['outgoingReview']['scanStatus'] = 'complete'
    d['transfer']['sends'] = [{'hash': 'a'*64, 'amount': 10130,
                              'verifiedAmount': 10130, 'status': 'confirmed'}]
    d['payTo']['account'] = 'changed while checking network'
    assert not m._stand_settle_verified(state, [d])
    assert d['step'] == 's23' and not d.get('serverTransferComplete')


def test_old_coins_order_without_timestamp_keeps_manual_fallback(api, network):
    state = setup_send(api, route='coins', prepay=False)
    state['deals'][0].pop('outgoingOrderAt')
    seed(state)
    network.append(tx(5, 10130))
    api[1][0] = 'teodor'
    saved = action(api).json
    d = saved['data']['deals'][0]
    assert d['step'] == 's23' and not d['transfer']['sends']
    assert d['outgoingReview']['legacyTime']
    d['transfer']['sends'] = [{'ref': f'{5:064x}', 'amount': 10130, 'net': 'TRC-20'}]
    api[1][0] = 'operator'
    r = api[0].put('/api/stand/state', json={'version': saved['version'], 'data': saved['data']})
    assert r.status_code == 200, r.json
    r = api[0].post('/api/stand/transfers/check', json={'dealId': 1484})
    assert r.json['data']['deals'][0]['step'] == 's25', r.json
