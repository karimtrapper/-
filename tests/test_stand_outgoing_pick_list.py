"""1484/1487: суммы, адреса и московское время из прогона, сеть синтетическая.
Полные хеши в задании не даны: префиксы дополнены нулями только для фикстуры.
"""
import copy
from datetime import datetime
from decimal import Decimal

import pytest
import app as m
import stand_egress
import stand_transfer_discovery as discovery
from tests.test_stand_freehold_e2e_fixes import api, base_api, edit, post
from tests.test_stand_outgoing_review import setup_send
from tests.test_stand_prepay import seed, TEODOR, COMPANY

IPPS = 'TXFqZbXCqoq5QVxRpp9EGLSzkeLMz8iG5D'
ENERGY = 'TLntW9Z59LYY5KEi9cmwk3PKjQga828ird'
CASES = [(1487, 2234.76, '2026-10-13T12:15:00+03:00', '2026-10-13T14:33:00+03:00', '81f87ac971'),
         (1484, 5507.16, '2026-10-12T13:33:00+03:00', '2026-10-12T15:18:00+03:00', '567e2fa168')]

def stamp(value):
    return int(datetime.fromisoformat(value).timestamp()*1000)


def event(ref, amount, to, ts):
    return {'transaction_id':ref, 'quant':str(int(Decimal(str(amount))*1000000)),
        'from_address':TEODOR, 'to_address':to, 'block_ts':ts, 'contract_address':discovery.USDT_TRC20,
        'confirmed':True, 'finalResult':'SUCCESS', 'event_type':'Transfer', 'contractRet':'SUCCESS', 'status':0}


@pytest.fixture
def chain(monkeypatch):
    class Chain(list):
        calls = 0
        offline = False
    rows = Chain()
    def read(op, params):
        rows.calls += 1
        if rows.offline:
            return 503, {}, 'stand_blocked'
        if op == 'tron_trc20_transfers':
            return 200, {'token_transfers': sorted(rows, key=lambda t:-t['block_ts']), 'total':len(rows)}, None
        assert op == 'tron_tx_info'
        events = [r for r in rows if r['transaction_id'] == params['hash']]
        if not events: return 404, {}, None
        return 200, {'hash':params['hash'], 'confirmed':True, 'contractRet':'SUCCESS', 'revert':False,
            'timestamp':events[0]['block_ts'], 'trc20TransferInfo':[{
                'contract_address':discovery.USDT_TRC20, 'from_address':r['from_address'],
                'to_address':r['to_address'], 'amount_str':r['quant'], 'decimals':6} for r in events]}, None
    monkeypatch.setenv('STAND_MODE','1')
    monkeypatch.delenv('STAND_ALLOW_DEMO', raising=False)
    monkeypatch.setattr(stand_egress,'read_get',read)
    return rows


def snapshot(api, chain, case=CASES[0]):
    id, amount, sent, ordered, prefix = case
    state = setup_send(api)
    d = state['deals'][0]
    d.update(id=id, code=f'СД-{id}', invoiceUsd=round((amount-50)/1.008,2))
    d['prepay']['amount'] = amount
    d['transfer'].update(amount=amount, addr=IPPS)
    d['ippsPayoutOrder'].update(amount=amount, address=IPPS, confirmedAt=ordered)
    state['incomes'][0]['dealId'] = id
    state['convs'][0]['sources'][0]['dealId'] = id
    ref = prefix.ljust(64,'0')
    chain.extend([event(ref, 1.5, ENERGY, stamp(sent)), event(ref, amount, IPPS, stamp(sent))])
    seed(state)
    return id, ref


def act(api, id, action, **data):
    saved = api[0].get('/api/stand/state').json
    return api[0].post('/api/stand/transfers/review', json={
        'dealId':id,'action':action,'version':saved['version'], **data})


def opened(api, chain, case=CASES[0]):
    id, ref = snapshot(api, chain, case)
    api[1][0] = 'teodor'
    response = act(api,id,'sent')
    assert response.status_code == 200, response.json
    api[1][0] = 'operator'
    return id, ref, response.json['data']['deals'][0]


@pytest.mark.parametrize('case',CASES,ids=['1487','1484'])
def test_exact_live_timing_pick_requires_ack_then_s26(api,chain,case):
    id, ref, d = opened(api,chain,case)
    assert d['step'] == 's23'
    candidates = d['outgoingReview']['candidates']
    assert len(candidates) == 2
    assert candidates[0]['to'] == IPPS and candidates[0]['selectable']
    assert candidates[0]['beforeOrder']
    assert candidates[1]['networkFee'] and not candidates[1]['selectable']
    denied = act(api,id,'select',hashes=[ref])
    assert denied.status_code == 409 and 'до поручения' in denied.json['error']
    response = act(api,id,'select',hashes=[ref],confirmBeforeOrder=True)
    assert response.status_code == 200,response.json
    d = response.json['data']['deals'][0]
    assert d['step'] == 's26' and d['serverTransferComplete']
    assert d['payout']['usdt'] == case[1], '1.5 на энергию не добавляются к оплате'
    assert d['transfer']['sends'][0]['to'] == IPPS
    assert any('до поручения — подтверждаю' in x['text'] and ref in x['text'] for x in d['log'])


def test_wrong_address_and_energy_are_not_selectable(api,chain):
    id, ref, _ = opened(api,chain)
    wrong, energy = m.secrets.token_hex(32), m.secrets.token_hex(32)
    chain.extend([event(wrong,2234.76,COMPANY,stamp(CASES[0][2])),event(energy,1.5,ENERGY,stamp(CASES[0][2]))])
    refreshed = act(api,id,'list')
    assert refreshed.status_code == 200
    for h in (wrong,energy):
        r = act(api,id,'select',hashes=[h],confirmBeforeOrder=True,confirmOverpay=True)
        assert r.status_code == 409,r.json
    assert api[0].get('/api/stand/state').json['data']['deals'][0]['step'] == 's23'


@pytest.mark.parametrize('actor',['manager','teodor','findir'])
def test_picker_roles(api,chain,actor):
    id, ref, _ = opened(api,chain)
    api[1][0] = actor
    for action in ('list','select'):
        assert act(api,id,action,hashes=[ref],confirmBeforeOrder=True).status_code == 403


def test_admin_can_pick(api,chain):
    id, ref, _ = opened(api,chain)
    api[1][0] = 'admin'
    assert act(api,id,'select',hashes=[ref],confirmBeforeOrder=True).json['data']['deals'][0]['step'] == 's26'


def test_selected_partial_then_overpay_requires_confirmation(api,chain):
    id, ref, _ = opened(api,chain)
    extra = m.secrets.token_hex(32)
    # Список — подсказка; фактическую сумму сервер заново читает из transaction-info.
    chain[1]['quant'] = '1000000'
    d = act(api,id,'select',hashes=[ref],confirmBeforeOrder=True).json['data']['deals'][0]
    assert d['step'] == 's23' and d['transfer']['sends'][0]['verifiedAmount'] == 1
    chain.append(event(extra,2235,IPPS,stamp(CASES[0][2])+1000))
    act(api,id,'list')
    r = act(api,id,'select',hashes=[ref,extra],confirmBeforeOrder=True)
    assert r.status_code == 409 and 'Переплата' in r.json['error']
    r = act(api,id,'select',hashes=[ref,extra],confirmBeforeOrder=True,confirmOverpay=True)
    assert r.status_code == 200,r.json
    d = r.json['data']['deals'][0]
    assert d['step'] == 's26' and d['payout']['usdt'] == 2236
    assert any('переплата' in x['text'] for x in d['log'])


def test_list_cache_and_offline_manual_fallback(api,chain,monkeypatch):
    id, ref, _ = opened(api,chain)
    act(api,id,'list'); before=chain.calls
    act(api,id,'list')
    assert chain.calls == before
    chain.offline = True
    monkeypatch.setattr(discovery.time, 'monotonic', lambda:10**15)
    r = act(api,id,'list')
    assert r.json['data']['deals'][0]['outgoingReview']['error'] == 'fetch_error'
    assert not r.json['data']['deals'][0].get('serverTransferComplete')
    chain.offline = False
    edit(api,'operator',lambda s,d:d['transfer'].update(sends=[{'ref':ref,'amount':2234.76,'net':'TRC-20'}]))
    d = post(api,'operator','/api/stand/transfers/check',dealId=id)['data']['deals'][0]
    assert d['transfer']['sends'][0]['beforeOrder'] and d['step'] == 's23'
    assert act(api,id,'accept',fingerprint=d['outgoingReview']['selectionFingerprint']).status_code == 409
    # A network fee shares this transaction: the operator must decide whether
    # to include it in cost, even when the IPPS payment itself was verified.
    assert act(api,id,'accept',fingerprint=d['outgoingReview']['selectionFingerprint'],confirmBeforeOrder=True).json['data']['deals'][0]['step'] == 's23'
    chosen = act(api,id,'select',hashes=[ref],commissionHashes=[ref],confirmBeforeOrder=True)
    assert chosen.status_code == 200, chosen.json
    assert chosen.json['data']['deals'][0]['step'] == 's26'


def test_claimed_hash_displays_deal_and_cannot_be_selected(api,chain):
    id, ref = snapshot(api,chain)
    state=api[0].get('/api/stand/state').json['data']
    state['deals'].append({'id':999,'code':'СД-999','step':'done','payinHashes':[{'hash':ref,'amount':2234.76}]})
    seed(state)
    api[1][0]='teodor';act(api,id,'sent');api[1][0]='operator'
    listed=act(api,id,'list').json['data']['deals'][0]['outgoingReview']['candidates']
    assert listed[0]['claimedBy']=='СД-999' and not listed[0]['selectable']
    r=act(api,id,'select',hashes=[ref],confirmBeforeOrder=True)
    assert r.status_code==409 and 'СД-999' in r.json['error']


def test_version_race_during_network_lookup_cannot_settle(api,chain,monkeypatch):
    id,ref,_=opened(api,chain)
    original=m.verify_transfer
    def race(*args,**kwargs):
        db=m.get_session()
        try:
            m._stand_row(db).version+=1;db.commit()
        finally:db.close()
        return original(*args,**kwargs)
    monkeypatch.setattr(m,'verify_transfer',race)
    assert act(api,id,'select',hashes=[ref],confirmBeforeOrder=True).status_code==409
    assert api[0].get('/api/stand/state').json['data']['deals'][0]['step']=='s23'


def test_hash_cannot_be_claimed_by_two_deals(api,chain):
    id,ref,_=opened(api,chain)
    state=api[0].get('/api/stand/state').json['data']
    other=copy.deepcopy(state['deals'][0]);other.update(id=1490,code='СД-1490')
    other.pop('cnvId',None)
    state['deals'].append(other);seed(state)
    api[1][0]='operator'
    assert act(api,id,'select',hashes=[ref],confirmBeforeOrder=True).status_code==200
    r=act(api,1490,'select',hashes=[ref],confirmBeforeOrder=True)
    assert r.status_code==409 and f'СД-{id}' in r.json['error']


def test_registered_wrong_address_cannot_bypass_network_check(api,chain):
    id,_,_=opened(api,chain)
    ref=m.secrets.token_hex(32);chain.append(event(ref,2234.76,COMPANY,stamp(CASES[0][2])))
    edit(api,'operator',lambda s,d:d['transfer'].update(sends=[{'ref':ref,'amount':2234.76,'net':'TRC-20'}]))
    r=act(api,id,'select',hashes=[ref],confirmBeforeOrder=True)
    assert r.status_code==409 and 'не совпали' in r.json['error']


def test_newer_payment_with_energy_event_waits_for_fee_choice(api,chain):
    id,ref=snapshot(api,chain)
    for row in chain:row['block_ts']=stamp(CASES[0][3])+1000
    api[1][0]='teodor'
    d=act(api,id,'sent').json['data']['deals'][0]
    assert d['step']=='s23' and not d.get('serverTransferComplete')
    api[1][0]='operator'
    chosen=act(api,id,'select',hashes=[ref],commissionHashes=[],confirmBeforeOrder=True)
    assert chosen.status_code==200,chosen.json
    assert chosen.json['data']['deals'][0]['step']=='s26'


def test_seven_day_window_and_conflicting_same_recipient(api,chain):
    id,ref=snapshot(api,chain)
    old=m.secrets.token_hex(32)
    chain.append(event(old,1,IPPS,stamp(CASES[0][3])-8*86400000))
    api[1][0]='teodor'
    rows=act(api,id,'sent').json['data']['deals'][0]['outgoingReview']['candidates']
    assert old not in {r['hash'] for r in rows}
    chain.append(event(ref,10,IPPS,stamp(CASES[0][2])))
    api[1][0]='operator'
    r=act(api,id,'list').json['data']['deals'][0]
    assert r['outgoingReview']['scanStatus']=='incomplete'
    assert r['outgoingReview']['error']=='conflicting_hash'
    assert not r.get('serverTransferComplete')


def test_concurrent_selections_settle_only_one_deal(api,chain,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    id,ref,_=opened(api,chain)
    state=api[0].get('/api/stand/state').json['data']
    other=copy.deepcopy(state['deals'][0]);other.update(id=1490,code='СД-1490');other.pop('cnvId',None)
    state['deals'].append(other);seed(state)
    saved=api[0].get('/api/stand/state').json
    with api[0].session_transaction() as sess: uid=sess['user_id']
    barrier=Barrier(2);original=m.verify_transfer
    def together(*args,**kwargs):
        proof=original(*args,**kwargs);barrier.wait(timeout=5);return proof
    monkeypatch.setattr(m,'verify_transfer',together)
    def choose(deal_id):
        client=m.app.test_client()
        with client.session_transaction() as sess:sess['user_id']=uid
        return client.post('/api/stand/transfers/review',json={'dealId':deal_id,'action':'select',
            'hashes':[ref],'version':saved['version'],'confirmBeforeOrder':True}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses=list(pool.map(choose,[id,1490]))
    assert sorted(statuses)==[200,409]
    deals=api[0].get('/api/stand/state').json['data']['deals']
    assert sum(bool(d.get('serverTransferComplete')) for d in deals)==1


@pytest.mark.parametrize('route,step',[('coins','s25'),('client','done')])
def test_picker_sequential_personal_send(api,chain,route,step):
    state=setup_send(api,route=route,prepay=False)
    state['deals'][0]['outgoingOrderAt']=CASES[0][3]
    seed(state)
    ref=m.secrets.token_hex(32)
    chain.append(event(ref,10130,state['deals'][0]['transfer']['addr'],stamp(CASES[0][2])))
    api[1][0]='teodor';act(api,1484,'sent');api[1][0]='operator'
    r=act(api,1484,'select',hashes=[ref],confirmBeforeOrder=True)
    assert r.status_code==200,r.json
    assert r.json['data']['deals'][0]['step']==step


def test_crm_claim_shows_where_used(api,chain):
    import json
    id,ref=snapshot(api,chain)
    db=m.get_session()
    try:
        crm=m.Deal(deal_type=m.DealType.PAY_OUT,client_name='Synthetic claim',
                   payout_tx_hashes=json.dumps([{'hash':ref,'amount_usdt':2234.76}]))
        db.add(crm);db.commit();crm_id=crm.id
    finally:db.close()
    try:
        api[1][0]='teodor';act(api,id,'sent');api[1][0]='operator'
        rows=act(api,id,'list').json['data']['deals'][0]['outgoingReview']['candidates']
        assert rows[0]['claimedBy']==f'CRM #{crm_id}' and not rows[0]['selectable']
        r=act(api,id,'select',hashes=[ref],confirmBeforeOrder=True)
        assert r.status_code==409 and f'CRM #{crm_id}' in r.json['error']
    finally:
        db=m.get_session()
        try:db.query(m.Deal).filter_by(id=crm_id).delete();db.commit()
        finally:db.close()


def test_put_cannot_clear_before_order_flag(api,chain):
    id,ref,_=opened(api,chain)
    edit(api,'operator',lambda s,d:d['transfer'].update(sends=[{'ref':ref,'amount':2234.76,'net':'TRC-20'}]))
    post(api,'operator','/api/stand/transfers/check',dealId=id)
    d=edit(api,'operator',lambda s,d:d['transfer']['sends'][0].update(beforeOrder=False))['data']['deals'][0]
    assert d['transfer']['sends'][0]['beforeOrder'] is True
    assert d['step']=='s23' and not d.get('serverTransferComplete')
