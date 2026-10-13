"""Б1/Б2 из съёмки: ролевые действия без исправлений пула/БД по ходу сделки."""
import pytest
import app as m
from tests.test_stand_freehold_e2e_fixes import (
    api, base_api, chain, initial_board, prepare_after_rub, send_broker,
    ipps_order, edit, post, close_via_roles,
)
from tests.test_stand_prepay import IPPS
from tests.test_stand_outgoing_review import action, setup_send, tx

pytestmark = pytest.mark.usefixtures('stand_demo_environment')


def demo_broker(api):
    sent = send_broker(api)
    planned = sent['data']['convs'][0]['sources'][0]['usdt']
    first = round(planned * .6, 2)
    # Точно те же две части, которые создаёт s18 и выбирает оператор в s18w.
    def attach(s, d):
        s['convs'][0]['txs'] = [dict(hash=f'demo:incoming:1:{n}', amount=a,
            net='TRC20', status='confirmed', demo=True)
            for n, a in enumerate([first, round(planned-first, 2)])]
    edit(api, 'operator', attach)
    def receive(s, d):
        c = s['convs'][0]
        c['sources'][0]['usdtFact'] = planned
        c['status'] = 'received'
        d['pay'].update(usdt=planned, hash=c['txs'][0]['hash'])
        d['payinHashes'] = [dict(hash=t['hash'], amount=t['amount'], network=t['net']) for t in c['txs']]
        d['prepay']['brokerStep'] = 'done'
    return edit(api, 'operator', receive)


def demo_setup(api, wallet, invoice=10000, rub=900000):
    initial_board(api, invoice=invoice, rub=rub)
    edit(api, 'operator', lambda s,d: d.update(demoTransfers=True))
    saved = prepare_after_rub(api)
    return post(api, 'operator', '/api/stand/prepay', action='start', dealId=1484,
                walletId=wallet, version=saved['version'])


@pytest.mark.parametrize('wallet,invoice,rub', [('teodor',10000,900000), ('company',4000,327000)],
                         ids=['B1_personal', 'B2_multisig_broker_shortfall'])
@pytest.mark.parametrize('broker_first', [True, False])
def test_demo_prepay_to_closure(api, wallet, invoice, rub, broker_first):
    demo_setup(api, wallet, invoice, rub)
    out_ref = f'demo:1484:{m.secrets.token_hex(8)}'
    if broker_first:
        demo_broker(api)
    saved = ipps_order(api, IPPS)
    assert saved['data']['deals'][0]['step'] == 's23'
    if wallet == 'teodor':
        api[1][0] = 'teodor'
        assert action(api).status_code == 200
    def register(s,d):
        d['transfer']['sends'] = [{'ref':out_ref, 'amount':d['transfer']['amount'], 'net':'TRC-20'}]
        if wallet == 'company': d['step'] = 's24'
    edit(api, 'operator' if wallet == 'teodor' else 'findir', register)
    paid = post(api, 'teodor', '/api/stand/transfers/demo', dealId=1484,
                ref=out_ref, outcome='confirmed')
    d = paid['data']['deals'][0]
    assert d['step'] == 's26', d['transfer']['sends']
    if not broker_first:
        d = demo_broker(api)['data']['deals'][0]
    if wallet == 'company':
        assert d['pay']['usdt'] < d['payout']['usdt'], 'Недобор брокера не требует подгонять пул под заявку'
    if wallet == 'teodor':
        post(api, 'findir', '/api/stand/prepay/reimburse', dealId=1484, hash='demo:1484:refund')
    else:
        assert 'кошелёк совпал' in d['payout']['reimbursement']['kind']
    assert close_via_roles(api)['data']['deals'][0]['closed']


@pytest.mark.parametrize('stamp', [None, 0])
def test_real_missing_timestamp_requires_operator(api, chain, stamp):
    setup_send(api)
    api[1][0] = 'teodor'
    assert action(api).status_code == 200
    chain.append(tx(993, 10130, ts=stamp))
    edit(api, 'operator', lambda s,d: d['transfer'].update(sends=[{
        'ref': chain.ref(993), 'amount':10130, 'net':'TRC-20'}]))
    saved = post(api, 'operator', '/api/stand/transfers/check', dealId=1484)
    d = saved['data']['deals'][0]
    send = d['transfer']['sends'][0]
    assert d['step'] == 's23' and not d.get('serverTransferComplete')
    assert send['status'] == 'confirmed', send
    assert send['timeUnverified'] is True
    assert 'до поручения' not in send.get('checkError', '')
    api[1][0] = 'teodor'
    assert action(api, 'accept', fingerprint=d['outgoingReview']['selectionFingerprint']).status_code == 403
    api[1][0] = 'operator'
    accepted = action(api, 'accept', fingerprint=d['outgoingReview']['selectionFingerprint'])
    assert accepted.status_code == 200, accepted.json
    assert accepted.json['data']['deals'][0]['step'] == 's26'
    assert any('время' in e['text'] for e in accepted.json['data']['deals'][0]['log'])


def test_demo_registration_time_is_stable_and_server_owned(api):
    demo_setup(api, 'teodor')
    ipps_order(api, IPPS)
    api[1][0] = 'teodor'
    assert action(api).status_code == 200
    saved = edit(api, 'operator', lambda s,d: d['transfer'].update(sends=[{
        'ref':'demo:1484:time', 'amount':10130, 'net':'TRC-20', 'registeredAtMs':1}]))
    registered = saved['data']['deals'][0]['transfer']['sends'][0]['registeredAtMs']
    assert registered > 1
    saved = edit(api, 'operator', lambda s,d: d['transfer']['sends'][0].update(registeredAtMs=2))
    assert saved['data']['deals'][0]['transfer']['sends'][0]['registeredAtMs'] == registered
    result = post(api, 'teodor', '/api/stand/transfers/demo', dealId=1484,
                  ref='demo:1484:time', outcome='confirmed')
    assert result['data']['deals'][0]['transfer']['sends'][0]['timestampMs'] == registered
    assert result['data']['deals'][0]['step'] == 's26'


def test_known_old_transfer_cannot_be_accepted(api, chain):
    setup_send(api)
    api[1][0] = 'teodor'
    assert action(api).status_code == 200
    chain.append(tx(994, 10130, ts=1))
    edit(api, 'operator', lambda s,d: d['transfer'].update(sends=[{
        'ref':chain.ref(994), 'amount':10130, 'net':'TRC-20'}]))
    d = post(api, 'operator', '/api/stand/transfers/check', dealId=1484)['data']['deals'][0]
    assert d['transfer']['sends'][0]['checkError'] == 'Перевод сделан до поручения'
    assert action(api, 'accept', fingerprint=d['outgoingReview']['selectionFingerprint']).status_code == 409


def test_missing_time_in_discovery_proof_requires_manual_accept(api, chain, monkeypatch):
    setup_send(api)
    chain.append(tx(995, 10130))
    original = m.verify_transfer
    def without_time(*args, **kwargs):
        proof = original(*args, **kwargs)
        proof.pop('timestampMs', None)
        return proof
    monkeypatch.setattr(m, 'verify_transfer', without_time)
    api[1][0] = 'teodor'
    d = action(api).json['data']['deals'][0]
    assert d['step'] == 's23'
    assert d['transfer']['sends'][0]['timeUnverified']
    assert 'время' in d['outgoingReview']['candidates'][0]['reason']
    # Общий PUT не может снять запрет на автозакрытие.
    saved = edit(api, 'operator', lambda s,d: d['transfer']['sends'][0].update(timeUnverified=False))
    assert saved['data']['deals'][0]['transfer']['sends'][0]['timeUnverified']
    d = post(api, 'operator', '/api/stand/transfers/check', dealId=1484)['data']['deals'][0]
    assert d['step'] == 's23'
    assert action(api, 'accept', fingerprint=d['outgoingReview']['selectionFingerprint']).json['data']['deals'][0]['step'] == 's26'


def test_b2_rejects_inconsistent_allocation_with_reason(api):
    demo_setup(api, 'company')
    demo_broker(api)
    # Имитируем запрос с разошедшимися фактом и распределением, не меняя БД/пул.
    saved = api[0].get('/api/stand/state').json
    saved['data']['convs'][0]['sources'][0]['usdtFact'] += 3
    d = saved['data']['deals'][0]
    d.update(step='s23', _ippsPayoutInstruction=True,
             transfer={'amount':10130, 'addr':IPPS, 'net':'TRC-20', 'to':'IPPS', 'sends':[]})
    api[1][0] = 'operator'
    response = api[0].put('/api/stand/state', json={'version':saved['version'], 'data':saved['data']})
    assert response.status_code == 409
    assert response.json['error'] == 'Распределение USDT не совпадает с подтверждённым приходом и долями RUB'
    assert api[0].get('/api/stand/state').json['data']['deals'][0]['step'] == 's22'


def test_existing_manual_acceptance_fingerprint_stays_valid():
    import json
    import stand_outgoing_review as review
    d = {'transfer': {'amount':100, 'sends':[{'hash':'legacy', 'status':'confirmed',
        'verifiedAmount':101, 'timestampMs':1700000000000}]},
        'outgoingReview':{'accepted':json.dumps([['legacy','101']])}}
    assert review.complete(d)
    d['transfer']['sends'][0]['timeUnverified'] = True
    assert not review.complete(d), 'Принятие переплаты не разрешает новое исключение по времени'
