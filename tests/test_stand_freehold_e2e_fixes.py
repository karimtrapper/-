"""Блокеры сквозного фрихолда: регрессии сначала воспроизводятся на stage."""
import copy

import pytest

pytestmark = pytest.mark.usefixtures('stand_demo_environment')
import app as m
from tests.test_stand_outgoing_review import api as base_api, network, setup_send, action, tx
from tests.test_stand_prepay import seed, start, payout, put, COMPANY, TEODOR

@pytest.fixture
def api(base_api):
    db = m.get_session()
    try:
        row = m._stand_row(db)
        before = (row.data, row.version, row.generation)
    finally:
        db.close()
    yield base_api
    db = m.get_session()
    try:
        row = m._stand_row(db)
        row.data, row.version, row.generation = before
        db.commit()
    finally:
        db.close()


RECEIPT = {'file': 'receipt.pdf', 'mime': 'application/pdf',
           'data': 'data:application/pdf;base64,JVBERi0='}


def paid(api, network, prepay=False):
    state = setup_send(api, prepay=prepay)
    state['deals'][0]['amountUsdt'] = 11000
    seed(state)
    network.append(tx(1, 10130))
    api[1][0] = 'teodor'
    response = action(api)
    assert response.status_code == 200, response.json
    return response.json


def test_null_payout_settles_via_network_api(api, network):
    state = setup_send(api, prepay=False)
    state['deals'][0]['payout'] = None
    seed(state)
    network.append(tx(1, 10130))
    api[1][0] = 'teodor'
    result = action(api)
    assert result.status_code == 200, result.json
    assert result.json['data']['deals'][0]['payout']['usdt'] == 10130
    assert result.json['data']['deals'][0]['step'] == 's26'


def mt103(saved, source='ipps_swift'):
    d = saved['data']['deals'][0]
    d.update(step='s27', paySrc=source)
    d['pay']['invoicePaid'] = True
    d['docs']['receipt'] = True
    d['files'] = {'receipt': [RECEIPT]}
    d['payout'].update(source='IPPS (SWIFT)', method='IPPS · SWIFT в USD',
                       invoice={'source': 'IPPS (SWIFT)', 'usd': d['invoiceUsd'], 'to': 'Developer'})
    return saved


def test_first_same_route_paysrc_on_mt103(api, network):
    saved = mt103(paid(api, network))
    result = put(api, saved, 'operator')
    assert result['data']['deals'][0]['step'] == 's27'


@pytest.mark.parametrize('actor', ['operator', 'admin'])
@pytest.mark.parametrize('field,value', [('walletId', 'teodor'), ('conv', [1475])])
def test_broker_draft_after_payment_is_independent(api, actor, field, value):
    saved = payout(api, 'founder', saved=start(api, step='s18'))
    # Дополнительный обмен уже есть на доске, выбирается только в черновик пачки.
    saved['data']['deals'].append({'id': 1475, 'step': 'done', 'closed': True,
        'type': 'Обмен валюты', 'amountRub': 1000, 'conv': []})
    seed(saved['data'])
    saved = api[0].get('/api/stand/state').json
    saved['data']['deals'][0][field] = value
    result = put(api, saved, actor)
    assert result['data']['deals'][0]['step'] == 's26'
    assert result['data']['deals'][0]['prepay']['brokerStep'] == 's18'


def test_confirmed_legacy_send_missing_addresses_is_reverified(api, network):
    saved = paid(api, network)
    d = saved['data']['deals'][0]
    # Снимок старого подтверждения, непригодного для ворот закрытия.
    d['transfer']['sends'][0].pop('from')
    d['transfer']['sends'][0].pop('to')
    seed(saved['data'])
    api[1][0] = 'operator'
    result = api[0].post('/api/stand/transfers/check', json={'dealId': 1484})
    assert result.status_code == 200, result.json
    d = result.json['data']['deals'][0]
    assert d['transfer']['sends'][0].get('from') == TEODOR
    assert d['transfer']['sends'][0].get('to') == d['transfer']['addr']
    assert m._stand_close_fact_source(result.json['data'], d, 'payout') == ('verified_network', None)


def test_reverify_legacy_send_keeps_other_operation_hash_claim(api, network):
    saved = paid(api, network)
    send = saved['data']['deals'][0]['transfer']['sends'][0]
    send.pop('from')
    send.pop('to')
    saved['data']['deals'].append({'id': 99, 'step': 'done', 'closed': True,
        'payinHashes': [{'hash': f'{1:064x}', 'amount': 10130}]})
    seed(saved['data'])
    result = post(api, 'operator', '/api/stand/transfers/check', dealId=1484)
    d = result['data']['deals'][0]
    assert d['transfer']['sends'][0]['status'] == 'mismatch'
    assert m._stand_close_fact_source(result['data'], d, 'payout')[1] == 'network_payout_proof_missing'


def test_personal_manual_hash_gets_addresses_from_real_verifier(api, chain):
    import time
    setup_send(api, prepay=False)
    api[1][0] = 'teodor'
    assert action(api).status_code == 200
    chain.append(tx(902, 10130, ts=int(time.time()*1000)+1000))
    edit(api, 'operator', lambda s,d: d['transfer'].update(sends=[{
        'ref': chain.ref(902), 'amount': 10130, 'net': 'TRC-20'}]))
    result = post(api, 'operator', '/api/stand/transfers/check', dealId=1484)
    d = result['data']['deals'][0]
    assert d['step'] == 's26'
    assert d['transfer']['sends'][0]['from'] == TEODOR
    assert d['transfer']['sends'][0]['to'] == d['transfer']['addr']
    assert m._stand_close_fact_source(result['data'], d, 'payout') == ('verified_network', None)


@pytest.fixture
def chain(monkeypatch):
    """Меняется только ответ сети; verify_transfer и HTTP-переходы настоящие."""
    import stand_egress
    from stand_transfer_discovery import USDT_TRC20
    monkeypatch.setenv('STAND_MODE', '1')
    class Chain(list):
        prefix = int(m.secrets.token_hex(16), 16)
        def ref(self, number):
            return f'{self.prefix + number:064x}'
        def append(self, row):
            row['transaction_id'] = self.ref(int(row['transaction_id'], 16))
            super().append(row)
    rows = Chain()
    def read(operation, params):
        if operation == 'tron_trc20_transfers':
            return 200, {'token_transfers': sorted(rows, key=lambda t: -t['block_ts']), 'total': len(rows)}, None
        assert operation == 'tron_tx_info', operation
        row = next((t for t in rows if t['transaction_id'] == params['hash']), None)
        if not row:
            return 404, {}, None
        return 200, {'hash': row['transaction_id'], 'confirmed': True, 'contractRet': 'SUCCESS',
            'revert': False, 'timestamp': row['block_ts'], 'trc20TransferInfo': [{
                'contract_address': USDT_TRC20, 'from_address': row['from_address'],
                'to_address': row['to_address'], 'amount_str': row['quant'], 'decimals': 6}]}, None
    monkeypatch.setattr(stand_egress, 'read_get', read)
    return rows


def initial_board(api, invoice=10000, rub=900000):
    from tests.test_stand_prepay import board
    state = board('s18')
    d = state['deals'][0]
    d.update(step='s14', payout=None, demoTransfers=False, invoiceUsd=invoice,
             incomeAmount=None, payinParts=[], amountRub=rub, rubReceivingAccount={'mode': 'sber'},
             source='none', originMode='workflow', originStep='s4', postConv=None)
    d['payTo']['amount'] = invoice
    state['incomes'][0].update(dealId=None, rub=rub)
    seed(state)
    # Однократная загрузка начального снимка; далее только API ролей.
    db = m.get_session()
    try:
        m._stand_row(db).generation = m.secrets.token_hex(16)
        db.commit()
    finally:
        db.close()
    return api[0].get('/api/stand/state').json


def edit(api, actor, change):
    saved = api[0].get('/api/stand/state').json
    change(saved['data'], saved['data']['deals'][0])
    return put(api, saved, actor)


def post(api, actor, path, **payload):
    api[1][0] = actor
    response = api[0].post(path, json=payload)
    assert response.status_code in (200, 201), (path, response.status_code, response.json)
    return response.json


def prepare_after_rub(api):
    def arrived(s, d):
        rub = d['amountRub']
        d.update(step='s15', incomeAmount=rub, payinParts=[{'incId': 1, 'amountRub': rub}])
        s['incomes'][0]['dealId'] = d['id']
    edit(api, 'operator', arrived)
    def requisites(s, d):
        d.update(step='s18', reqTask='done', payToConfirm={'payTo': dict(d['payTo']), 'at': 'confirmed'})
    return edit(api, 'manager', requisites)


def send_broker(api, wallet='company'):
    import time
    def handoff(s, d):
        rub = d['incomeAmount']; rate = float(d['rates']['broker'])
        held = round(rub * .003 + 40, 2); sent = rub - held
        d.update(cnvId=1, walletId=wallet)
        if d.get('prepay'):
            d['prepay']['brokerStep'] = 's18w'
        else:
            d['step'] = 's18w'
        s['convs'] = [{'id': 1, 'walletId': wallet, 'broker': 'Synthetic broker',
            'rate': str(rate), 'status': 'sent', 'at': '13.10, 12:00', 'requestNo': 'TEST',
            'sentTs': int(time.time()*1000), 'rubTotal': rub, 'sent': sent, 'held': held,
            'feeCtrl': round(rub*.001+40, 2), 'feeOurs': round(rub*.002, 2),
            'feePct': .3, 'feeFix': 40, 'feeCtrlPct': .1, 'feeOursPct': .2,
            'sources': [{'dealId': d['id'], 'rub': rub, 'usdt': round(sent/rate, 2)}], 'txs': []}]
        s['incomes'][0]['cnvId'] = 1
    return edit(api, 'operator', handoff)


def receive_broker(api, chain, amount=11000):
    import time
    from tests.test_stand_prepay import FOUNDER
    chain.append(tx(901, amount, sender=FOUNDER, to=COMPANY, ts=int(time.time()*1000)+1000))
    post(api, 'operator', '/api/stand/incoming/check', dealId=1484, hash=chain.ref(901), network='TRC-20')
    def receive(s, d):
        s['convs'][0]['sources'][0]['usdtFact'] = amount
        s['convs'][0]['status'] = 'received'
        d['pay'].update(usdt=amount, hash=chain.ref(901))
        d['payinHashes'] = [{'hash': chain.ref(901), 'amount': amount, 'net': 'TRC-20'}]
        if d.get('prepay'):
            d['prepay']['brokerStep'] = 'done'
        else:
            d.update(step='s22', postConv='ipps_swift')
    return edit(api, 'operator', receive)


def ipps_order(api, address):
    import stand_prepay
    def confirm(s, d):
        d['payToConfirm'] = {'payTo': dict(d['payTo']), 'at': 'confirmed'}
        d['reqTask'] = 'done'
    edit(api, 'manager', confirm)
    def instruct(s, d):
        d.update(step='s23', _ippsPayoutInstruction=True, postConv='ipps_swift',
                 transfer={'amount': stand_prepay.amount(d), 'addr': address,
                           'net': 'TRC-20', 'to': 'IPPS', 'sends': []})
    return edit(api, 'operator', instruct)


def send_ipps(api, chain, personal):
    import time
    d = api[0].get('/api/stand/state').json['data']['deals'][0]
    chain.append(tx(902, d['transfer']['amount'], sender=d['prepay']['wallet']['addr'] if personal else COMPANY,
                    to=d['transfer']['addr'], ts=int(time.time()*1000)+1000))
    if personal:
        api[1][0] = 'teodor'
        result = action(api)
        assert result.status_code == 200, result.json
        saved = result.json
    else:
        def register(s, d):
            d['transfer']['sends'] = [{'ref': chain.ref(902), 'amount': d['transfer']['amount'], 'net': 'TRC-20'}]
            d['step'] = 's24'
        edit(api, 'findir', register)
        saved = post(api, 'teodor', '/api/stand/transfers/check', dealId=1484)
    assert saved['data']['deals'][0]['step'] == 's26', saved['data']['deals'][0]
    return saved


def close_via_roles(api):
    saved = api[0].get('/api/stand/state').json
    d = saved['data']['deals'][0]
    # Тот же s26: источник добавляется только если его ещё не записала предоплата.
    source = d.get('paySrc') or 'ipps_swift'
    mt103(saved, source)
    if d.get('prepay'):
        d['payout']['source'] = d['prepay']['wallet']['name']
    put(api, saved, 'operator')
    edit(api, 'manager', lambda s, d: d.update(sentToClient=True, sentAt='13.10'))
    evidence = '/api/stand/deals/1484/close-evidence'
    for kind, role in [('payin', 'manager'), ('payout', 'manager'), ('receipt', 'operator'), ('sent', 'manager')]:
        version = api[0].get('/api/stand/state').json['version']
        post(api, role, evidence, version=version, kind=kind)
    saved = api[0].get('/api/stand/state').json
    d = saved['data']['deals'][0]
    assert api[0].get(evidence).json['missing'] == []
    crm = {'client_name': d['client'], 'deal_kind': 'mf_freehold', 'payin_method': 'sber_reqs',
        'payin_rate_rub_usdt': float(d['rates']['broker']), 'payin_amount_rub': d['incomeAmount'],
        'payin_amount_usdt': d['pay']['usdt'], 'invoice_amount_usd': d['invoiceUsd'],
        'transfer_fee_percent': .8, 'transfer_fee_fixed_usd': 50, 'transfer_sent_usd': d['payout']['usdt'],
        'realty_purpose': d['payTo']['purpose'],
        'payin_tx_hashes': [{'hash': h['hash'], 'network': 'trc20', 'amount_usdt': h['amount']} for h in d['payinHashes']],
        'payout_tx_hashes': [{'hash': h['hash'], 'network': 'trc20', 'amount_usdt': h['amount']} for h in d['payout']['hashes']]}
    closed = post(api, 'manager', '/api/stand/deals/1484/crm-close', version=saved['version'], crm=crm)
    assert closed['data']['deals'][0]['closed']
    assert closed['data']['deals'][0]['crmDealId']
    return closed


@pytest.mark.parametrize('prepay', [False, True], ids=['sequential_multisig', 'prepay_teodor_refund'])
def test_full_freehold_s14_to_crm_via_api_only(api, chain, prepay, monkeypatch):
    monkeypatch.delenv('STAND_ALLOW_DEMO', raising=False)
    from tests.test_stand_prepay import IPPS
    initial_board(api)
    saved = prepare_after_rub(api)
    if prepay:
        post(api, 'operator', '/api/stand/prepay', action='start', dealId=1484,
             walletId='teodor', version=saved['version'])
    else:
        send_broker(api)
        receive_broker(api, chain)
    ipps_order(api, IPPS)
    send_ipps(api, chain, personal=prepay)
    if prepay:
        send_broker(api)
        receive_broker(api, chain)
        import time
        chain.append(tx(903, 10130, sender=COMPANY, to=TEODOR, ts=int(time.time()*1000)+1000))
        refunded = post(api, 'findir', '/api/stand/prepay/reimburse', dealId=1484, hash=chain.ref(903))
        assert refunded['data']['deals'][0]['payout']['reimbursement']['usdt'] == 10130
    closed = close_via_roles(api)
    assert closed['deal']['net_profit_usdt'] == 870


@pytest.mark.parametrize('change', ['other_source', 'other_route', 'no_receipt', 'stale_payto', 'manager', 'existing_source'])
def test_mt103_source_exception_does_not_unlock_route(api, network, change):
    saved = paid(api, network)
    if change == 'existing_source':
        saved['data']['deals'][0]['paySrc'] = 'founder'
        seed(saved['data'])
        saved = api[0].get('/api/stand/state').json
    saved = mt103(saved)
    d = saved['data']['deals'][0]
    actor = 'operator'
    if change == 'other_source': d['paySrc'] = 'cash'
    if change == 'other_route': d['postConv'] = 'client'
    if change == 'no_receipt': d['files'] = {}
    if change == 'stale_payto': d['payTo']['acc'] = 'other'
    if change == 'manager': actor = 'manager'
    api[1][0] = actor
    response = api[0].put('/api/stand/state', json={'version': saved['version'], 'data': saved['data']})
    assert response.status_code == 409, response.json


@pytest.mark.parametrize('actor', ['manager', 'findir', 'teodor'])
def test_broker_draft_does_not_open_other_roles(api, actor):
    saved = payout(api, 'founder', saved=start(api, step='s18'))
    saved['data']['deals'][0]['walletId'] = 'teodor'
    api[1][0] = actor
    response = api[0].put('/api/stand/state', json={'version': saved['version'], 'data': saved['data']})
    assert response.status_code == 409


def test_broker_draft_cannot_change_paid_ipps_recipient(api):
    saved = payout(api, 'founder', saved=start(api, step='s18'))
    d = saved['data']['deals'][0]
    d['walletId'] = 'teodor'
    d['transfer']['addr'] = COMPANY
    api[1][0] = 'operator'
    response = api[0].put('/api/stand/state', json={'version': saved['version'], 'data': saved['data']})
    assert response.status_code == 409


def test_missing_network_proof_cannot_be_repaired_by_guess(api, network):
    saved = paid(api, network)
    d = saved['data']['deals'][0]
    d['transfer']['sends'][0].pop('from')
    d['transfer']['sends'][0].pop('to')
    seed(saved['data'])
    network.clear()
    api[1][0] = 'operator'
    result = api[0].post('/api/stand/transfers/check', json={'dealId': 1484})
    d = result.json['data']['deals'][0]
    assert not d['transfer']['sends'][0].get('from')
    assert m._stand_close_fact_source(result.json['data'], d, 'payout')[1] == 'network_payout_proof_missing'


@pytest.mark.parametrize('role', ['manager', 'operator', 'admin'])
def test_four_close_evidence_roles(api, network, role):
    saved = paid(api, network)
    saved = put(api, mt103(saved), 'operator')
    edit(api, 'manager', lambda s, d: d.update(sentToClient=True))
    api[1][0] = role
    for kind in ['payin', 'payout', 'receipt', 'sent']:
        version = api[0].get('/api/stand/state').json['version']
        response = api[0].post('/api/stand/deals/1484/close-evidence', json={'kind': kind, 'version': version})
        allowed = role == 'admin' or (role == 'operator') == (kind == 'receipt')
        assert response.status_code == (200 if allowed else 403), (role, kind, response.json)


def test_live_1484_snapshot_s23_to_close_via_api_only(api, chain, monkeypatch):
    monkeypatch.delenv('STAND_ALLOW_DEMO', raising=False)
    import json, time
    from pathlib import Path
    state = json.loads((Path(__file__).parent/'fixtures/stand_1484_s23_anonymized.json').read_text())
    assert state['snapshotVersion'] == 1101
    d = state['deals'][0]
    assert d['step'] == 's23' and d['prepay']['brokerStep'] == 's18'
    assert d['prepay']['source'] == 'founder' and d['prepay']['wallet']['multisig'] is False
    assert d['transfer']['amount'] == 5507.16 and d['invoiceUsd'] == 5413.85
    assert d['payout'] is None and not d.get('payToConfirm')
    seed(state)
    db = m.get_session()
    try:
        m._stand_row(db).generation = m.secrets.token_hex(16)
        db.commit()
    finally:
        db.close()
    # Старой заявке требуется штатное подтверждение менеджера, без исправления БД.
    edit(api, 'manager', lambda s,d: d.update(payToConfirm={'payTo': dict(d['payTo']), 'at': 'confirmed'}))
    send_ipps(api, chain, personal=True)
    # Будущие ответы брокера и сети синтетические; сохранённые деньги не переписываются.
    edit(api, 'operator', lambda s,d: d['rates'].update(broker='85.6'))
    send_broker(api, wallet='grusha')
    receive_broker(api, chain, amount=5800)
    chain.append(tx(903, 5507.16, sender=COMPANY, to=d['prepay']['wallet']['addr'], ts=int(time.time()*1000)+1000))
    result = post(api, 'findir', '/api/stand/prepay/reimburse', dealId=1484, hash=chain.ref(903))
    assert result['data']['deals'][0]['payout']['reimbursement']['usdt'] == 5507.16
    closed = close_via_roles(api)
    assert closed['deal']['net_profit_usdt'] == 292.84
