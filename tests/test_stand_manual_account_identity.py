"""QA 29.10 (TC-10→TC-11): ручной приход на реквизиты Сбера по режиму «по реквизитам» не уходил брокеру (409)."""
import copy
import json
import time
import uuid

import pytest

import app as m
import stand_funding
from tests.test_stand_manual_bank_receipt import board, seed, snapshot

SBER_BIK = '044525225'
SBER_ACCOUNT = '40807810938720000286'
SBER_CORR = '30101810400000000225'
FLOWSOLE_BIK = '044525094'
FLOWSOLE_ACCOUNT = '40807810819000000261'


def _sber_custom_board():
    """Сделка на s14, реквизиты получателя заданы вручную, но это Сбер MF Corp."""
    state = board()
    deal = state['deals'][0]
    deal['rubReceivingAccount'] = {'mode': 'custom', 'bank': 'ПАО Сбербанк',
        'account': SBER_ACCOUNT, 'correspondent': SBER_CORR, 'bik': SBER_BIK}
    deal['expect'] = {'acc': '…0286 · Сбер', 'bank': 'ПАО Сбербанк',
        'account': SBER_ACCOUNT, 'amount': 10000, 'tol': 1000}
    state['wallets'] = [{'id': 'grusha', 'role': 'findir', 'multisig': True,
        'addr': 'TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn'}]
    return state


@pytest.fixture
def batch_env(monkeypatch):
    for name in ('send_deal_completed_webhook', 'notify_agents_new_deal',
                 'sync_deals_to_gsheet', 'sync_referrer_reward_to_gsheet',
                 '_send_deal_telegram', '_stand_deliver_notes',
                 '_tron_tx_amount', '_tron_tx_to_address'):
        monkeypatch.setattr(m, name, lambda *args, **kwargs: None)
    monkeypatch.setattr(m, 'CONVERSIONS_LAUNCH_DATE', '2026-01-01')
    monkeypatch.setattr(m, 'current_role', lambda: 'operator')


def _confirm_custom_sber_receipt(client):
    """Операционист подтверждает приход на Сбер, указанный вручную (TC-10)."""
    pending = client.post('/api/stand/manual-bank-receipt', json={
        'version': snapshot(client)['version'], 'dealId': 9301, 'handoff': True})
    assert pending.status_code == 200, pending.json
    confirmed = client.post('/api/stand/manual-bank-receipt/9301/confirm', json={
        'version': pending.json['version'], 'statementVerified': True,
        'actualMode': 'custom', 'bank': 'ПАО Сбербанк', 'account': SBER_ACCOUNT,
        'correspondent': SBER_CORR, 'bik': SBER_BIK,
        'recipientName': 'ООО «ЭМ ЭФ КОРПОРЕЙШН»', 'recipientInn': '9909726886', 'recipientKpp': '770387001',
        'actualAmount': '10000', 'payer': 'Иван Клиент', 'bankPurpose': 'Оплата по договору',
        'statementDate': '2026-10-13', 'statementRef': 'операция 7788'})
    assert confirmed.status_code == 200, confirmed.json
    return confirmed.json['data']['deals'][0]['manualBankReceipt']['id']


def _batch_proposal(current, sent_ts, extra_sources=()):
    """Пачка брокеру: источник — сделка 9301 с подтверждённым приходом."""
    proposal = copy.deepcopy(current)
    task = proposal['deals'][0]
    task.update(step='s18w', cnvId=1, walletId='grusha')
    task.setdefault('rates', {})['broker'] = '100'
    for income in proposal['incomes']:
        if income.get('source') == 'manual_confirmed':
            income['cnvId'] = 1
    sources = [{'dealId': 9301, 'rub': 10000, 'clientRub': 10000, 'usdt': 99.30, 'bankNet': False}]
    sources.extend(extra_sources)
    proposal['convs'] = [{'id': 1, 'broker': 'Test', 'requestNo': '41', 'rate': '100',
        'status': 'sent', 'at': 'test, now', 'sentTs': sent_ts, 'walletId': 'grusha',
        'rubTotal': 10000, 'clientRubTotal': 10000, 'held': 70, 'sent': 9930,
        'feePct': .3, 'feeFix': 40, 'feeCtrl': 50, 'feeOurs': 20,
        'feeCtrlPct': .1, 'feeOursPct': .2, 'sources': sources, 'txs': []}]
    return proposal


def test_identity_custom_sber_requisites_resolve_to_preset():
    receipt = {'actualMode': 'custom', 'bankBik': SBER_BIK, 'account': SBER_ACCOUNT}
    assert m._stand_manual_account_key(receipt) == 'sber'


def test_identity_custom_flowsole_requisites_resolve_to_preset():
    receipt = {'actualMode': 'custom', 'bankBik': FLOWSOLE_BIK, 'account': FLOWSOLE_ACCOUNT}
    assert m._stand_manual_account_key(receipt) == 'flow_sole'


def test_identity_other_custom_account_keeps_other_key():
    receipt = {'actualMode': 'custom', 'bankBik': SBER_BIK, 'account': '40702810900000012345'}
    assert m._stand_manual_account_key(receipt) == 'other:40702810900000012345'


def test_identity_same_account_other_bik_is_not_sber():
    receipt = {'actualMode': 'custom', 'bankBik': '044525999', 'account': SBER_ACCOUNT}
    assert m._stand_manual_account_key(receipt) == 'other:' + SBER_ACCOUNT


def test_both_sides_agree_for_custom_sber_receipt():
    receipt = {'actualMode': 'custom', 'status': 'confirmed', 'confirmedAt': 'x', 'confirmedBy': 1,
               'bankBik': SBER_BIK, 'account': SBER_ACCOUNT}
    deal = {'manualBankReceipt': receipt, 'rubReceivingAccount': {'mode': 'custom', 'bik': SBER_BIK,
            'account': SBER_ACCOUNT, 'correspondent': SBER_CORR}}
    mirror = {'source': 'manual_confirmed', 'accountKey': m._stand_manual_account_key(receipt)}
    row_identity = m.account_identity(m._stand_manual_account_key(receipt))
    assert stand_funding.income_account_identity(mirror, deal) == row_identity == 'sber'


def test_qa_tc10_tc11_custom_sber_receipt_goes_to_broker(batch_env, monkeypatch):
    client = seed(monkeypatch, _sber_custom_board())
    _confirm_custom_sber_receipt(client)
    before = snapshot(client)
    proposal = _batch_proposal(before['data'], int(time.time() * 1000) - 60000)
    response = client.put('/api/stand/state', json={'version': before['version'], 'data': proposal})
    assert response.status_code == 200, response.json
    assert response.json['data']['convs'][0]['crmConversionId']
    db = m.get_session()
    try:
        row = db.query(m.SberIncome).filter_by(uuid='manual:' + response.json['data']['deals'][0]['manualBankReceipt']['id']).one()
        assert row.account_key == 'sber'
    finally:
        db.close()


def test_previously_confirmed_other_key_record_still_goes_to_broker(batch_env, monkeypatch):
    """Приход, подтверждённый до фикса: в БД и в зеркале стоит other:<счёт>. Миграция не нужна."""
    client = seed(monkeypatch, _sber_custom_board())
    receipt_id = _confirm_custom_sber_receipt(client)
    legacy_key = 'other:' + SBER_ACCOUNT
    db = m.get_session()
    try:
        db.query(m.SberIncome).filter_by(uuid='manual:' + receipt_id).update({'account_key': legacy_key})
        db.commit()
    finally:
        db.close()
    db = m.get_session()
    try:
        # Состояние, записанное до фикса: API не даёт менять подтверждённый приход, пишем напрямую.
        row = m._stand_row(db)
        stored = json.loads(row.data)
        for income in stored['incomes']:
            if income.get('source') == 'manual_confirmed':
                income['accountKey'] = legacy_key
        for part in stored['deals'][0]['payinParts']:
            if part.get('manualReceiptId'):
                part['accountKey'] = legacy_key
        row.data = json.dumps(stored, ensure_ascii=False)
        row.version = (row.version or 0) + 1
        db.commit()
    finally:
        db.close()
    current = snapshot(client)
    proposal = _batch_proposal(current['data'], int(time.time() * 1000) - 60000)
    response = client.put('/api/stand/state', json={'version': current['version'], 'data': proposal})
    assert response.status_code == 200, response.json
    assert response.json['data']['convs'][0]['crmConversionId']


def test_different_real_accounts_still_cannot_share_one_batch(batch_env, monkeypatch):
    client = seed(monkeypatch, _sber_custom_board())
    _confirm_custom_sber_receipt(client)
    db = m.get_session()
    other_uuid = 'neg-' + uuid.uuid4().hex
    try:
        other = m.SberIncome(uuid=other_uuid, operation_date='2026-10-13', amount_rub=5000,
                             account_key='other:40702810900000012345')
        db.add(other); db.flush(); other_id = other.id
        db.commit()
    finally:
        db.close()
    before = snapshot(client)
    extra = {'dealId': None, 'crmIncomeId': other_id, 'clientRub': 5000,
             'incomeId': 'sber:' + other_uuid, 'rub': 5000, 'usdt': 49.65}
    proposal = _batch_proposal(before['data'], int(time.time() * 1000) - 60000, [extra])
    proposal['deals'][0]['brokerCrmDraftIds'] = [other_id]
    proposal['incomes'].append({'id': 'sber:' + other_uuid, 'source': 'registry',
        'accountKey': 'other:40702810900000012345', 'rub': 5000, 'grossRub': 5000,
        'dealId': None, 'cnvId': 1, 'batchRub': 5000})
    response = client.put('/api/stand/state', json={'version': before['version'], 'data': proposal})
    assert response.status_code == 409, response.json
    assert 'разных счет' in response.json['error'].lower()
    db = m.get_session()
    try:
        db.query(m.SberIncome).filter_by(uuid=other_uuid).delete()
        db.commit()
    finally:
        db.close()
