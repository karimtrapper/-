"""A manager may reprice before broker/outgoing commitment, retaining client credit."""
import base64
import copy
import io
import subprocess

import pytest

from tests.test_t29_step_role import board


def put(client, mutate):
    current = client.get('/api/stand/state').json
    proposed = copy.deepcopy(current['data'])
    mutate(proposed)
    return client.put('/api/stand/state', json={'version': current['version'], 'data': proposed})


def rerate(state, target='s5'):
    deal = state['deals'][0]
    deal['step'] = target
    deal['ratesPrev'] = deal.get('rates') or {}
    deal['rates'] = {}
    deal['quotes'] = []
    deal['ratePick'] = {}
    deal['reRequest'] = (deal.get('reRequest') or 0) + 1
    if target == 's6':
        deal['self'] = True


@pytest.mark.parametrize('step', ['s6', 's8', 's11', 's11b', 's12', 's14', 's14m', 's15', 's18'])
def test_manager_can_rerate_each_pre_broker_step(board, step):
    install, clients = board
    install(step, {'pair': 'RUB → USDT', 'rates': {'rubUsdt': '85', 'client': '90'},
                   'quotes': [{'dir': 'rub', 'rate': '85', 'cpId': 'broker'}],
                   'docVersion': 2, 'docPack': {'version': 2},
                   'docsIssued': [{'version': 2, 'kind': 'bill', 'docId': 20}]})
    response = put(clients('manager'), rerate)
    assert response.status_code == 200, response.json
    deal = response.json['data']['deals'][0]
    assert deal['step'] == 's5' and deal['reRequest'] == 1
    assert deal['docVersion'] == 2 and deal['docsIssued'][0]['docId'] == 20
    assert deal['rerateDocVersion'] == 2


def test_s12_rerate_without_client_money_and_fresh_quote_handoff(board):
    install, clients = board
    install('s12', {'pair': 'RUB → USDT', 'rates': {'rubUsdt': '85', 'client': '90'},
                    'ratePick': {'rub': 'broker'},
                    'docVersion': 1, 'docPack': {'version': 1},
                    'docsIssued': [{'version': 1, 'kind': 'bill', 'docId': 20}]},
            {'cps': [{'id': 'broker', 'name': 'Synthetic Broker', 'dirs': ['rub']}]})
    manager = clients('manager')
    reset = put(manager, rerate)
    assert reset.status_code == 200, reset.json
    assert reset.json['data']['deals'][0]['step'] == 's5'
    quote = clients('operator').post('/api/stand/quote', json={
        'version': reset.json['version'], 'dealId': 1474, 'dir': 'rub',
        'cpId': 'broker', 'rate': '87'})
    assert quote.status_code == 200, quote.json
    deal = quote.json['data']['deals'][0]
    assert deal['step'] == 's6' and deal['rates']['rubUsdt'] == '87'
    assert deal['docVersion'] == 1 and deal['docsIssued'][0]['docId'] == 20
    assert deal['rerateDocVersion'] == 1


FREEHOLD_THB = {
    'type': 'Оплата недвижимости', 'kind': 'Фрихолд', 'payType': 'По реквизитам',
    'curBase': 'fhusd', 'invoiceCurrency': 'thb', 'invoiceThb': 9976500,
    'invoiceUsd': 297983.87, 'fxBank': 'Kasikorn', 'fxRate': 33.48,
    'ippsTariff': 'bank', 'selfRate': True, 'isOld': True,
    'docVersion': 1, 'docPack': {'version': 1, 'agreementId': 123},
    'reRequest': 3, 'rerateDocVersion': 1, 'rates': {'rubUsdt': '85'},
}


def test_rerated_thb_freehold_edits_and_reissues_agreed_terms(board, monkeypatch):
    import docgen
    from tests.test_stand_docs import _fields, _text

    monkeypatch.setattr(docgen, 'to_pdf', lambda raw, timeout=120: None)
    install, clients = board
    old_fields = _fields(kind='Фрихолд', passNo='78 1234567', amountThb='297983.87',
                         amountPay='26818548.30', rate='90')
    old_doc = {'kind': 'app', 'version': 1, 'docId': 21}
    old_economy = {'version': 1, 'invoiceUsd': 297983.87, 'ippsTariff': 'bank'}
    pdf = base64.b64encode(b'%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\n%%EOF').decode()
    install('s6', {**FREEHOLD_THB, 'docsIssued': [old_doc], 'docFields': old_fields,
                   'ownerEconomyAtDoc': old_economy,
                   'files': {'inv': [{'file': 'synthetic.pdf', 'mime': 'application/pdf',
                                      'data': 'data:application/pdf;base64,' + pdf}]}})
    manager, operator = clients('manager'), clients('operator')
    invoice_usd = round(FREEHOLD_THB['invoiceThb'] / 33.86, 2)
    fx = put(manager, lambda s: s['deals'][0].update(fxRate=33.86, invoiceUsd=invoice_usd))
    assert fx.status_code == 200, fx.json
    assert fx.json['data']['deals'][0]['fxRate'] == 33.86
    tariff = put(manager, lambda s: s['deals'][0].update(ippsTariff='soft'))
    assert tariff.status_code == 200, tariff.json
    d = tariff.json['data']['deals'][0]
    assert (d['ippsTariff'], d['invoiceUsd']) == ('soft', invoice_usd)
    assert (d['docVersion'], d['docPack'], d['docsIssued'], d['ownerEconomyAtDoc']) == (
        1, FREEHOLD_THB['docPack'], [old_doc], old_economy)

    def agree(s):
        d = s['deals'][0]
        d.update(step='s8', freeholdClientInput='rate', amountRub=round(invoice_usd * 91, 2))
        d['rates']['client'] = '91,0000'

    approved = put(manager, agree)
    assert approved.status_code == 200, approved.json
    handed = put(manager, lambda s: s['deals'][0].update(step='s11'))
    assert handed.status_code == 200, handed.json
    assert operator.get('/api/stand/docs/zip?dealId=1474').status_code == 409
    blocked = put(operator, lambda s: s['deals'][0].update(step='s11b'))
    assert blocked.status_code == 409
    assert 'перевыпустите' in blocked.json['error']

    issue = operator.post('/api/stand/docs/issue', json={'dealId': 1474, 'docFields': old_fields})
    assert issue.status_code == 200, issue.json
    d = issue.json['data']['deals'][0]
    assert d['docVersion'] == d['docPack']['version'] == 2
    assert d['docsIssued'][0] == old_doc
    assert d['docFields']['amountThb'] == d['ownerEconomyAtDoc']['invoiceUsd'] == invoice_usd
    assert float(d['docPack']['amount']) == round(invoice_usd * 91, 2)
    assert d['ownerEconomyAtDoc']['ippsTariff'] == 'soft'
    app_doc = next(entry for entry in issue.json['issued'] if entry['kind'] == 'app')
    assert 'THB 9976500' in _text(operator, app_doc['docId'])
    handoff = put(operator, lambda s: s['deals'][0].update(step='s11b'))
    assert handoff.status_code == 200, handoff.json


@pytest.mark.parametrize('step,role,over', [
    ('s6', 'manager', {'rerateDocVersion': None}),
    ('s6', 'manager', {'rerateDocVersion': 0}),
    ('s6', 'operator', {}),
    ('s6', 'manager', {'prepay': {'brokerStep': 's18', 'wallet': {'role': 'findir'}}}),
    ('s6', 'manager', {'transfer': {'sends': [{'status': 'pending'}]}}),
    ('s6', 'manager', {'pay': {'invoicePaid': True}}),
    ('s8', 'manager', {}),
    ('s11', 'operator', {}),
    ('s12', 'manager', {}),
])
def test_freehold_tariff_locked_outside_uncommitted_rerated_calculation(board, step, role, over):
    install, clients = board
    install(step, {**FREEHOLD_THB, **over})
    client = clients(role)
    response = put(client, lambda s: s['deals'][0].update(ippsTariff='soft'))
    assert response.status_code == 409, response.json
    assert client.get('/api/stand/state').json['data']['deals'][0]['ippsTariff'] == 'bank'


def test_rerated_freehold_edit_preserves_credited_money(board):
    install, clients = board
    part = {'incId': 44, 'amountRub': 90000}
    credit = {'id': 44, 'dealId': 1474, 'rub': 90000, 'source': 'sber'}
    install('s6', {**FREEHOLD_THB, 'payinParts': [part], 'incomeAmount': 90000},
            {'incomes': [credit]})
    manager = clients('manager')
    blocked = put(manager, lambda s: s['deals'][0].update(ippsTariff='soft', payinParts=[]))
    assert blocked.status_code == 409, blocked.json
    accepted = put(manager, lambda s: s['deals'][0].update(ippsTariff='soft'))
    assert accepted.status_code == 200, accepted.json
    assert accepted.json['data']['deals'][0]['payinParts'] == [part]
    assert accepted.json['data']['deals'][0]['incomeAmount'] == 90000
    assert accepted.json['data']['incomes'] == [credit]


def test_replacement_version_cannot_make_rerated_pack_current(board):
    install, clients = board
    install('s11', {**FREEHOLD_THB, 'docVersion': 2})
    operator = clients('operator')
    response = put(operator, lambda s: s['deals'][0].update(step='s11b'))
    assert response.status_code == 409
    assert 'перевыпустите' in response.json['error']
    upload = operator.post('/api/stand/docs/upload', data={
        'dealId': '1474', 'kind': 'app', 'file': (io.BytesIO(b'%PDF-1.4 synthetic'), 'fake.pdf'),
    })
    assert upload.status_code == 409
    assert 'перевыпустите' in upload.json['error']
    install('s12', {**FREEHOLD_THB, 'docVersion': 2})
    sent = put(clients('manager'), lambda s: s['deals'][0].update(docsSent={'version': 2}))
    assert sent.status_code == 409
    assert 'перевыпустите' in sent.json['error']


@pytest.mark.parametrize('field,value', [
    ('docVersion', 7), ('docsIssued', []), ('docPack', {'version': 7})])
def test_rerate_cannot_forge_new_document_version(board, field, value):
    install, clients = board
    install('s12', {'pair': 'RUB → USDT', 'rates': {'rubUsdt': '85'},
                    'docVersion': 1, 'docPack': {'version': 1},
                    'docsIssued': [{'version': 1, 'kind': 'bill', 'docId': 20}]})
    def forge(state):
        rerate(state)
        state['deals'][0][field] = value
    response = put(clients('manager'), forge)
    assert response.status_code == 409, response.json
    assert 'сервер' in response.json['error']


def test_old_package_cannot_be_sent_as_new_after_rerate(board):
    install, clients = board
    install('s11', {'pair': 'RUB → USDT', 'rates': {'client': '95'},
                    'docVersion': 1, 'rerateDocVersion': 1,
                    'docPack': {'version': 1, 'rate': '90'},
                    'docsIssued': [{'version': 1, 'kind': 'bill', 'docId': 20}]})
    response = put(clients('operator'), lambda state: state['deals'][0].update(step='s11b'))
    assert response.status_code == 409, response.json
    assert response.json['error'] == 'Сначала перевыпустите документы с новым курсом'
    forged = put(clients('operator'), lambda state: state['deals'][0].update(rerateDocVersion=0))
    assert forged.status_code == 409, forged.json
    assert forged.json['error'] == 'Версию для повторного выпуска документов фиксирует сервер'


def test_server_reissues_new_rate_before_document_handoff(board, monkeypatch):
    import docgen
    from tests.test_stand_docs import _fields

    monkeypatch.setattr(docgen, 'to_pdf', lambda raw, timeout=120: None)
    install, clients = board
    install('s11', {'type': 'Оплата недвижимости', 'kind': 'Лизхолд',
                    'payType': 'По реквизитам', 'curBase': 'thb',
                    'amountThb': 350000, 'amountRub': 1015000,
                    'incomeAmount': 914795,
                    'payinParts': [{'incId': 44, 'amountRub': 914795}],
                    'rates': {'client': '2,90'}, 'docVersion': 1,
                    'rerateDocVersion': 1, 'docPack': {'version': 1, 'rate': '2,6137'},
                    'docsIssued': [{'version': 1, 'kind': 'bill', 'docId': 20}]},
            {'incomes': [{'id': 44, 'dealId': 1474, 'rub': 914795, 'source': 'sber'}]})
    issue = clients('operator').post('/api/stand/docs/issue', json={
        'dealId': 1474, 'docFields': _fields(fio='Тестова Ксения Ивановна',
            passNo='77 1234567', amountPay='1015000', amountThb='350000', rate='2,90')})
    assert issue.status_code == 200, issue.json
    deal = issue.json['data']['deals'][0]
    assert deal['docVersion'] == 2 and float(deal['docPack']['rate']) == 2.9
    assert all(entry['version'] == 2 for entry in issue.json['issued'])
    assert deal['docsIssued'][0]['docId'] == 20
    assert deal['incomeAmount'] == 914795
    assert deal['payinParts'] == [{'incId': 44, 'amountRub': 914795}]
    handoff = put(clients('operator'), lambda state: state['deals'][0].update(step='s11b'))
    assert handoff.status_code == 200, handoff.json


def test_credited_receipt_survives_rerate_before_broker_send(board):
    install, clients = board
    credit = {'id': 44, 'dealId': 1474, 'rub': 90000, 'source': 'sber'}
    part = {'incId': 44, 'amountRub': 90000}
    install('s18', {'pair': 'RUB → USDT', 'rates': {'rubUsdt': '85', 'client': '90'},
                    'amountRub': 90000, 'amountUsdt': 1000,
                    'incomeAmount': 90000, 'payinParts': [part],
                    'expect': {'amount': 90000}, 'docVersion': 1,
                    'docPack': {'version': 1, 'amount': '90000', 'rate': '90'},
                    'docsIssued': [{'version': 1, 'kind': 'bill', 'docId': 20}]},
            {'incomes': [credit], 'cps': [{'id': 'broker', 'name': 'Synthetic Broker', 'dirs': ['rub']}]})
    manager = clients('manager')
    reset = put(manager, rerate)
    assert reset.status_code == 200, reset.json
    saved = reset.json['data']
    assert saved['incomes'] == [credit]
    assert saved['deals'][0]['payinParts'] == [part]
    assert saved['deals'][0]['incomeAmount'] == 90000
    assert saved['deals'][0]['expect']['amount'] == 90000
    quote = clients('operator').post('/api/stand/quote', json={
        'version': reset.json['version'], 'dealId': 1474, 'dir': 'rub',
        'cpId': 'broker', 'rate': '87'})
    assert quote.status_code == 200, quote.json

    def recalc(state):
        deal = state['deals'][0]
        deal.update(step='s8', amountRub=95000,
                    rerateExpectFollowsDeal=True, rerateDocVersion=1)
        deal['rates']['client'] = '95'

    agreed = put(manager, recalc)
    assert agreed.status_code == 200, agreed.json
    deal = agreed.json['data']['deals'][0]
    assert deal['amountRub'] == 95000 and deal['incomeAmount'] == 90000
    assert deal['payinParts'] == [part] and agreed.json['data']['incomes'] == [credit]
    assert deal['docVersion'] == 1 and deal['docsIssued'][0]['docId'] == 20


@pytest.mark.parametrize('field,value', [
    ('payinParts', []), ('incomeAmount', None), ('expect', {'amount': 1})])
def test_rerate_cannot_erase_credited_money(board, field, value):
    install, clients = board
    install('s12', {'pair': 'RUB → USDT', 'rates': {'rubUsdt': '85'},
                    'payinParts': [{'incId': 44, 'amountRub': 90000}],
                    'incomeAmount': 90000, 'expect': {'amount': 90000}})
    def forge(state):
        rerate(state)
        state['deals'][0][field] = value
    response = put(clients('manager'), forge)
    assert response.status_code == 409, response.json
    assert 'приход' in response.json['error'].lower()


def test_after_broker_handoff_rerate_denied_in_plain_language(board):
    install, clients = board
    install('s18w', {'pair': 'RUB → USDT', 'cnvId': 1, 'rates': {'rubUsdt': '85'}},
            {'convs': [{'id': 1, 'status': 'sent', 'sources': [{'dealId': 1474, 'rub': 90000}]}]})
    response = put(clients('manager'), rerate)
    assert response.status_code == 409, response.json
    assert response.json['error'] == 'Рубли уже ушли брокеру — курс зафиксирован'
    assert clients('manager').get('/api/stand/state').json['data']['deals'][0]['step'] == 's18w'


@pytest.mark.parametrize('marker', [
    {'prepay': {'brokerStep': 's18'}},
    {'ippsPayoutOrder': {'confirmedAt': '2026-10-15T08:00:00Z'}},
    {'outgoingOrderAt': '2026-10-15T08:00:00Z'},
    {'transfer': {'sends': [{'hash': 'a' * 64}]}},
])
def test_started_prepay_or_outgoing_denies_rerate(board, marker):
    install, clients = board
    install('s18', {'pair': 'RUB → USDT', 'rates': {'rubUsdt': '85'}, **marker})
    response = put(clients('manager'), rerate)
    assert response.status_code == 409, response.json
    assert response.json['error'] == 'Оплата наперёд или исходящий перевод уже начаты — курс зафиксирован'


def test_prepay_payment_branch_denies_with_prepay_message(board):
    install, clients = board
    install('s22', {'pair': 'RUB → USDT', 'rates': {'rubUsdt': '85'},
                    'prepay': {'brokerStep': 's18', 'amount': 10000}})
    response = put(clients('manager'), rerate)
    assert response.status_code == 409, response.json
    assert response.json['error'] == 'Оплата наперёд или исходящий перевод уже начаты — курс зафиксирован'


def test_crypto_freehold_without_external_quote_has_no_rerate_route(board):
    install, clients = board
    install('s12', {'type': 'Оплата недвижимости', 'kind': 'Фрихолд',
                    'payType': 'Крипта', 'rates': {}})
    response = put(clients('manager'), rerate)
    assert response.status_code == 409, response.json
    assert response.json['error'] == 'В этой сделке внешний курс не запрашивается'


@pytest.mark.parametrize('start', ['s6', 's12'])
def test_self_rate_returns_to_calculation_and_needs_new_pair_quote(board, start):
    install, clients = board
    install(start, {'pair': 'RUB → USDT', 'selfRate': True,
                    'rates': {'rubUsdt': '85', 'client': '90'},
                    'amountRub': 90000, 'amountUsdt': 1000})
    manager = clients('manager')
    reset = put(manager, lambda state: rerate(state, 's6'))
    assert reset.status_code == 200, reset.json
    assert reset.json['data']['deals'][0]['step'] == 's6'

    def agree(state, rate):
        deal = state['deals'][0]
        deal.update(step='s8', amountRub=95000)
        deal['rates'] = {'client': '95', **({'rubUsdt': rate} if rate else {})}

    missing = put(manager, lambda state: agree(state, None))
    assert missing.status_code == 409
    assert 'курсы выбранной пары' in missing.json['error']
    good = put(manager, lambda state: agree(state, '87'))
    assert good.status_code == 200, good.json
    assert good.json['data']['deals'][0]['amountRub'] == 95000


def test_rerate_ui_recalculates_and_shows_both_balances():
    subprocess.run(['node', 'tests/test_stand_rerate.js'], check=True)
