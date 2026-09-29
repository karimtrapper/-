"""Выпуск настоящих документов на стенде: POST /api/stand/docs/issue и /upload.

Генератор тот же, что у CRM; LibreOffice в тестах выключен — as_pdf отдаёт DOCX,
его текст и проверяем. Данные синтетические.
"""
import io
import json
import re

import pytest
from docx import Document

import app as appmod
import docgen
import stand_notify

RUB_PAY_TO = ('ООО «ЭМ ЭФ КОРПОРЕЙШН» · ИНН 9909726886 · КПП 770387001 · ПАО Сбербанк · '
              'р/с 40807810938720000286 · к/с 30101810400000000225 · БИК 044525225')
PURPOSE = 'Оплата по агентскому договору № SD-9001, НДС не облагается'
GRUSHA = 'TKkeEVf2zySaWTLyX2qPwvi6kcdHRuPxkJ'
CRYPTO_FREEHOLD_FEE = 'Вознаграждение агента включено в сумму платежа, отдельно не взимается'
CRYPTO_FREEHOLD_AGENT_FEE = (
    'Вознаграждение агента включено в сумму платежа, отдельно не взимается / '
    'The Agent’s fee is included in the payment amount and is not charged separately'
)


def _fields(**over):
    base = {'fio': 'Тестов Иван Петрович', 'fioLat': 'IVAN TESTOV', 'passNo': '75 1234567',
            'passIss': '01.02.2020', 'passOrg': 'МВД 770-001', 'born': '03.04.1985',
            'dev': 'Test Development Co., Ltd.', 'invNo': 'INV-TEST-1', 'invDate': '01.09.2026',
            'object': 'Test Residence, A-101', 'kind': 'Лизхолд',
            'amountThb': '350 000', 'rate': '2,6137', 'amountPay': '914 795',
            'payTo': RUB_PAY_TO, 'purpose': PURPOSE,
            'feeNote': 'Комиссия включена в курс, отдельно не взимается', 'validTill': ''}
    base.update(over)
    return base


def _deal(deal_id, **over):
    d = {'id': deal_id, 'code': f'SD-{deal_id}', 'client': 'Тестов Иван', 'type': 'Оплата недвижимости',
         'kind': 'Лизхолд', 'payType': 'По реквизитам', 'curBase': 'thb', 'step': 's11',
         'isOld': False, 'log': [], 'docParse': {'fields': {
             'client_name_en': 'IVAN TESTOV', 'client_citizenship': 'Россия',
             'project_name': 'Test Residence', 'unit_no': 'A-101'}}}
    d.update(over)
    return d


@pytest.fixture
def stand(monkeypatch):
    monkeypatch.setattr(appmod, 'STAND_MODE', True)
    # В общем pytest app импортирован в прод-режиме; поднимаем таблицы и уведомления после смены режима.
    appmod._stand_migrate()
    stand_notify.init(appmod)
    monkeypatch.setenv('LOCAL_NO_AUTH', '1')

    def role_lookup():
        # как настоящая current_role: закрывает общую scoped-сессию
        appmod.get_session().close()
        return 'operator'
    monkeypatch.setattr(appmod, 'current_role', role_lookup)
    monkeypatch.setattr(docgen, 'to_pdf', lambda raw, timeout=120: None)
    db = appmod.get_session()
    try:
        db.query(appmod.AgreementDoc).delete()
        db.query(appmod.Agreement).delete()
        db.commit()
    finally:
        db.close()

    def put(deals, wallets=None):
        db = appmod.get_session()
        try:
            row = appmod._stand_row(db)
            row.data = json.dumps({'deals': deals, 'convs': [], 'wallets': wallets or []})
            row.version = 1
            db.commit()
        finally:
            db.close()
    with appmod.app.test_client() as client:
        db = appmod.get_session()
        try:
            user = db.query(appmod.AdminUser).filter_by(username='stand_docs_test').first()
            if not user:
                user = appmod.AdminUser(username='stand_docs_test', role='operator',
                                        password_hash=appmod.AdminUser.hash_password('test'))
                db.add(user); db.commit()
            uid = user.id
        finally:
            db.close()
        with client.session_transaction() as sess:
            sess['user_id'] = uid
        client.put_board = put
        yield client


def _text(client, doc_id):
    r = client.get(f'/api/docs/file/{doc_id}')
    assert r.status_code == 200
    doc = Document(io.BytesIO(r.data))
    parts = [p.text for p in doc.paragraphs]
    for t in doc.tables:
        for row in t.rows:
            parts += [c.text for c in row.cells]
    return '\n'.join(parts)


def _agent_fee_cells(client, doc_id):
    response = client.get(f'/api/docs/file/{doc_id}')
    assert response.status_code == 200
    doc = Document(io.BytesIO(response.data))
    return [row.cells[-1].text for table in doc.tables for row in table.rows
            if row.cells and 'Комиссия Агента' in row.cells[0].text]


def _appendix_row_labels(client, doc_id):
    response = client.get(f'/api/docs/file/{doc_id}')
    assert response.status_code == 200
    doc = Document(io.BytesIO(response.data))
    return [row.cells[0].text for table in doc.tables for row in table.rows if row.cells]


@pytest.mark.parametrize('currency,expected', [('thb', 'THB 1500000'), ('usd', 'USD 45000')])
def test_freehold_invoice_currency_issues_real_pack(stand, currency, expected):
    deal = _deal(901 if currency == 'thb' else 902, kind='Фрихолд', curBase='fhusd',
                 invoiceUsd=45000, invoiceCurrency=currency,
                 invoiceThb=1500000 if currency == 'thb' else None, ippsTariff='bank')
    stand.put_board([deal])
    fields = _fields(amountThb='45000', amountPay='3710389.50', rate='82.4531')
    response = stand.post('/api/stand/docs/issue', json={'dealId': deal['id'], 'docFields': fields})
    assert response.status_code == 200, response.json
    assert [entry['kind'] for entry in response.json['issued']] == ['dog', 'app', 'bill']
    texts = [_text(stand, entry['docId']) for entry in response.json['issued']]
    assert expected in texts[1]
    assert '1500000' not in texts[2]
    if currency == 'thb':
        for label in ('Источник курса и срок действия', 'Подтверждённый USD-эквивалент',
                      'Статус зачёта THB-инвойса', 'Письменное подтверждение застройщика'):
            assert label in texts[1]
        assert texts[1].count('[●]') >= 4
    else:
        assert 'Н/П' in texts[1]


def test_new_client_leasehold_rub_issues_agreement_addendum_invoice(stand):
    stand.put_board([_deal(1)])
    r = stand.post('/api/stand/docs/issue', json={'dealId': 1, 'docFields': _fields()})
    assert r.status_code == 200, r.json
    pack = r.json['pack']
    assert pack['mode'] == 'agreement' and pack['version'] == 1
    assert pack['pair'] == 'RUB_THB' and pack['method'] == 'bank'
    assert pack['purpose'] == PURPOSE
    assert [e['kind'] for e in r.json['issued']] == ['dog', 'app', 'bill']

    saved = stand.get('/api/stand/state').json['data']['deals'][0]
    assert [e['kind'] for e in saved['docsIssued']] == ['dog', 'app', 'bill']
    assert saved['docVersion'] == 1 and saved['docPack']['agreementId'] == pack['agreementId']
    assert 'Выпущен пакет документов' in saved['log'][-1]['text']

    by = {e['kind']: e['docId'] for e in saved['docsIssued']}
    agreement = _text(stand, by['dog'])
    assert 'Тестов Иван Петрович' in agreement and '75 1234567' in agreement
    addendum = _text(stand, by['app'])
    assert '914 795' in addendum and '350 000' in addendum and '2.6137' in addendum
    invoice = _text(stand, by['bill'])
    assert PURPOSE in invoice and '40807810938720000286' in invoice and '914 795' in invoice

    # «Поправить и пересоздать» — тот же договор, новая версия, без второго договора
    again = stand.post('/api/stand/docs/issue', json={'dealId': 1, 'docFields': _fields(amountPay='914 795')})
    assert again.status_code == 200, again.json
    assert again.json['pack']['agreementId'] == pack['agreementId']
    assert again.json['pack']['version'] == 2 and again.json['pack']['mode'] == 'agreement'
    db = appmod.get_session()
    try:
        assert db.query(appmod.Agreement).count() == 1
    finally:
        db.close()


def test_known_client_gets_addendum_and_invoice(stand):
    stand.put_board([_deal(1), _deal(2, isOld=True)])
    first = stand.post('/api/stand/docs/issue', json={'dealId': 1, 'docFields': _fields()})
    assert first.status_code == 200, first.json
    second = stand.post('/api/stand/docs/issue', json={
        'dealId': 2, 'docFields': _fields(amountThb='100 000', rate='2,6', amountPay='260 000')})
    assert second.status_code == 200, second.json
    pack = second.json['pack']
    assert pack['mode'] == 'addendum' and pack['paymentNo'] == 2
    assert pack['agreementId'] == first.json['pack']['agreementId']
    assert [e['kind'] for e in second.json['issued']] == ['app', 'bill']
    invoice = _text(stand, second.json['issued'][1]['docId'])
    assert '260 000' in invoice


def test_known_client_without_agreement_in_base_gets_full_package_with_note(stand):
    stand.put_board([_deal(3, isOld=True)])
    r = stand.post('/api/stand/docs/issue', json={'dealId': 3, 'docFields': _fields()})
    assert r.status_code == 200, r.json
    assert r.json['pack']['mode'] == 'agreement'
    assert 'полный договор' in r.json['pack']['note']


def test_crypto_usdt_thb_uses_wallet_and_no_purpose(stand):
    stand.put_board([_deal(4, payType='Крипта', curBase='usdt', walletId='grusha')])
    fields = _fields(passNo='76 7654321', rate='32,5', amountPay='10 769,23', amountThb='350 000',
                     payTo='USDT · сеть TRC-20 · кошелёк: ' + GRUSHA, purpose='')
    r = stand.post('/api/stand/docs/issue', json={'dealId': 4, 'docFields': fields})
    assert r.status_code == 200, r.json
    pack = r.json['pack']
    assert pack['pair'] == 'USDT_THB' and pack['method'] == 'usdt'
    assert pack['wallet'] == GRUSHA and 'TRC-20' in pack['network'] and pack['purpose'] == ''
    invoice = _text(stand, r.json['issued'][-1]['docId'])
    assert GRUSHA in invoice and '10 769.23' in invoice


@pytest.mark.parametrize('pay_type,cur_base,saved_fee,submitted_fee', [
    ('Крипта', 'usdt', 'Комиссия включена в курс, отдельно не взимается',
     'Комиссия включена в курс, отдельно не взимается'),
    (None, 'usdt', 'Комиссия включена в курс, отдельно не взимается',
     'Комиссия включена в курс, отдельно не взимается'),
    ('Крипта', 'usdt', 'Индивидуальная оговорка клиента',
     'Индивидуальная оговорка клиента'),
    ('Крипта', 'usdt', 'Индивидуальная оговорка клиента',
     'Комиссия включена в курс, отдельно не взимается'),
])
def test_crypto_freehold_fee_note_in_generated_appendix(
        stand, pay_type, cur_base, saved_fee, submitted_fee):
    deal = _deal(940, kind='Фрихолд', payType=pay_type, curBase=cur_base,
                 invoiceUsd=97500, amountUsdt=98800, ippsTariff='bank',
                 docFields={'feeNote': saved_fee})
    stand.put_board([deal], wallets=[{'id': 'grusha', 'addr': GRUSHA}])
    fields = _fields(kind='Фрихолд', amountThb='97500', amountPay='98800', rate='',
                     payTo='USDT · сеть TRC-20 · кошелёк: ' + GRUSHA,
                     purpose='', feeNote=submitted_fee)
    response = stand.post('/api/stand/docs/issue',
                          json={'dealId': deal['id'], 'docFields': fields})
    assert response.status_code == 200, response.json
    appendix_id = next(x['docId'] for x in response.json['issued'] if x['kind'] == 'app')
    appendix = _text(stand, appendix_id)
    assert _agent_fee_cells(stand, appendix_id) == [CRYPTO_FREEHOLD_AGENT_FEE] * 2
    assert appendix.count(CRYPTO_FREEHOLD_AGENT_FEE) == 2
    assert 'курс' not in appendix.casefold()
    assert not re.search(r'\brate\b', appendix, re.IGNORECASE)
    # The mandatory word "separately" itself contains the letters "rate".
    assert 'rate' not in appendix.replace(CRYPTO_FREEHOLD_AGENT_FEE, '').casefold()
    assert 'платёжного партнёра' not in appendix.casefold()
    labels = _appendix_row_labels(stand, appendix_id)
    assert not any('Комиссия платёжного партнёра и конвертация' in x or
                   'Источник курса и срок действия' in x for x in labels)
    saved = stand.get('/api/stand/state').json['data']['deals'][0]
    assert saved['docFields']['feeNote'] == CRYPTO_FREEHOLD_AGENT_FEE
    assert saved['docFields']['payTo'] == 'USDT TRC-20, ' + GRUSHA


def test_crypto_freehold_erc_document_uses_saved_canonical_receiver(stand):
    addr = '0x68aEA0F5386a57b48953F6fFF2f22D29D00D9ba9'
    deal = _deal(944, kind='Фрихолд', payType='Крипта', curBase='usdt',
                 walletId='teodor-erc', invoiceUsd=97500, amountUsdt=98800,
                 ippsTariff='bank')
    stand.put_board([deal], wallets=[{'id': 'teodor-erc', 'addr': '0x' + '3' * 40,
                                      'net': 'ERC-20', 'owner': 'компания'}])
    fields = _fields(kind='Фрихолд', amountThb='97500', amountPay='98800',
                     rate='', payTo='USDT TRC-20, ' + GRUSHA, purpose='')
    response = stand.post('/api/stand/docs/issue',
                          json={'dealId': deal['id'], 'docFields': fields})
    assert response.status_code == 200, response.json
    saved = stand.get('/api/stand/state').json['data']['deals'][0]
    assert saved['docFields']['payTo'] == 'USDT ERC-20, ' + addr
    assert saved['docFields']['feeNote'] == CRYPTO_FREEHOLD_AGENT_FEE
    invoice = _text(stand, response.json['issued'][-1]['docId'])
    assert addr in invoice and 'ERC-20' in invoice


@pytest.mark.parametrize('kind,amount_thb,amount_pay,rate,expected', [
    ('Фрихолд', '45000', '3710389.50', '82.4531',
     'Включена в согласованную сумму pay-in; отдельно не взимается / '
     'Included in the agreed pay-in amount; no separate charge'),
    ('Лизхолд', '350000', '914795', '2.6137',
     'Включена в курс 2.6137 RUB/THB, отдельно не взимается / '
     'Included in the rate of 2.6137 RUB/THB, not charged separately'),
])
def test_other_property_fee_note_generated_output_unchanged(
        stand, kind, amount_thb, amount_pay, rate, expected):
    deal = _deal(941, kind=kind, invoiceUsd=45000 if kind == 'Фрихолд' else None,
                 ippsTariff='bank' if kind == 'Фрихолд' else None)
    stand.put_board([deal])
    fields = _fields(kind=kind, amountThb=amount_thb, amountPay=amount_pay, rate=rate)
    response = stand.post('/api/stand/docs/issue',
                          json={'dealId': deal['id'], 'docFields': fields})
    assert response.status_code == 200, response.json
    appendix_id = next(x['docId'] for x in response.json['issued'] if x['kind'] == 'app')
    appendix = _text(stand, appendix_id)
    agent_cells = _agent_fee_cells(stand, appendix_id)
    assert agent_cells == [expected, docgen.DEFAULTS['fee_included']]
    assert CRYPTO_FREEHOLD_FEE not in appendix
    saved = stand.get('/api/stand/state').json['data']['deals'][0]
    assert saved['docFields']['payTo'] == RUB_PAY_TO


@pytest.mark.parametrize('kind,pay_type,cur_base,amount_thb,amount_pay,rate', [
    ('Фрихолд', 'По реквизитам', 'fhusd', '45000', '3710389.50', '82.4531'),
    ('Лизхолд', 'По реквизитам', 'thb', '350000', '914795', '2.6137'),
    ('Аренда', 'По реквизитам', 'thb', '350000', '914795', '2.6137'),
])
def test_other_property_manual_fee_note_reaches_generated_appendix(
        stand, kind, pay_type, cur_base, amount_thb, amount_pay, rate):
    manual = 'Индивидуальная оговорка / Individually agreed fee note'
    deal = _deal(942, kind=kind, payType=pay_type, curBase=cur_base,
                 invoiceUsd=45000 if kind == 'Фрихолд' else None,
                 ippsTariff='bank' if kind == 'Фрихолд' else None)
    stand.put_board([deal])
    fields = _fields(kind=kind, amountThb=amount_thb, amountPay=amount_pay,
                     rate=rate, feeNote=manual)
    response = stand.post('/api/stand/docs/issue',
                          json={'dealId': deal['id'], 'docFields': fields})
    assert response.status_code == 200, response.json
    appendix_id = next(x['docId'] for x in response.json['issued'] if x['kind'] == 'app')
    assert _agent_fee_cells(stand, appendix_id) == [manual, docgen.DEFAULTS['fee_included']]


def test_crypto_freehold_reissue_keeps_issued_appendix_bytes(stand):
    deal = _deal(943, kind='Фрихолд', payType='Крипта', curBase='usdt',
                 invoiceUsd=97500, amountUsdt=98800, ippsTariff='bank')
    stand.put_board([deal], wallets=[{'id': 'grusha', 'addr': GRUSHA}])
    fields = _fields(kind='Фрихолд', amountThb='97500', amountPay='98800', rate='',
                     payTo='USDT · сеть TRC-20 · кошелёк: ' + GRUSHA, purpose='')
    first = stand.post('/api/stand/docs/issue',
                       json={'dealId': deal['id'], 'docFields': fields})
    assert first.status_code == 200, first.json
    first_id = next(x['docId'] for x in first.json['issued'] if x['kind'] == 'app')
    first_bytes = stand.get(f'/api/docs/file/{first_id}').data
    fields['feeNote'] = 'Индивидуальная оговорка клиента'
    second = stand.post('/api/stand/docs/issue',
                        json={'dealId': deal['id'], 'docFields': fields})
    assert second.status_code == 200, second.json
    second_id = next(x['docId'] for x in second.json['issued'] if x['kind'] == 'app')
    assert _agent_fee_cells(stand, second_id) == [CRYPTO_FREEHOLD_AGENT_FEE] * 2
    assert stand.get(f'/api/docs/file/{first_id}').data == first_bytes
    assert stand.get('/api/stand/state').json['data']['deals'][0]['docFields']['feeNote'] == CRYPTO_FREEHOLD_AGENT_FEE


@pytest.mark.parametrize('wallet_id,custom,expected_net,expected_addr', [
    ('teodor-erc', None, 'ERC-20', '0x68aEA0F5386a57b48953F6fFF2f22D29D00D9ba9'),
    ('custom', {'network': 'ERC-20', 'addr': '0x' + '2' * 40}, 'ERC-20', '0x' + '2' * 40),
    ('custom', {'network': 'TRC-20', 'addr': GRUSHA}, 'TRC-20', GRUSHA),
])
def test_crypto_directory_and_custom_network_in_issued_document(
        stand, wallet_id, custom, expected_net, expected_addr):
    deal = _deal(104, payType='Крипта', curBase='usdt', walletId=wallet_id)
    if custom:
        deal['payinCustom'] = custom
    # A stale/forged saved entry must not override the reviewed Teodor address.
    stand.put_board([deal], wallets=[{'id': 'teodor-erc', 'addr': '0x' + '3' * 40,
                                      'net': 'ERC-20', 'owner': 'компания'}])
    fields = _fields(rate='32,5', amountPay='10 769,23', amountThb='350 000',
                     payTo='USDT '+expected_net+', '+expected_addr, purpose='')
    response = stand.post('/api/stand/docs/issue', json={'dealId': 104, 'docFields': fields})
    assert response.status_code == 200, response.json
    pack = response.json['pack']
    assert pack['wallet'] == expected_addr and expected_net in pack['network']
    invoice = _text(stand, response.json['issued'][-1]['docId'])
    assert expected_addr in invoice and expected_net in invoice


@pytest.mark.parametrize('network,address', [
    ('ERC-20', GRUSHA), ('TRC-20', '0x' + '2' * 40), ('BEP-20', GRUSHA),
])
def test_crypto_invalid_custom_network_or_address_cannot_issue(stand, network, address):
    deal = _deal(105, payType='Крипта', curBase='usdt', walletId='custom',
                 payinCustom={'network': network, 'addr': address})
    stand.put_board([deal])
    response = stand.post('/api/stand/docs/issue', json={'dealId': 105,
        'docFields': _fields(rate='32,5', amountPay='10 769,23', amountThb='350 000',
                            payTo='USDT '+network+', '+address, purpose='')})
    assert response.status_code == 400
    assert 'payTo' in response.json['fields']


def test_missing_fields_return_400_with_stand_labels(stand):
    stand.put_board([_deal(5)])
    r = stand.post('/api/stand/docs/issue', json={'dealId': 5, 'docFields': _fields(passNo='', amountPay='')})
    assert r.status_code == 400
    assert r.json['error'] == 'missing_fields'
    assert set(r.json['fields']) >= {'passNo', 'amountPay'}
    assert 'номер паспорта' in r.json['detail'] and 'сумма клиенту' in r.json['detail']
    db = appmod.get_session()
    try:
        assert db.query(appmod.Agreement).count() == 0
    finally:
        db.close()


def test_rate_not_matching_amounts_is_400_not_500(stand):
    stand.put_board([_deal(6)])
    r = stand.post('/api/stand/docs/issue', json={'dealId': 6, 'docFields': _fields(rate='3,1')})
    assert r.status_code == 400
    assert r.json['error'] == 'rate_mismatch' and 'rate' in r.json['fields']


def test_issue_only_on_document_step(stand):
    stand.put_board([_deal(7, step='s14')])
    r = stand.post('/api/stand/docs/issue', json={'dealId': 7, 'docFields': _fields()})
    assert r.status_code == 409


def test_upload_own_file_replaces_generated(stand):
    stand.put_board([_deal(8)])
    assert stand.post('/api/stand/docs/issue', json={'dealId': 8, 'docFields': _fields()}).status_code == 200
    pdf = b'%PDF-1.4 own contract'
    r = stand.post('/api/stand/docs/upload', data={'dealId': '8', 'kind': 'dog',
                                                   'file': (io.BytesIO(pdf), 'own.pdf')},
                   content_type='multipart/form-data')
    assert r.status_code == 200, r.json
    own = r.json['data']['deals'][0]['issued']['dog']
    assert own['file'] == 'own.pdf'
    assert stand.get(f"/api/docs/file/{own['docId']}").data == pdf
    bad = stand.post('/api/stand/docs/upload', data={'dealId': '8', 'kind': 'dog',
                                                     'file': (io.BytesIO(b'x'), 'x.exe')},
                     content_type='multipart/form-data')
    assert bad.status_code == 400


def test_stand_docs_hidden_outside_stand(monkeypatch):
    monkeypatch.setattr(appmod, 'STAND_MODE', False)
    monkeypatch.setenv('LOCAL_NO_AUTH', '1')
    with appmod.app.test_client() as client:
        assert client.post('/api/stand/docs/issue', json={'dealId': 1}).status_code == 404


def test_zip_contains_current_pack_with_own_file(stand):
    import zipfile
    stand.put_board([_deal(9)])
    assert stand.post('/api/stand/docs/issue', json={'dealId': 9, 'docFields': _fields()}).status_code == 200
    stand.post('/api/stand/docs/upload', data={'dealId': '9', 'kind': 'bill',
                                               'file': (io.BytesIO(b'%PDF-1.4 own bill'), 'bill.pdf')},
               content_type='multipart/form-data')
    r = stand.get('/api/stand/docs/zip?dealId=9')
    assert r.status_code == 200
    names = zipfile.ZipFile(io.BytesIO(r.data)).namelist()
    assert len(names) == 3 and 'bill.pdf' in names
    assert any(n.startswith('MF_Agreement_leasehold') for n in names)


def test_leasehold_without_invoice_number_names_the_field(stand):
    stand.put_board([_deal(10)])
    r = stand.post('/api/stand/docs/issue', json={'dealId': 10, 'docFields': _fields(invNo='')})
    assert r.status_code == 400
    assert r.json['fields'] == ['invNo'] and 'номер инвойса' in r.json['detail']


def test_crypto_freehold_stale_rate_does_not_block_issue(stand):
    # Сохранённый со старой версии курс (2.66) у крипто-фрихолда не должен давать
    # «Курс не соответствует суммам» — курса у такой сделки нет (Карим, 29.09).
    deal = _deal(945, kind='Фрихолд', payType='Крипта', curBase='usdt',
                 walletId='grusha', invoiceUsd=97500, amountUsdt=98800, ippsTariff='bank')
    stand.put_board([deal])
    fields = _fields(kind='Фрихолд', amountThb='97500', amountPay='98800',
                     rate='2.66', payTo='USDT TRC-20, ' + GRUSHA, purpose='')
    response = stand.post('/api/stand/docs/issue',
                          json={'dealId': deal['id'], 'docFields': fields})
    assert response.status_code == 200, response.json


def test_crypto_freehold_payment_ignores_rate_inherited_from_agreement(stand):
    # Второй платёж того же клиента идёт допником к уже выпущенному договору.
    # Курс, оставшийся в money_json договора, не должен ронять крипто-фрихолд
    # «Курс не соответствует суммам» (Карим, 29.09, СД-1475).
    first = _deal(946, kind='Фрихолд', payType='Крипта', curBase='usdt',
                  walletId='grusha', invoiceUsd=97500, amountUsdt=98800, ippsTariff='bank')
    second = _deal(947, kind='Фрихолд', payType='Крипта', curBase='usdt',
                   walletId='grusha', invoiceUsd=10000, amountUsdt=11000, ippsTariff='bank')
    stand.put_board([first, second])
    f1 = _fields(kind='Фрихолд', amountThb='97500', amountPay='98800', rate='',
                 payTo='USDT TRC-20, ' + GRUSHA, purpose='')
    r1 = stand.post('/api/stand/docs/issue', json={'dealId': 946, 'docFields': f1})
    assert r1.status_code == 200, r1.json
    db = appmod.get_session()
    try:
        a = db.query(appmod.Agreement).order_by(appmod.Agreement.id.desc()).first()
        money = json.loads(a.money_json or '{}')
        money['rate'] = '2.66'
        a.money_json = json.dumps(money)
        db.commit()
    finally:
        db.close()
    f2 = _fields(kind='Фрихолд', amountThb='10000', amountPay='11000', rate='2.66',
                 payTo='USDT TRC-20, ' + GRUSHA, purpose='')
    r2 = stand.post('/api/stand/docs/issue', json={'dealId': 947, 'docFields': f2})
    assert r2.status_code == 200, r2.json
