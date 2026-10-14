"""Bank account isolation for RUB receipts and broker conversions."""
import copy
import uuid
from io import BytesIO

import app as m
import pytest
from tests.test_stand_manual_bank_receipt import board, seed, snapshot


def test_conversion_rejects_mixed_accounts_even_with_force(monkeypatch):
    monkeypatch.setenv('LOCAL_NO_AUTH', '1')
    db = m.get_session()
    ids = []
    try:
        for key in ('sber', 'flow_sole'):
            row = m.SberIncome(uuid=uuid.uuid4().hex, operation_date='2026-10-14',
                amount_rub=10000, account_key=key)
            db.add(row); db.flush(); ids.append(row.id)
        db.commit()
        client = m.app.test_client()
        payload = {'broker': 'test', 'rate_rub_usdt': 100, 'force': True,
            'sources': [{'sber_income_id': i, 'amount_rub': 10000} for i in ids]}
        response = client.post('/api/conversions', json=payload)
        assert response.status_code == 409
        assert 'разных счет' in response.json['error'].lower()
    finally:
        db.query(m.ConversionSource).filter(m.ConversionSource.sber_income_id.in_(ids)).delete(synchronize_session=False)
        db.query(m.SberIncome).filter(m.SberIncome.id.in_(ids)).delete(synchronize_session=False)
        db.commit(); db.close()


@pytest.mark.parametrize('mode,key', [
    ('flowsole', 'flow_sole'),
    ('custom', 'other:40702810900000012345'),
])
def test_s14_manual_receipt_enters_shared_registry(monkeypatch, mode, key):
    state = board()
    if mode == 'flowsole':
        state['deals'][0]['rubReceivingAccount'] = {'mode': 'flowsole'}
    client = seed(monkeypatch, state)
    monkeypatch.setattr(m, 'current_role', lambda: 'operator')
    pending = client.post('/api/stand/manual-bank-receipt', json={
        'version': snapshot(client)['version'], 'dealId': 9301, 'handoff': True})
    response = client.post('/api/stand/manual-bank-receipt/9301/confirm', json={
        'version': pending.json['version'], 'actualAmount': '10000'})
    assert response.status_code == 200, response.json
    receipt_id = response.json['data']['deals'][0]['manualBankReceipt']['id']
    db = m.get_session()
    try:
        row = db.query(m.SberIncome).filter_by(uuid='manual:' + receipt_id).one()
        assert row.account_key == key
        assert row.amount_rub == 10000
    finally:
        db.query(m.SberIncome).filter_by(uuid='manual:' + receipt_id).delete()
        db.commit(); db.close()


def test_crm_and_s14_flowsole_share_batch_and_profit(monkeypatch):
    for name in ('send_deal_completed_webhook', 'notify_agents_new_deal',
                 'sync_deals_to_gsheet', 'sync_referrer_reward_to_gsheet',
                 '_send_deal_telegram', '_stand_deliver_notes',
                 '_tron_tx_amount', '_tron_tx_to_address'):
        monkeypatch.setattr(m, name, lambda *args, **kwargs: None)
    state = board()
    state['deals'][0]['rubReceivingAccount'] = {'mode': 'flowsole'}
    state['wallets'] = [{'id': 'grusha', 'role': 'findir', 'multisig': True,
        'addr': 'TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn'}]
    client = seed(monkeypatch, state)
    monkeypatch.setattr(m, 'current_role', lambda: 'operator')
    monkeypatch.setattr(m, 'CONVERSIONS_LAUNCH_DATE', '2026-01-01')
    pending = client.post('/api/stand/manual-bank-receipt', json={
        'version': snapshot(client)['version'], 'dealId': 9301, 'handoff': True})
    confirmed = client.post('/api/stand/manual-bank-receipt/9301/confirm', json={
        'version': pending.json['version'], 'actualAmount': '10000'})
    assert confirmed.status_code == 200, confirmed.json
    stand_uuid = 'manual:' + confirmed.json['data']['deals'][0]['manualBankReceipt']['id']
    made = client.post('/api/deals', json={
        'deal_type': 'pay_in', 'status': 'pending', 'skip_sync': True,
        'client_name': 'Flow Sole test ' + uuid.uuid4().hex[:8],
        'payin_method': 'flow_sole_reqs', 'payin_amount_rub': 20000,
        'payout_method': 'transfer', 'payout_source': 'cash_batch',
        'payout_amount_usdt': 150, 'needs_reimbursement': False})
    assert made.status_code == 201, made.json
    deal_id = made.json['deal']['id']
    missing = client.post(f'/api/deals/{deal_id}/manual-rub-income',
        data={'amount_rub': '20000'})
    assert missing.status_code == 400
    uploaded = client.post(f'/api/deals/{deal_id}/manual-rub-income', data={
        'amount_rub': '20000', 'file': (BytesIO(b'%PDF-1.4\nstatement'), 'statement.pdf')})
    assert uploaded.status_code == 200, uploaded.json
    assert uploaded.json['income']['account_key'] == 'flow_sole'
    assert uploaded.json['income']['operation_date']
    statement = client.get(f'/api/deals/{deal_id}/manual-rub-income/statement')
    assert statement.status_code == 200 and statement.data.startswith(b'%PDF-')
    db = m.get_session()
    try:
        stand = db.query(m.SberIncome).filter_by(uuid=stand_uuid).one()
        crm = db.query(m.SberIncome).filter_by(claimed_deal_id=deal_id).one()
        assert stand.account_key == crm.account_key == 'flow_sole'
        stand_id, crm_id = stand.id, crm.id
    finally:
        db.close()
    registry = client.get('/api/sber-incomes?all=1&with_conversion=1').json
    rows = {i['id']: i for i in registry['incomes']}
    assert rows[stand_id]['account_key'] == rows[crm_id]['account_key'] == 'flow_sole'
    assert rows[stand_id]['conv_state'] == rows[crm_id]['conv_state'] == 'pending'
    before = snapshot(client)
    proposal = copy.deepcopy(before['data'])
    task = proposal['deals'][0]
    task.update(step='s18w', cnvId=1, walletId='grusha')
    task.setdefault('rates', {})['broker'] = '100'
    proposal['incomes'][0]['cnvId'] = 1
    proposal['incomes'].append({'id': 'sber:' + crm.uuid, 'source': 'registry',
        'accountKey': 'flow_sole', 'rub': 20000, 'grossRub': 20000,
        'dealId': None, 'cnvId': 1, 'batchRub': 20000})
    proposal['convs'] = [{'id': 1, 'broker': 'Test', 'requestNo': '41',
        'rate': '100', 'status': 'sent', 'at': '14.10, 12:00',
        'sentTs': 1791979200000, 'walletId': 'grusha', 'accountKey': 'flow_sole',
        'rubTotal': 30000, 'held': 130, 'sent': 29870,
        'feePct': .3, 'feeFix': 40, 'feeCtrl': 70, 'feeOurs': 60,
        'feeCtrlPct': .1, 'feeOursPct': .2,
        'sources': [{'dealId': 9301, 'rub': 10000, 'usdt': 99.57, 'bankNet': False,
                     'accountKey': 'flow_sole'},
                    {'dealId': None, 'incomeId': 'sber:' + crm.uuid,
                     'rub': 20000, 'usdt': 199.13, 'accountKey': 'flow_sole'}],
        'txs': []}]
    batch = client.put('/api/stand/state', json={'version': before['version'],
        'data': proposal})
    assert batch.status_code == 200, batch.json
    conv_id = batch.json['data']['convs'][0]['crmConversionId']
    assert conv_id
    conv = client.get(f'/api/conversions/{conv_id}').json['conversion']
    assert conv['account_key'] == 'flow_sole'
    assert conv['sources_rub'] == 30000
    # Same formula as Sber: (30,000 - 0.3% - 40) / 100 = 298.70 USDT.
    assert conv['expected_usdt'] == 298.7
    received = client.post(f"/api/conversions/{conv['id']}/txs", json={
        'tx_hash': uuid.uuid4().hex + uuid.uuid4().hex, 'amount_usdt': 298.7})
    assert received.status_code == 200, received.json
    db = m.get_session()
    try:
        deal = db.get(m.Deal, deal_id)
        assert deal.payin_amount_usdt == 199.13
        assert deal.profit_usdt == 49.13
        report = client.get('/api/deals/ledger?status=all').json
        row = next(r for r in report['deals'] if r['id'] == deal_id)
        assert row['pay_in']['method'] == 'flow_sole_reqs'
        assert report['totals']['by_payin_method']['flow_sole_reqs']['label'] == m.PAYIN_METHOD_LABELS['flow_sole_reqs']
        assert report['labels']['payin_method']['flow_sole_reqs'] == m.PAYIN_METHOD_LABELS['flow_sole_reqs']
        import csv
        from io import StringIO
        exported = list(csv.DictReader(StringIO(client.get('/api/deals/ledger?status=all&format=csv')
            .data.decode('utf-8-sig')), delimiter=';'))
        assert next(r for r in exported if r['id'] == str(deal_id))['метод прихода'] == m.PAYIN_METHOD_LABELS['flow_sole_reqs']
    finally:
        db.query(m.ConversionSource).filter_by(conversion_id=conv['id']).delete()
        db.query(m.ConversionTx).filter_by(conversion_id=conv['id']).delete()
        db.query(m.Conversion).filter_by(id=conv['id']).delete()
        db.query(m.SberIncome).filter(m.SberIncome.id.in_([stand_id, crm_id])).delete(synchronize_session=False)
        db.query(m.StandFile).filter_by(deal_id=deal_id, kind='crmBankCreditEvidence').delete()
        db.query(m.Deal).filter_by(id=deal_id).delete()
        db.commit(); db.close()


def test_null_account_key_is_legacy_sber(monkeypatch):
    monkeypatch.setenv('LOCAL_NO_AUTH', '1')
    db = m.get_session()
    income = m.SberIncome(uuid=uuid.uuid4().hex, operation_date='2026-10-14',
        amount_rub=17000, account_key=None)
    db.add(income); db.flush(); income_id = income.id
    from sqlalchemy import text
    db.execute(text('UPDATE sber_incomes SET account_key = NULL WHERE id = :id'), {'id': income_id})
    db.commit(); db.close()
    client = m.app.test_client()
    rows = client.get('/api/sber-incomes?all=1').json['incomes']
    assert next(i for i in rows if i['id'] == income_id)['account_key'] == 'sber'
    db = m.get_session()
    db.query(m.SberIncome).filter_by(id=income_id).delete(); db.commit(); db.close()
