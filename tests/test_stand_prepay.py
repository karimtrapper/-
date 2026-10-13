"""Оплата наперёд: две ветки, независимые источники и обязательное возмещение."""

import copy
import json

import pytest

pytestmark = pytest.mark.usefixtures('stand_demo_environment')

import app as m
import stand_prepay
from stand_transfers import expected_addresses

COMPANY = 'TKkeEVf2zySaWTLyX2qPwvi6kcdHRuPxkJ'
FOUNDER = 'TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn'
TEODOR = 'TVmgzMQ2zwV2DVPscBf98WRRdhrcpf5x5p'
IPPS = 'TQgQCBXkewuW4RoieDKFP9Ko2SopBh8jso'


@pytest.mark.parametrize('tariff, expected', [('bank', 10130.01), ('soft', 10200.01)])
def test_prepay_amount_rounds_final_sum_like_freehold_send(tariff, expected):
    assert stand_prepay.amount({'invoiceUsd': 10000.005, 'ippsTariff': tariff}) == expected


def board(step='s18w', incoming='company'):
    d = {'id': 1484, 'code': 'СД-1484', 'client': 'Тест фрихолда', 'step': step,
         'type': 'Оплата недвижимости', 'kind': 'Фрихолд', 'payType': 'По реквизитам',
         'invoiceUsd': 10000, 'ippsTariff': 'bank', 'amountRub': 900000, 'incomeAmount': 900000,
         'walletId': incoming, 'cnvId': 1, 'conv': [], 'rates': {'broker': '80'},
         'payinParts': [{'incId': 1, 'amountRub': 900000}], 'payinHashes': [],
         'pay': {}, 'payout': {}, 'transfer': {}, 'log': [], 'docs': {}, 'demoTransfers': True,
         'reqTask': 'open', 'payTo': {'dev': 'Developer', 'bank': 'Bank', 'swift': 'BANKXX',
                                   'acc': 'SYNTHETIC', 'purpose': 'Invoice', 'amount': 10000}}
    state = {'deals': [d], 'incomes': [{'id': 1, 'dealId': 1484, 'rub': 900000, 'source': 'sber'}],
             'notes': [], 'convs': [{'id': 1, 'walletId': incoming, 'txs': [], 'status': 'sent',
                  'sources': [{'dealId': 1484, 'rub': 900000, 'usdt': 11000}]}],
             'wallets': [{'id': 'company', 'addr': COMPANY, 'multisig': True, 'role': 'findir', 'owner': 'компания'},
                         {'id': 'founder', 'addr': FOUNDER, 'multisig': False, 'role': 'teodor', 'owner': 'Андрей'},
                         {'id': 'teodor', 'addr': TEODOR, 'multisig': False, 'role': 'teodor', 'owner': 'Теодор'}]}
    if step == 's18':
        d.pop('cnvId')
        state['convs'] = []
    return state


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(m, 'STAND_MODE', True)
    monkeypatch.setenv('LOCAL_NO_AUTH', '1')
    monkeypatch.setattr(m, '_stand_deliver_notes', lambda: [])
    role = ['operator']
    monkeypatch.setattr(m, 'current_role', lambda: role[0])
    m._stand_migrate()
    db = m.get_session()
    try:
        user = db.query(m.AdminUser).filter_by(username='prepay_test').first()
        if not user:
            user = m.AdminUser(username='prepay_test', role='admin', password_hash='synthetic')
            db.add(user)
        db.flush()
        uid = user.id
        for address, owner, multi in ((COMPANY, 'компания', True), (FOUNDER, 'Андрей', False), (TEODOR, 'Теодор', False)):
            w = db.query(m.Wallet).filter_by(address=address).first()
            if not w:
                w = m.Wallet(address=address)
                db.add(w)
            w.owner, w.is_multisig, w.active, w.blockchain = owner, multi, True, 'TRON'
        db.commit()
    finally:
        db.close()
    client = m.app.test_client()
    with client.session_transaction() as session:
        session['user_id'] = uid
    return client, role


def seed(state):
    db = m.get_session()
    try:
        row = m._stand_row(db)
        row.data, row.version = json.dumps(state), 1
        db.commit()
    finally:
        db.close()


def start(api, source='founder', step='s18w', incoming='company'):
    seed(board(step, incoming))
    response = api[0].post('/api/stand/prepay', json={
        'action': 'start', 'dealId': 1484, 'walletId': source, 'version': 1})
    assert response.status_code == 200, response.json
    return response.json


def put(api, saved, role):
    api[1][0] = role
    response = api[0].put('/api/stand/state', json={'version': saved['version'], 'data': saved['data']})
    assert response.status_code == 200, response.json
    return response.json


def order(api, saved):
    d = saved['data']['deals'][0]
    d['payToConfirm'] = {'payTo': copy.deepcopy(d['payTo']), 'at': 'confirmed'}
    d['reqTask'] = 'done'
    saved = put(api, saved, 'manager')
    d = saved['data']['deals'][0]
    d.update(step='s23', reqTask='done', _ippsPayoutInstruction=True,
             transfer={'amount': 10130, 'to': 'IPPS', 'addr': IPPS, 'net': 'TRC-20', 'sends': []})
    return put(api, saved, 'operator')


@pytest.mark.parametrize('source', ['founder', 'company'])
@pytest.mark.parametrize('step', ['s18', 's18w'])
def test_start_preserves_broker_and_uses_manager_gate(api, source, step):
    saved = start(api, source, step)
    d = saved['data']['deals'][0]
    assert d['step'] == 's22' and d['prepay']['brokerStep'] == step
    assert not d['payinHashes'] and not d['pay'].get('usdt')
    assert '10130.00' in d['log'][-1]['text']
    assert d['prepay']['wallet']['owner'] == ('Андрей' if source == 'founder' else 'компания')
    assert expected_addresses(saved['data'], d)[0] == (FOUNDER if source == 'founder' else COMPANY)
    forbidden = copy.deepcopy(saved['data'])
    forbidden['deals'][0]['transfer']['sends'] = [{'ref': 'demo:1484:x', 'amount': 10130}]
    assert m._stand_guard_transition(saved['data'], forbidden, 'teodor')
    saved = order(api, saved)
    d = saved['data']['deals'][0]
    assert d['ippsPayoutOrder']['confirmedAt']
    assert m._stand_current_step_role(saved['data'], d) == ('findir' if source == 'company' else 'teodor')
    assert not d['pay'].get('usdt'), 'Источник предоплаты не становится приходом брокера'


@pytest.mark.parametrize('stage', ['s14', 's27'])
def test_no_start_outside_broker_stages(api, stage):
    seed(board(stage))
    r = api[0].post('/api/stand/prepay', json={'action': 'start', 'dealId': 1484, 'walletId': 'founder', 'version': 1})
    assert r.status_code == 409


def test_no_start_without_rub_or_after_broker_usdt(api):
    for change in ('no_rub', 'usdt'):
        state = board()
        if change == 'no_rub':
            state['deals'][0]['payinParts'] = []
        else:
            state['convs'][0]['txs'] = [{'hash': 'a' * 64, 'status': 'confirmed', 'amount': 11000}]
        seed(state)
        r = api[0].post('/api/stand/prepay', json={'action': 'start', 'dealId': 1484, 'walletId': 'founder', 'version': 1})
        assert r.status_code == 409


@pytest.mark.parametrize('instructed', [False, True])
def test_cancel_restores_broker_and_no_debt(api, instructed):
    saved = start(api)
    if instructed:
        saved = order(api, saved)
    api[1][0] = 'operator'
    r = api[0].post('/api/stand/prepay', json={'action': 'cancel', 'dealId': 1484, 'version': saved['version']})
    assert r.status_code == 200, r.json
    d = r.json['data']['deals'][0]
    assert d['step'] == 's18w' and not d.get('prepay') and not d.get('ippsPayoutOrder')
    assert not d.get('paySrc') and not d['payout']


def test_source_amount_and_mode_cannot_be_forged_by_put(api):
    saved = start(api)
    for key, value in (('amount', 1), ('wallet', {}), ('source', 'multisig')):
        forged = copy.deepcopy(saved['data'])
        forged['deals'][0]['prepay'][key] = value
        assert m._stand_guard_transition(saved['data'], forged, 'admin')
    before = board()
    assert m._stand_guard_transition(before, saved['data'], 'operator')


def payout(api, source, incoming='company', saved=None):
    saved = order(api, saved or start(api, source, incoming=incoming))
    d = saved['data']['deals'][0]
    d['transfer']['sends'] = [{'ref': 'demo:1484:out', 'amount': 10130, 'net': 'TRC-20'}]
    saved = put(api, saved, 'findir' if source == 'company' else 'teodor')
    api[1][0] = 'operator'
    r = api[0].post('/api/stand/prepay', json={'action': 'cancel', 'dealId': 1484, 'version': saved['version']})
    assert r.status_code == 409
    if source == 'company':
        saved['data']['deals'][0]['step'] = 's24'
        saved = put(api, saved, 'findir')
    api[1][0] = 'teodor'
    r = api[0].post('/api/stand/transfers/demo', json={'dealId': 1484, 'ref': 'demo:1484:out', 'outcome': 'confirmed'})
    assert r.status_code == 200 and r.json.get('success'), r.json
    saved = r.json
    d = saved['data']['deals'][0]
    assert d['step'] == 's26' and d['prepay']['brokerStep'] in ('s18', 's18w', 'done')
    assert d['serverTransferComplete'] and d['payout']['usdt'] == 10130
    return saved


@pytest.mark.parametrize('source', ['founder', 'company'])
def test_payment_before_broker_then_reimbursement_and_close_gate(api, source):
    saved = payout(api, source)
    state = saved['data']
    d = state['deals'][0]
    assert stand_prepay.close_problem(state, d)
    # Приход вводится отдельным проверенным событием, затем штатный разнос s18w.
    state['convs'][0]['txs'] = [{'hash': 'b' * 64, 'status': 'confirmed', 'amount': 11000, 'net': 'TRC-20'}]
    seed(state)
    saved['version'] = 1
    d['prepay']['brokerStep'] = 'done'
    state['convs'][0]['sources'][0]['usdtFact'] = 11000
    state['convs'][0]['status'] = 'received'
    d['pay'].update(usdt=11000, hash='b' * 64)
    d['payinHashes'] = [{'hash': 'b' * 64, 'amount': 11000, 'network': 'TRC-20'}]
    saved = put(api, saved, 'operator')
    d = saved['data']['deals'][0]
    assert d['step'] == 's26', 'Приход брокера не перезапускает s22'
    assert d['payout']['usdt'] == 10130
    if source == 'founder':
        assert d['paySrc'] == 'founder'
        assert stand_prepay.close_problem(saved['data'], d)
        api[1][0] = 'findir'
        r = api[0].post('/api/stand/prepay/reimburse', json={'dealId': 1484, 'hash': 'demo:1484:return'})
        assert r.status_code == 200, r.json
        d = r.json['data']['deals'][0]
        assert d['payout']['reimbursement']['usdt'] == 10130
        assert d['payout']['usdt'] == 10130 and d['pay']['usdt'] == 11000
        assert stand_prepay.close_problem(r.json['data'], d) is None
    else:
        assert 'кошелёк совпал' in d['payout']['reimbursement']['kind']
        assert d['paySrc'] != 'founder'
        assert stand_prepay.close_problem(saved['data'], d) is None


def test_old_deal_without_prepay_keeps_existing_gates():
    state = board()
    assert stand_prepay.close_problem(state, state['deals'][0]) is None
    assert m._stand_guard_transition(state, copy.deepcopy(state), 'operator') is None


@pytest.mark.parametrize('payment_stage', ['s22', 's23', 's26'])
def test_rubles_can_be_sent_while_manager_or_founder_has_payment_task(api, payment_stage):
    saved = start(api, step='s18')
    if payment_stage == 's23':
        saved = order(api, saved)
    elif payment_stage == 's26':
        saved = payout(api, 'founder', saved=saved)
    # Курс и кошелёк можно готовить у операциониста, пока задача оплаты у другой роли.
    saved['data']['deals'][0]['brokerDraft'] = '80'
    saved = put(api, saved, 'operator')
    d = saved['data']['deals'][0]
    d.update(cnvId=1, brokerDraft=None, brokerPick=None)
    d['prepay']['brokerStep'] = 's18w'
    saved['data']['convs'] = [{'id': 1, 'walletId': 'company', 'broker': 'Брокер',
        'rate': '80', 'status': 'sent', 'at': '12.10, 12:00', 'requestNo': 'TEST', 'sentTs': 1700000000000,
        'rubTotal': 900000, 'sent': 897260, 'held': 2740, 'feeCtrl': 940, 'feeOurs': 1800,
        'feePct': .3, 'feeFix': 40, 'feeCtrlPct': .1, 'feeOursPct': .2,
        'sources': [{'dealId': 1484, 'rub': 900000, 'usdt': 11215.75}], 'txs': []}]
    saved = put(api, saved, 'operator')
    assert saved['data']['deals'][0]['step'] == payment_stage
    assert saved['data']['deals'][0]['prepay']['brokerStep'] == 's18w'


def test_broker_receipt_can_arrive_before_payment_instruction(api):
    saved = start(api)
    saved['data']['convs'][0]['txs'] = [{'hash': 'b' * 64, 'status': 'confirmed', 'amount': 11000, 'net': 'TRC-20'}]
    seed(saved['data'])
    saved['version'] = 1
    d = saved['data']['deals'][0]
    d['prepay']['brokerStep'] = 'done'
    d['pay'].update(usdt=11000, hash='b' * 64)
    d['payinHashes'] = [{'hash': 'b' * 64, 'amount': 11000, 'network': 'TRC-20'}]
    saved['data']['convs'][0]['sources'][0]['usdtFact'] = 11000
    saved = put(api, saved, 'operator')
    saved = order(api, saved)
    assert saved['data']['deals'][0]['prepay']['brokerStep'] == 'done'


def test_stale_launch_and_wrong_roles_are_rejected(api):
    saved = start(api)
    for actor, version, expected in [('manager', saved['version'], 403), ('operator', 1, 409)]:
        api[1][0] = actor
        r = api[0].post('/api/stand/prepay', json={'action': 'cancel', 'dealId': 1484, 'version': version})
        assert r.status_code == expected


def test_no_close_before_broker_receipt_even_with_paid_invoice(api):
    saved = payout(api, 'company')
    d = saved['data']['deals'][0]
    d.update(step='s27', sentToClient=True)
    d['pay']['invoicePaid'] = True
    d['files'] = {'receipt': [{'file': 'receipt.pdf', 'mime': 'application/pdf',
                             'data': 'data:application/pdf;base64,JVBERi0='}]}
    seed(saved['data'])
    api[1][0] = 'manager'
    r = api[0].post('/api/stand/deals/1484/crm-close', json={'version': 1, 'crm': {}})
    assert r.status_code == 409
    assert 'USDT брокера' in r.json['error'], r.json


def test_second_signature_and_payto_confirmation_are_not_bypassed(api):
    saved = order(api, start(api, 'company'))
    d = saved['data']['deals'][0]
    d['transfer']['sends'] = [{'ref': 'demo:1484:out', 'amount': 10130, 'net': 'TRC-20'}]
    saved = put(api, saved, 'findir')
    r = api[0].post('/api/stand/transfers/demo', json={'dealId': 1484, 'ref': 'demo:1484:out', 'outcome': 'confirmed'})
    assert r.status_code == 409 and 'вторая подпись' in r.json['error']
    api[1][0] = 'operator'
    saved = payout(api, 'founder')
    saved['data']['deals'][0].pop('payToConfirm', None)
    forged = copy.deepcopy(saved['data'])
    forged['deals'][0]['step'] = 's27'
    forged['deals'][0]['pay']['invoicePaid'] = True
    forged['deals'][0].pop('payToConfirm', None)
    assert 'подтверждения реквизитов' in m._stand_guard_transition(saved['data'], forged, 'operator')


def receive(api, saved, amount=11000):
    # Синтетическое подтверждение сети; переход и распределение проходят реальный PUT.
    state = saved['data']
    state['convs'][0]['txs'] = [{'hash': 'b' * 64, 'status': 'confirmed', 'amount': amount, 'net': 'TRC-20'}]
    seed(state)
    saved['version'] = 1
    d = state['deals'][0]
    d['prepay']['brokerStep'] = 'done'
    state['convs'][0]['sources'][0]['usdtFact'] = amount
    state['convs'][0]['status'] = 'received'
    d['pay'].update(usdt=amount, hash='b' * 64)
    d['payinHashes'] = [{'hash': 'b' * 64, 'amount': amount, 'network': 'TRC-20'}]
    return put(api, saved, 'operator')


@pytest.mark.parametrize('source', ['founder', 'teodor', 'company'])
@pytest.mark.parametrize('incoming', ['founder', 'teodor', 'company'])
@pytest.mark.parametrize('broker_first', [False, True])
def test_wallet_matrix_and_both_completion_orders(api, source, incoming, broker_first):
    saved = start(api, source, incoming=incoming)
    if broker_first:
        saved = receive(api, saved)
        assert not saved['data']['deals'][0]['payout'].get('reimbursement')
    saved = payout(api, source, incoming, saved)
    if not broker_first:
        saved = receive(api, saved)
    d = saved['data']['deals'][0]
    if source == incoming:
        assert 'кошелёк совпал' in d['payout']['reimbursement']['kind']
        assert d['payout']['reimbursement']['usdt'] == 10130
        assert stand_prepay.close_problem(saved['data'], d) is None
    else:
        assert not d['payout'].get('reimbursement')
        assert stand_prepay.close_problem(saved['data'], d)
        api[1][0] = 'findir' if incoming == 'company' else 'teodor'
        r = api[0].post('/api/stand/prepay/reimburse', json={'dealId': 1484, 'hash': 'demo:1484:refund'})
        assert r.status_code == 200, r.json
        d = r.json['data']['deals'][0]
        assert d['payout']['reimbursement']['usdt'] == 10130
        assert stand_prepay.close_problem(r.json['data'], d) is None
        retry = api[0].post('/api/stand/prepay/reimburse', json={'dealId': 1484, 'hash': 'demo:1484:refund'})
        assert retry.json['version'] == r.json['version']
    assert d['payout']['usdt'] == 10130 and d['pay']['usdt'] == 11000
    assert d['paySrc'] == ('ipps_swift' if source == 'company' else 'founder')


def test_reimbursement_cannot_be_forged_or_reuse_payin_or_outgoing(api):
    saved = receive(api, payout(api, 'founder'))
    forged = copy.deepcopy(saved['data'])
    forged['deals'][0]['payout']['reimbursement'] = {'hash': 'fake'}
    assert 'только сервер' in m._stand_guard_transition(saved['data'], forged, 'admin')
    api[1][0] = 'findir'
    for ref in ('b' * 64, 'demo:1484:out'):
        r = api[0].post('/api/stand/prepay/reimburse', json={'dealId': 1484, 'hash': ref})
        assert r.status_code == 409 and 'уже учтён' in r.json['error']
    forged = copy.deepcopy(saved['data'])
    forged['wallets'][0]['addr'] = FOUNDER
    assert m._stand_guard_transition(saved['data'], forged, 'admin')


@pytest.mark.parametrize('amount', [10000, 11000])
def test_reimbursement_does_not_hide_broker_difference(api, amount):
    saved = receive(api, payout(api, 'founder'), amount)
    api[1][0] = 'findir'
    r = api[0].post('/api/stand/prepay/reimburse', json={'dealId': 1484, 'hash': 'demo:1484:refund'})
    assert r.status_code == 200, r.json
    d = r.json['data']['deals'][0]
    assert d['payout']['reimbursement']['usdt'] == d['payout']['usdt'] == 10130
    assert d['pay']['usdt'] == amount


@pytest.mark.parametrize('result', ['confirmed', 'pending', 'wrong', 'old', 'race'])
def test_real_reimbursement_checks_exact_wallets_and_rejects_unverified_or_stale(api, monkeypatch, result):
    saved = receive(api, payout(api, 'company', incoming='founder'))
    saved['data']['deals'][0]['demoTransfers'] = False
    seed(saved['data'])
    def verify(ref, network, sender, receiver, amount, **kwargs):
        assert (network, sender, receiver, amount) == ('trc20', FOUNDER, COMPANY, 10130)
        assert kwargs['demo'] is False
        if result == 'race':
            db = m.get_session()
            try:
                m._stand_row(db).version += 1
                db.commit()
            finally:
                db.close()
        return {'status': 'pending' if result == 'pending' else 'mismatch' if result == 'wrong' else 'confirmed',
                'verifiedAmount': 10130, 'timestampMs': 1 if result == 'old' else m.time.time() * 1000}
    monkeypatch.setattr(m, 'verify_transfer', verify)
    api[1][0] = 'teodor'
    r = api[0].post('/api/stand/prepay/reimburse', json={'dealId': 1484, 'hash': 'c' * 64})
    assert r.status_code == (200 if result == 'confirmed' else 409), r.json
    if result != 'confirmed':
        current = api[0].get('/api/stand/state').json['data']['deals'][0]
        assert not current['payout'].get('reimbursement')


def test_same_address_different_legacy_wallet_ids_auto_settle(api):
    saved = payout(api, 'founder', incoming='founder')
    state = saved['data']
    state['wallets'].append(dict(state['wallets'][1], id='legacy-andrey'))
    state['convs'][0]['walletId'] = 'legacy-andrey'
    state['deals'][0]['walletId'] = 'legacy-andrey'
    saved = receive(api, saved)
    assert 'кошелёк совпал' in saved['data']['deals'][0]['payout']['reimbursement']['kind']


def test_prepayment_does_not_wait_for_another_deal_in_broker_batch(api):
    saved = start(api)
    state = saved['data']
    side = copy.deepcopy(board()['deals'][0])
    side.update(id=1485, code='СД-1485', type='Обмен валюты', kind='', step='pack', main=1484,
                payinParts=[{'incId': 2, 'amountRub': 900000}])
    state['deals'].append(side)
    state['incomes'].append({'id': 2, 'dealId': 1485, 'rub': 900000, 'source': 'sber'})
    state['convs'][0]['sources'].append({'dealId': 1485, 'rub': 900000, 'usdt': 11000})
    seed(state)
    saved['version'] = 1
    saved = payout(api, 'founder', saved=saved)
    assert saved['data']['deals'][0]['step'] == 's26'
    assert saved['data']['deals'][1]['step'] == 'pack'
    assert not saved['data']['convs'][0]['txs']
    state = saved['data']
    state['convs'][0]['txs'] = [{'hash': 'b' * 64, 'status': 'confirmed', 'amount': 22000, 'net': 'TRC-20'}]
    seed(state)
    saved['version'] = 1
    state['convs'][0]['status'] = 'received'
    for d, src in zip(state['deals'], state['convs'][0]['sources']):
        src['usdtFact'] = 11000
        d['pay'].update(usdt=11000, hash='b' * 64)
        d['payinHashes'] = [{'hash': 'b' * 64, 'amount': 11000, 'network': 'TRC-20'}]
    state['deals'][0]['prepay']['brokerStep'] = 'done'
    state['deals'][1]['step'] = 's22'
    saved = put(api, saved, 'operator')
    assert saved['data']['deals'][0]['step'] == 's26'
    assert saved['data']['deals'][1]['step'] == 's22'


@pytest.mark.parametrize('source', ['founder', 'company'])
@pytest.mark.parametrize('received_usdt', [10000, 11000], ids=['partial_loss', 'full_profit'])
def test_actual_crm_close_requires_all_results_and_preserves_profit(api, source, received_usdt):
    saved = receive(api, payout(api, source), received_usdt)
    if source == 'founder':
        api[1][0] = 'findir'
        saved = api[0].post('/api/stand/prepay/reimburse', json={
            'dealId': 1484, 'hash': 'demo:1484:refund'}).json
    state = saved['data']
    d = state['deals'][0]
    # Даже при недоборе брокера возвращается весь расход IPPS, а не сумма прихода.
    assert d['payout']['usdt'] == 10130
    assert d['payout']['reimbursement']['usdt'] == 10130
    assert d['pay']['usdt'] == received_usdt
    d.update(step='s27', sentToClient=True)
    d['pay']['invoicePaid'] = True
    d['files'] = {'receipt': [{'file': 'receipt.pdf', 'mime': 'application/pdf',
                             'data': 'data:application/pdf;base64,JVBERi0='}]}
    seed(state)
    # Здесь проверяем атомарное закрытие; проверка самого MT103 имеет отдельные тесты.
    db = m.get_session()
    try:
        row = m._stand_row(db)
        row.generation = m.secrets.token_hex(16)
        with api[0].session_transaction() as session:
            uid = session['user_id']
        for kind in m._stand_close_required(d):
            db.add(m.StandCloseEvidence(generation=row.generation, stand_deal_id=1484,
                kind=kind, fingerprint=m._stand_close_fingerprint(d, kind),
                actor_id=uid, provenance='synthetic_preverified_fixture'))
        db.commit()
    finally:
        db.close()
    crm = {'client_name': 'Synthetic prepay', 'deal_kind': 'mf_freehold',
           'payin_method': 'sber_reqs', 'payin_rate_rub_usdt': 80,
           'payin_amount_rub': 900000, 'payin_amount_usdt': received_usdt,
           'invoice_amount_usd': 10000, 'transfer_fee_percent': .8,
           'transfer_fee_fixed_usd': 50, 'transfer_sent_usd': 10130,
           'realty_purpose': 'Invoice',
           'payin_tx_hashes': [{'hash': 'b' * 64, 'network': 'trc20', 'amount_usdt': received_usdt}],
           'payout_tx_hashes': [{'hash': 'demo:1484:out', 'network': 'trc20', 'amount_usdt': 10130}]}
    api[1][0] = 'manager'
    for missing in ('receipt', 'invoice', 'sent', 'refund'):
        broken = copy.deepcopy(state)
        target = broken['deals'][0]
        if missing == 'receipt':
            target['files'] = {}
        elif missing == 'invoice':
            target['pay']['invoicePaid'] = False
        elif missing == 'sent':
            target['sentToClient'] = False
        else:
            target['payout'].pop('reimbursement')
        seed(broken)
        r = api[0].post('/api/stand/deals/1484/crm-close', json={'version': 1, 'crm': crm})
        assert r.status_code == 409, r.json
    seed(state)
    r = api[0].post('/api/stand/deals/1484/crm-close', json={'version': 1, 'crm': crm})
    assert r.status_code == 201, r.json
    assert r.json['deal']['profit_usdt'] == received_usdt - 10130
    again = api[0].post('/api/stand/deals/1484/crm-close', json={'version': 1, 'crm': crm})
    assert again.status_code == 200 and again.json['duplicate']
