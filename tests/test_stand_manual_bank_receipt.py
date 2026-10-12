"""Сверка ручного рублёвого прихода операционистом по банковской выписке."""
import copy
import base64
import json
import secrets

import pytest

import app as m
from stand_funding import check_batch


def board():
    evidence = {'id': 'bce_123456789abc', 'file': 'statement.pdf', 'size': '1 КБ',
                'at': '12.10', 'mime': 'application/pdf', 'bytes': 19,
                'data': 'data:application/pdf;base64,' + base64.b64encode(b'%PDF-1.4\nstatement').decode(),
                'demo': False, 'uploadedById': 1, 'uploadedBy': 'Synthetic'}
    deal = {'id': 9301, 'code': 'SYN-9301', 'type': 'Обмен валюты',
            'payType': 'По реквизитам', 'curBase': 'rub', 'step': 's14',
            'amountRub': 10000, 'incomeAmount': None, 'pay': {}, 'rates': {},
            'rubReceivingAccount': {'mode': 'custom', 'bank': 'Test Bank',
                'account': '40702810900000012345',
                'correspondent': '30101810000000000000', 'bik': '044525225'},
            # Старое значение счёта может сохраниться; structured account — актуальный источник.
            'expect': {'acc': '…0286 · Сбер', 'bank': 'Сбер', 'account': '40807810938720000286'},
            'docVersion': 1, 'docFields': {'payTo': 'Старый банк · р/с 407028...'},
            'payinParts': [], 'log': [], 'closed': False,
            'files': {'bankCreditEvidence': [evidence]}}
    return {'deals': [deal], 'incomes': [], 'convs': [], 'wallets': [], 'notes': []}


def seed(monkeypatch, state):
    monkeypatch.setattr(m, 'STAND_MODE', True)
    m._stand_migrate()
    db = m.get_session()
    try:
        user = m.AdminUser(username='manual-bank-' + secrets.token_hex(4), role='admin',
                           display_name='Synthetic', password_hash='unused')
        db.add(user); db.flush()
        row = m._stand_row(db); row.data = json.dumps(state); row.version = 7
        db.commit(); uid = user.id
    finally:
        db.close()
    client = m.app.test_client()
    with client.session_transaction() as session:
        session['user_id'] = uid
    return client


def payload(version=7):
    return {'version': version, 'dealId': 9301, 'bank': 'Test Bank',
            'account': '40702810900000012345', 'actualAmount': '9987.50',
            'payer': 'Иван Клиент', 'bankPurpose': 'Оплата по договору',
            'statementDate': '2026-10-01',
            'statementRef': 'операция 7788', 'documentsAcknowledged': True}


def snapshot(client):
    return client.get('/api/stand/state').json


def test_manager_request_is_pending_operator_only_and_documents_ack_required(monkeypatch):
    client = seed(monkeypatch, board())
    monkeypatch.setattr(m, 'current_role', lambda: 'manager')
    data = payload(); data['documentsAcknowledged'] = False
    denied = client.post('/api/stand/manual-bank-receipt', json=data)
    assert denied.status_code == 403
    assert not snapshot(client)['data']['incomes']

    monkeypatch.setattr(m, 'current_role', lambda: 'operator')
    denied = client.post('/api/stand/manual-bank-receipt', json=data)
    assert denied.status_code == 409
    data['documentsAcknowledged'] = True
    saved = client.post('/api/stand/manual-bank-receipt', json=data)
    assert saved.status_code == 200, saved.json
    state = snapshot(client)['data']
    deal = state['deals'][0]
    assert deal['manualBankReceipt']['status'] == 'pending'
    assert deal['manualBankReceipt']['documentPayToAtRequest'] == 'Старый банк · р/с 407028...'
    assert deal['manualBankReceipt']['bankBik'] == '044525225'
    assert deal['manualBankReceipt']['correspondentAccount'] == '30101810000000000000'
    assert state['incomes'] == []
    assert saved.json['data']['notes'][0]['role'] == 'operator', saved.json['data']['notes'][0]
    assert 'сверка ручного rub прихода' in saved.json['data']['notes'][0]['text'].lower()

    # Нельзя обычным PUT добавить DEMO/пуловый приход между заявкой и сверкой.
    mixed = copy.deepcopy(state)
    mixed['deals'][0]['payinParts'] = [{'incId': 81, 'amountRub': 9987.5, 'demo': True}]
    mixed['deals'][0]['incomeAmount'] = 9987.5
    mixed['incomes'].append({'id': 81, 'dealId': 9301, 'rub': 9987.5, 'demo': True})
    rejected_mix = client.put('/api/stand/state', json={'version': saved.json['version'], 'data': mixed})
    assert rejected_mix.status_code == 409

    changed_expect = copy.deepcopy(state)
    changed_expect['deals'][0]['expect']['account'] = '40702810900000099999'
    put = client.put('/api/stand/state', json={'version': saved.json['version'], 'data': changed_expect})
    assert put.status_code == 409

    forged = copy.deepcopy(state); forged['deals'][0]['manualBankReceipt']['status'] = 'confirmed'
    put = client.put('/api/stand/state', json={'version': saved.json['version'], 'data': forged})
    assert put.status_code == 409
    moved = copy.deepcopy(state); moved['deals'][0]['step'] = 's15'
    put = client.put('/api/stand/state', json={'version': saved.json['version'], 'data': moved})
    assert put.status_code == 409
    assert snapshot(client)['data']['deals'][0]['step'] == 's14'


def test_matching_issued_document_account_does_not_need_acknowledgment(monkeypatch):
    state = board()
    issued_payto = (
        'ООО «ЭМ ЭФ КОРПОРЕЙШН» · ИНН 9909726886 · КПП 770387001 · Test Bank · '
        'р/с 40702810900000012345 · к/с 30101810000000000000 · БИК 044525225')
    state['deals'][0]['docFields']['payTo'] = issued_payto
    state['deals'][0]['issuedDocPayTo'] = issued_payto
    client = seed(monkeypatch, state)
    monkeypatch.setattr(m, 'current_role', lambda: 'manager')

    # The browser cannot rewrite either the issued snapshot or its editable
    # source field through an ordinary board PUT after package issuance.
    current = snapshot(client)
    forged = copy.deepcopy(current['data'])
    forged['deals'][0]['issuedDocPayTo'] = 'Test Bank · 40702810900000012345'
    forged['deals'][0]['docFields']['payTo'] = 'Test Bank · 40702810900000012345'
    rejected = client.put('/api/stand/state', json={'version': current['version'], 'data': forged})
    assert rejected.status_code == 409
    assert snapshot(client)['data']['deals'][0]['issuedDocPayTo'] == issued_payto

    monkeypatch.setattr(m, 'current_role', lambda: 'operator')
    data = payload(); data['documentsAcknowledged'] = False
    response = client.post('/api/stand/manual-bank-receipt', json=data)
    assert response.status_code == 200, response.json
    assert response.json['receipt']['documentMismatch'] is False
    assert response.json['receipt']['documentsAcknowledged'] is False
    assert response.json['data']['deals'][0]['manualBankReceipt']['documentPayToAtRequest'] == issued_payto


def test_operator_confirmation_creates_immutable_manual_provenance(monkeypatch):
    client = seed(monkeypatch, board())
    monkeypatch.setattr(m, 'current_role', lambda: 'operator')
    pending = client.post('/api/stand/manual-bank-receipt', json=payload()).json
    monkeypatch.setattr(m, 'current_role', lambda: 'manager')
    self_confirm = client.post('/api/stand/manual-bank-receipt/9301/confirm',
                               json={'version': pending['version'], 'statementVerified': True})
    assert self_confirm.status_code == 403
    monkeypatch.setattr(m, 'current_role', lambda: 'operator')
    second_request = client.post('/api/stand/manual-bank-receipt', json=payload(pending['version']))
    assert second_request.status_code == 409
    refused = client.post('/api/stand/manual-bank-receipt/9301/confirm',
                          json={'version': pending['version']})
    assert refused.status_code == 400
    confirmed = client.post('/api/stand/manual-bank-receipt/9301/confirm',
                            json={'version': pending['version'], 'statementVerified': True})
    assert confirmed.status_code == 200, confirmed.json
    state = confirmed.json['data']; deal = state['deals'][0]; income = state['incomes'][0]
    receipt = deal['manualBankReceipt']
    assert receipt['status'] == 'confirmed' and receipt['confirmedRole'] == 'operator'
    assert receipt['confirmedBy'] and receipt['confirmedAt']
    assert income['source'] == 'manual_confirmed' and income['demo'] is False
    assert income['manualReceiptId'] == receipt['id']
    assert m._stand_close_fact_source(state, deal, 'payin') == ('manual_bank_confirmed', None)
    duplicate = client.post('/api/stand/manual-bank-receipt/9301/confirm',
                            json={'version': confirmed.json['version'], 'statementVerified': True})
    assert duplicate.status_code == 409
    assert len(snapshot(client)['data']['incomes']) == 1

    forged = copy.deepcopy(state); forged['incomes'][0]['rub'] = 1
    rejected = client.put('/api/stand/state', json={'version': confirmed.json['version'], 'data': forged})
    assert rejected.status_code == 409
    forged_parts = copy.deepcopy(state); forged_parts['deals'][0]['payinParts'] = []
    rejected = client.put('/api/stand/state', json={'version': confirmed.json['version'], 'data': forged_parts})
    assert rejected.status_code == 409
    mixed = copy.deepcopy(state)
    mixed['deals'][0]['payinParts'].append({'incId': 99, 'amountRub': 1, 'demo': True})
    mixed['incomes'].append({'id': 99, 'dealId': 9301, 'rub': 1, 'demo': True})
    rejected = client.put('/api/stand/state', json={'version': confirmed.json['version'], 'data': mixed})
    assert rejected.status_code == 409

    monkeypatch.setattr(m, 'current_role', lambda: 'manager')
    current = snapshot(client)
    stage15 = copy.deepcopy(current['data'])
    stage15['deals'][0].update(step='s15', reqTask='open')
    moved = client.put('/api/stand/state', json={'version': current['version'], 'data': stage15})
    assert moved.status_code == 200, moved.json
    stage18 = copy.deepcopy(moved.json['data'])
    stage18['deals'][0].update(step='s18', reqTask='done',
        payTo={'dev': 'Client', 'bank': 'Client Bank', 'acc': '123456789',
               'purpose': 'Payout', 'amount': 9987.50})
    dispatched = client.put('/api/stand/state', json={'version': moved.json['version'], 'data': stage18})
    assert dispatched.status_code == 200, dispatched.json
    assert dispatched.json['data']['deals'][0]['step'] == 's18'
    evidence = client.post('/api/stand/deals/9301/close-evidence',
        json={'version': dispatched.json['version'], 'kind': 'payin'})
    assert evidence.status_code == 200, evidence.json
    assert evidence.json['provenance'] == 'manual_bank_confirmed'


def test_operator_can_initiate_request_and_confirmation_rejects_unexpected_parts(monkeypatch):
    client = seed(monkeypatch, board())
    monkeypatch.setattr(m, 'current_role', lambda: 'operator')
    pending = client.post('/api/stand/manual-bank-receipt', json=payload()).json
    assert pending['success']
    receipt = pending['receipt']
    assert receipt['requestedRole'] == 'operator'
    with m.get_session() as db:
        state = json.loads(m._stand_row(db).data)
    state['deals'][0]['payinParts'] = [{'incId': 82, 'amountRub': 10, 'demo': True}]
    state['deals'][0]['incomeAmount'] = 10
    state['incomes'].append({'id': 82, 'dealId': 9301, 'rub': 10, 'demo': True})
    # Сымитировать непредвиденную запись в хранилище: endpoint всё равно останавливает сверку.
    db = m.get_session()
    try:
        row = m._stand_row(db); row.data = json.dumps(state); row.version = pending['version']; db.commit()
    finally:
        db.close()
    refused = client.post('/api/stand/manual-bank-receipt/9301/confirm',
        json={'version': pending['version'], 'statementVerified': True})
    assert refused.status_code == 409
    assert 'другие приходы' in refused.json['error']


def test_operator_can_record_then_confirm_after_statement_review(monkeypatch):
    client = seed(monkeypatch, board())
    monkeypatch.setattr(m, 'current_role', lambda: 'operator')
    pending = client.post('/api/stand/manual-bank-receipt', json=payload())
    assert pending.status_code == 200, pending.json
    assert pending.json['receipt']['requestedRole'] == 'operator'
    confirmed = client.post('/api/stand/manual-bank-receipt/9301/confirm',
        json={'version': pending.json['version'], 'statementVerified': True})
    assert confirmed.status_code == 200, confirmed.json
    receipt = confirmed.json['data']['deals'][0]['manualBankReceipt']
    assert receipt['requestedRole'] == 'operator' and receipt['confirmedRole'] == 'operator'


def test_manual_request_notification_is_created_and_delivery_runs_after_commit(monkeypatch):
    client = seed(monkeypatch, board())
    monkeypatch.setattr(m, 'current_role', lambda: 'operator')
    calls = []
    def deliver():
        # Confirm state persistence precedes external notification delivery.
        calls.append(snapshot(client)['data']['deals'][0]['manualBankReceipt']['status'])
        return [{'note_id': 'placeholder', 'status': 'sent'}]
    monkeypatch.setattr(m, '_stand_deliver_notes', deliver)
    response = client.post('/api/stand/manual-bank-receipt', json=payload())
    assert response.status_code == 200
    assert calls == ['pending']
    note = next(n for n in response.json['data']['notes'] if n['role'] == 'operator')
    assert note['id'].startswith('stand:manual-bank-receipt:9301:')


def test_manual_source_must_match_operator_stamp_for_rub_batch():
    receipt = {'id': 'r-1', 'status': 'confirmed', 'actualAmount': 9987.50,
               'confirmedBy': 4, 'confirmedAt': '2026-10-01T10:00:00Z'}
    state = {'deals': [{'id': 1, 'cnvId': 1, 'incomeAmount': 9987.50,
                        'payinParts': [{'incId': 5, 'amountRub': 9987.50}],
                        'manualBankReceipt': receipt, 'step': 's22', 'postConv': 'keep',
                        'transfer': {'amount': 0}}],
             'incomes': [{'id': 5, 'rub': 9987.50, 'dealId': 1,
                          'source': 'manual_confirmed', 'manualReceiptId': 'r-1'}],
             'convs': [{'id': 1, 'sources': [{'dealId': 1, 'rub': 9987.50}], 'txs': []}]}
    assert check_batch(state, state['convs'][0]) is None
    state['deals'][0]['manualBankReceipt']['status'] = 'pending'
    assert 'не подтверждён' in check_batch(state, state['convs'][0])


def test_ordinary_put_cannot_relabel_existing_sber_income_as_manual():
    before = {'deals': [], 'incomes': [{'id': 5, 'rub': 100, 'source': 'sber'}], 'convs': []}
    after = copy.deepcopy(before)
    after['incomes'][0].update(source='manual_confirmed', manualReceiptId='fake')
    assert m._stand_guard_transition(before, after, actor='manager') == \
        'Ручной приход подтверждается только оператором'


def test_structured_receiving_account_is_locked_after_document_issue_and_manual_request():
    prior = board()
    deal = prior['deals'][0]
    deal['rubReceivingAccount'] = {'mode': 'custom', 'bank': 'Test Bank',
        'account': '40702810900000012345', 'correspondent': '30101810000000000000',
        'bik': '044525225'}
    after = copy.deepcopy(prior)
    after['deals'][0]['rubReceivingAccount']['account'] = '40702810900000099999'
    assert m._stand_guard_transition(prior, after, actor='manager') == \
        'Реквизиты для документов меняют до выпуска пакета на шаге s11'
    for status in ('pending', 'confirmed'):
        locked = copy.deepcopy(prior)
        locked['deals'][0]['manualBankReceipt'] = {'id': 'receipt-1', 'status': status}
        altered = copy.deepcopy(locked)
        altered['deals'][0]['rubReceivingAccount']['account'] = '40702810900000099999'
        assert m._stand_guard_transition(locked, altered, actor='manager') == \
            'Реквизиты для документов меняют до выпуска пакета на шаге s11'

    before_issue = board(); before_issue['deals'][0].update(step='s11', docVersion=None)
    changed = copy.deepcopy(before_issue)
    changed['deals'][0]['rubReceivingAccount'] = {'mode': 'custom', 'bank': 'Test Bank',
        'account': '40702810900000012345', 'correspondent': '30101810000000000000',
        'bik': '044525225'}
    assert m._stand_guard_transition(before_issue, changed, actor='operator') is None


def test_custom_account_form_can_save_each_field_progressively_only_on_s11(monkeypatch):
    initial = board(); initial['deals'][0].update(step='s11', docVersion=None, docPack=None)
    client = seed(monkeypatch, initial)
    monkeypatch.setattr(m, 'current_role', lambda: 'operator')
    fields = [
        {'mode': 'custom'},
        {'mode': 'custom', 'bank': 'Test Bank'},
        {'mode': 'custom', 'bank': 'Test Bank', 'account': '40702810900000012345'},
        {'mode': 'custom', 'bank': 'Test Bank', 'account': '40702810900000012345',
         'correspondent': '30101810000000000000'},
        {'mode': 'custom', 'bank': 'Test Bank', 'account': '40702810900000012345',
         'correspondent': '30101810000000000000', 'bik': '044525225'},
    ]
    version = 7
    for ix, account in enumerate(fields):
        current = snapshot(client)['data']
        current['deals'][0]['rubReceivingAccount'] = account
        saved = client.put('/api/stand/state', json={'version': version, 'data': current})
        assert saved.status_code == 200, saved.json
        version = saved.json['version']
        if ix == 0:
            incomplete = snapshot(client)['data']; incomplete['deals'][0]['step'] = 's12'
            blocked = client.put('/api/stand/state', json={'version': version, 'data': incomplete})
            assert blocked.status_code == 409
    refreshed = snapshot(client)['data']['deals'][0]['rubReceivingAccount']
    assert refreshed == fields[-1]
    current = snapshot(client)['data']; current['deals'][0]['step'] = 's12'
    moved = client.put('/api/stand/state', json={'version': version, 'data': current})
    assert moved.status_code == 200, moved.json


def test_flowsole_existing_state_switches_without_database_rewrite(monkeypatch):
    initial = board()
    deal = initial['deals'][0]
    deal.update(step='s11', docVersion=None, docPack=None,
                rubReceivingAccount={'mode': 'flowsole'})
    original = copy.deepcopy(initial)
    client = seed(monkeypatch, initial)
    monkeypatch.setattr(m, 'current_role', lambda: 'operator')
    saved = snapshot(client)
    assert saved['data'] == m._stand_strip_files(original)
    changed = saved['data']
    changed['deals'][0]['rubReceivingAccount'] = {'mode': 'sber'}
    response = client.put('/api/stand/state', json={'version': saved['version'], 'data': changed})
    assert response.status_code == 200, response.json
    changed = response.json['data']
    changed['deals'][0]['rubReceivingAccount'] = {'mode': 'flowsole'}
    response = client.put('/api/stand/state', json={'version': response.json['version'], 'data': changed})
    assert response.status_code == 200, response.json


def test_custom_recipient_fields_save_but_partial_recipient_cannot_leave_s11(monkeypatch):
    initial = board()
    initial['deals'][0].update(step='s11', docVersion=None, docPack=None)
    client = seed(monkeypatch, initial)
    monkeypatch.setattr(m, 'current_role', lambda: 'operator')
    changed = snapshot(client)
    changed['data']['deals'][0]['rubReceivingAccount'].update(
        recipientName='ООО ТЕСТ', recipientInn='7700000000', recipientKpp='770101001')
    saved = client.put('/api/stand/state', json=changed)
    assert saved.status_code == 200, saved.json
    changed = saved.json
    changed['data']['deals'][0]['rubReceivingAccount']['recipientInn'] = ''
    changed['data']['deals'][0]['step'] = 's12'
    rejected = client.put('/api/stand/state', json=changed)
    assert rejected.status_code == 409
    assert 'ИНН' in rejected.json['error']


def test_flowsole_receipt_uses_preset_despite_stale_sber_expect(monkeypatch):
    initial = board()
    deal = initial['deals'][0]
    deal['rubReceivingAccount'] = {'mode': 'flowsole'}
    deal['docFields']['payTo'] = ('ФЛОУ СОЛЕ КО., ЛТД · Московский филиал "БАНК СГБ" г. Москва '
                                  '· р/с 40807810819000000261 · к/с 30101810245250000094 · БИК 044525094')
    client = seed(monkeypatch, initial)
    monkeypatch.setattr(m, 'current_role', lambda: 'operator')
    request = payload()
    request.update(bank='Московский филиал "БАНК СГБ" г. Москва',
                   account='40807810819000000261', documentsAcknowledged=False)
    saved = client.post('/api/stand/manual-bank-receipt', json=request)
    assert saved.status_code == 200, saved.json
    assert saved.json['receipt']['documentMismatch'] is False
    monkeypatch.setattr(m, 'current_role', lambda: 'operator')
    confirmed = client.post('/api/stand/manual-bank-receipt/9301/confirm', json={
        'version': saved.json['version'], 'statementVerified': True})
    assert confirmed.status_code == 200, confirmed.json
    assert confirmed.json['data']['deals'][0]['manualBankReceipt']['status'] == 'confirmed'


def test_1485_handoff_operator_selects_flowsole_and_acknowledges_documents(monkeypatch):
    initial = board()
    deal = initial['deals'][0]
    deal.update(id=1485, code='SYN-1485', docVersion=3, rubReceivingAccount=None,
                issuedDocPayTo='ООО «ЭМ ЭФ КОРПОРЕЙШН» · ПАО Сбербанк · р/с 40807810938720000286')
    client = seed(monkeypatch, initial)
    monkeypatch.setattr(m, 'current_role', lambda: 'operator')
    handoff = client.post('/api/stand/manual-bank-receipt', json={
        'version': 7, 'dealId': 1485, 'handoff': True})
    assert handoff.status_code == 200, handoff.json
    pending = handoff.json['data']['deals'][0]
    assert pending['rubReceivingAccount'] is None
    assert pending['docVersion'] == 3
    assert pending['manualBankReceipt']['status'] == 'pending'
    assert pending['manualBankReceipt'].get('bank') is None

    monkeypatch.setattr(m, 'current_role', lambda: 'operator')
    actual = {'version': handoff.json['version'], 'statementVerified': True,
              'actualMode': 'flowsole', 'actualAmount': '9987.50',
              'payer': 'Иван Клиент', 'bankPurpose': 'Оплата по договору',
              'statementDate': '2026-10-01', 'statementRef': 'строка 7788'}
    without_ack = client.post('/api/stand/manual-bank-receipt/1485/confirm', json=actual)
    assert without_ack.status_code == 409
    assert 'расхождение' in without_ack.json['error']
    assert snapshot(client)['data']['incomes'] == []
    actual['deviationAcknowledged'] = True
    confirmed = client.post('/api/stand/manual-bank-receipt/1485/confirm', json=actual)
    assert confirmed.status_code == 200, confirmed.json
    saved = confirmed.json['data']['deals'][0]
    receipt = saved['manualBankReceipt']
    assert saved['rubReceivingAccount'] is None
    assert receipt['bank'] == 'Московский филиал "БАНК СГБ" г. Москва'
    assert receipt['account'] == '40807810819000000261'
    assert receipt['bankBik'] == '044525094'
    assert receipt['correspondentAccount'] == '30101810245250000094'
    assert receipt['accountMismatch'] is True
    assert receipt['documentMismatch'] is True
    assert receipt['documentsAcknowledged'] is True
    assert 'расхождение' in saved['log'][-1]['text']
    assert confirmed.json['data']['incomes'][0]['source'] == 'manual_confirmed'


@pytest.mark.parametrize('mode,number', [
    ('sber', '40807810938720000286'),
    ('acquiring', '…2118'),
    ('tbank', '…5510'),
    ('flowsole', '40807810819000000261'),
])
def test_operator_actual_account_presets_are_server_selected(monkeypatch, mode, number):
    initial = board()
    initial['deals'][0].update(docVersion=None, docPack=None)
    client = seed(monkeypatch, initial)
    monkeypatch.setattr(m, 'current_role', lambda: 'operator')
    handoff = client.post('/api/stand/manual-bank-receipt', json={
        'version': 7, 'dealId': 9301, 'handoff': True})
    monkeypatch.setattr(m, 'current_role', lambda: 'operator')
    actual = {'version': handoff.json['version'], 'statementVerified': True,
              'actualMode': mode, 'bank': 'Подменённый банк', 'account': '99999999999999999999',
              'actualAmount': '9987.50', 'payer': 'Иван Клиент',
              'bankPurpose': 'Оплата по договору', 'statementDate': '2026-10-01',
              'statementRef': 'строка 7788', 'deviationAcknowledged': True}
    confirmed = client.post('/api/stand/manual-bank-receipt/9301/confirm', json=actual)
    assert confirmed.status_code == 200, confirmed.json
    receipt = confirmed.json['data']['deals'][0]['manualBankReceipt']
    assert receipt['account'] == number
    assert receipt['bank'] != 'Подменённый банк'


def test_operator_custom_actual_account_needs_full_requisites(monkeypatch):
    initial = board()
    initial['deals'][0].update(docVersion=None, docPack=None)
    client = seed(monkeypatch, initial)
    monkeypatch.setattr(m, 'current_role', lambda: 'operator')
    handoff = client.post('/api/stand/manual-bank-receipt', json={
        'version': 7, 'dealId': 9301, 'handoff': True})
    monkeypatch.setattr(m, 'current_role', lambda: 'operator')
    actual = {'version': handoff.json['version'], 'statementVerified': True,
              'actualMode': 'custom', 'bank': 'Test Bank',
              'account': '40702810900000012345', 'correspondent': '30101810000000000000',
              'bik': '123', 'actualAmount': '9987.50', 'payer': 'Иван Клиент',
              'bankPurpose': 'Оплата по договору', 'statementDate': '2026-10-01',
              'statementRef': 'строка 7788', 'deviationAcknowledged': True}
    invalid = client.post('/api/stand/manual-bank-receipt/9301/confirm', json=actual)
    assert invalid.status_code == 400
    actual['bik'] = '044525225'
    incomplete = client.post('/api/stand/manual-bank-receipt/9301/confirm', json=actual)
    assert incomplete.status_code == 400
    actual.update(recipientName='ООО ТЕСТ', recipientInn='7700000000', recipientKpp='770101001')
    confirmed = client.post('/api/stand/manual-bank-receipt/9301/confirm', json=actual)
    assert confirmed.status_code == 200, confirmed.json
    assert confirmed.json['data']['deals'][0]['manualBankReceipt']['bankBik'] == '044525225'


def test_manager_cannot_rewrite_expected_account_at_s14():
    prior = board()
    changed = copy.deepcopy(prior)
    changed['deals'][0]['expect']['acc'] = '…0261 · СГБ (Flow Sole)'
    assert 'Ожидаемый счёт' in m._stand_guard_transition(prior, changed, actor='manager')


@pytest.mark.parametrize('mode', ['flowsole', 'custom'])
def test_operator_manual_receipt_requires_bank_file(monkeypatch, mode):
    state = board()
    deal = state['deals'][0]
    deal['rubReceivingAccount'] = {'mode': 'flowsole'} if mode == 'flowsole' else deal['rubReceivingAccount']
    deal['files'] = {}
    client = seed(monkeypatch, state)
    monkeypatch.setattr(m, 'current_role', lambda: 'manager')
    assert client.post('/api/stand/manual-bank-receipt', json={
        'version': 7, 'dealId': 9301, 'handoff': True}).status_code == 403
    assert client.post('/api/stand/manual-bank-receipt', json=payload()).status_code == 403

    monkeypatch.setattr(m, 'current_role', lambda: 'operator')
    pending = client.post('/api/stand/manual-bank-receipt', json={
        'version': 7, 'dealId': 9301, 'handoff': True})
    assert pending.status_code == 200, pending.json
    actual = {'version': pending.json['version'], 'statementVerified': True,
              'actualMode': mode, 'actualAmount': '9987.50', 'payer': 'Иван Клиент',
              'bankPurpose': 'Оплата по договору', 'statementDate': '2026-10-01',
              'statementRef': 'строка 7788', 'deviationAcknowledged': True}
    if mode == 'custom':
        actual.update(bank='Test Bank', account='40702810900000012345',
                      correspondent='30101810000000000000', bik='044525225',
                      recipientName='ООО ТЕСТ', recipientInn='7700000000', recipientKpp='770101001')
    missing = client.post('/api/stand/manual-bank-receipt/9301/confirm', json=actual)
    assert missing.status_code == 409
    assert 'выписку' in missing.json['error'].lower()

    with client.session_transaction() as session:
        uid = session['user_id']
    current = snapshot(client)
    entry = board()['deals'][0]['files']['bankCreditEvidence'][0]
    entry['uploadedById'] = uid
    entry['data'] = board()['deals'][0]['files']['bankCreditEvidence'][0]['data']
    current['data']['deals'][0]['files']['bankCreditEvidence'] = [dict(entry, mime='text/html')]
    invalid_file = client.put('/api/stand/state', json=current)
    assert invalid_file.status_code == 409
    files = [entry]
    if mode == 'flowsole':
        files.append(dict(entry, id='bce_abcdef123456', file='statement-second.pdf'))
    current['data']['deals'][0]['files']['bankCreditEvidence'] = files
    current['data']['deals'][0]['log'].append({
        'text': 'Выписка о зачислении прикреплена · statement.pdf · Synthetic'})
    if len(files) == 2:
        current['data']['deals'][0]['log'].append({
            'text': 'Выписка о зачислении прикреплена · statement-second.pdf · Synthetic'})
    uploaded = client.put('/api/stand/state', json=current)
    assert uploaded.status_code == 200, uploaded.json
    actual['version'] = uploaded.json['version']
    confirmed = client.post('/api/stand/manual-bank-receipt/9301/confirm', json=actual)
    assert confirmed.status_code == 200, confirmed.json
    assert confirmed.json['data']['incomes'][0]['source'] == 'manual_confirmed'
    assert len(confirmed.json['data']['deals'][0]['files']['bankCreditEvidence']) == len(files)
    assert confirmed.json['data']['deals'][0]['files']['bankCreditEvidence'][0]['data'] == '__detached__'
    assert confirmed.json['data']['deals'][0]['files'].get('clientPayinReceipt') is None


def test_sber_api_route_and_old_demo_state(monkeypatch):
    state = board()
    state['deals'][0].update(rubReceivingAccount={'mode': 'sber'}, demoTransfers=True)
    state['incomes'].append({'id': 55, 'rub': 10, 'demo': True, 'dealId': None})
    client = seed(monkeypatch, state)
    monkeypatch.setattr(m, 'current_role', lambda: 'operator')
    assert m._stand_rub_api_account(state['deals'][0])
    manual = client.post('/api/stand/manual-bank-receipt', json=payload())
    assert manual.status_code == 409
    assert 'API' in manual.json['error']
    shown = snapshot(client)
    assert shown['data']['deals'][0]['demoTransfers'] is True
    assert shown['data']['incomes'][0]['demo'] is True
