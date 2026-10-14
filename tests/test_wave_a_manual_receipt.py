import copy
from datetime import datetime
import pytest
import app as m
from tests.test_stand_manual_bank_receipt import board, seed, snapshot


@pytest.mark.parametrize('mode', ['custom', 'flowsole'])
def test_manual_receipt_only_amount_and_statement_required(monkeypatch, mode):
    state = board()
    if mode == 'flowsole': state['deals'][0]['rubReceivingAccount'] = {'mode': 'flowsole'}
    client = seed(monkeypatch, state)
    monkeypatch.setattr(m, 'current_role', lambda: 'operator')
    pending = client.post('/api/stand/manual-bank-receipt', json={'version': snapshot(client)['version'], 'dealId': 9301, 'handoff': True})
    response = client.post('/api/stand/manual-bank-receipt/9301/confirm', json={'version': pending.json['version'], 'actualAmount': '10000'})
    assert response.status_code == 200, response.json
    deal = response.json['data']['deals'][0]
    receipt = deal['manualBankReceipt']
    assert receipt['status'] == 'confirmed'
    assert receipt['statementDate'] == datetime.now().date().isoformat()
    assert not receipt['payer'] and not receipt['statementRef']
    assert deal['step'] == 's18'
    assert receipt['account'] == ('40807810819000000261' if mode == 'flowsole' else '40702810900000012345')


@pytest.mark.parametrize('amount,evidence,date', [(None, True, None), ('0', True, None), ('-1', True, None), ('10000.001', True, None), ('10000', False, None), ('10000', True, 'invalid')])
def test_manual_receipt_amount_file_and_date_validation(monkeypatch, amount, evidence, date):
    state = board()
    if not evidence: state['deals'][0]['files'] = {}
    client = seed(monkeypatch, state)
    monkeypatch.setattr(m, 'current_role', lambda: 'operator')
    pending = client.post('/api/stand/manual-bank-receipt', json={'version': snapshot(client)['version'], 'dealId': 9301, 'handoff': True})
    response = client.post('/api/stand/manual-bank-receipt/9301/confirm', json={'version': pending.json['version'], 'actualAmount': amount, 'statementDate': date})
    assert response.status_code in (400,409), response.json
    assert snapshot(client)['data']['deals'][0]['step'] == 's14'


def test_other_account_is_explicit_and_logged_without_checkbox(monkeypatch):
    client = seed(monkeypatch, board())
    monkeypatch.setattr(m, 'current_role', lambda: 'operator')
    pending = client.post('/api/stand/manual-bank-receipt', json={'version': snapshot(client)['version'], 'dealId': 9301, 'handoff': True})
    response = client.post('/api/stand/manual-bank-receipt/9301/confirm', json={'version': pending.json['version'], 'actualAmount': '10000', 'actualMode': 'flowsole'})
    assert response.status_code == 200, response.json
    deal = response.json['data']['deals'][0]
    assert deal['rubReceivingAccount']['mode'] == 'custom'
    assert any('Пришло на другой счёт' in x['text'] and '40807810819000000261' in x['text'] for x in deal['log'])
