"""Поступления CRM в рублёвой пачке стенда и защита от повторного выбора."""
import copy
import json
import secrets
from decimal import Decimal

import pytest

import app as m
import stand_funding


@pytest.fixture
def sber_board(monkeypatch):
    monkeypatch.setattr(m, 'STAND_MODE', True)
    monkeypatch.setattr(m, 'CONVERSIONS_LAUNCH_DATE', '2026-01-01')
    monkeypatch.setattr(m, '_stand_deliver_notes', lambda: None)
    m._stand_migrate()
    db = m.get_session()
    try:
        user = m.AdminUser(username='s18crm_' + secrets.token_hex(5), role='operator',
                           password_hash='synthetic-disabled')
        db.add(user)
        db.flush()
        ids = []
        for client in ('Обмен 1', 'Обмен 2'):
            deal = m.Deal(deal_type=m.DealType.PAY_IN, status=m.DealStatus.PENDING,
                          client_name=client)
            db.add(deal)
            db.flush()
            ids.append(deal.id)
        rows = []
        for n, amount, claimed in ((0, 10000, None), (1, 20000, ids[0]),
                                   (2, 30000, ids[1]), (3, 5000, None)):
            row = m.SberIncome(uuid='s18crm-' + secrets.token_hex(12),
                               operation_date='2026-10-13', amount_rub=amount,
                               payer='Плательщик ' + str(n), claimed_deal_id=claimed)
            db.add(row)
            db.flush()
            rows.append({'id': row.id, 'uuid': row.uuid, 'rub': amount,
                         'payer': row.payer, 'claimed': claimed})
            if claimed:
                deal = db.query(m.Deal).get(claimed)
                deal.payin_amount_rub = amount
                deal.payout_amount_usdt = 150 if claimed == ids[0] else 225
                deal.payin_parts = json.dumps([{'uuid': row.uuid, 'amount_rub': amount}])
        board = {'deals': [{'id': 999991, 'code': 'S18-CRM', 'client': 'Основная',
                            'type': 'Обмен валюты', 'step': 's18', 'log': [],
                            'incomeAmount': 10000, 'amountRub': 10000,
                            'payinParts': [{'incId': 'sber:' + rows[0]['uuid'],
                                            'amountRub': 10000}],
                            'rates': {}, 'conv': []}],
                 'convs': [], 'wallets': [{'id': 'grusha', 'role': 'findir',
                                         'multisig': True,
                                         'addr': 'TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn'}],
                 'incomes': [{'id': 'sber:' + rows[0]['uuid'], 'source': 'sber',
                             'rub': 10000, 'grossRub': 10000, 'dealId': 999991}],
                 'notes': []}
        stand = m._stand_row(db)
        stand.data = json.dumps(board, ensure_ascii=False)
        stand.version = (stand.version or 0) + 1
        db.commit()
        user_id = user.id
    finally:
        db.close()
    client = m.app.test_client()
    with client.session_transaction() as sess:
        sess['user_id'] = user_id
    try:
        yield client, rows
    finally:
        db = m.get_session()
        try:
            income_ids = [r['id'] for r in rows]
            conv_ids = [x[0] for x in db.query(m.ConversionSource.conversion_id).filter(
                m.ConversionSource.sber_income_id.in_(income_ids)).distinct().all()]
            tx_ids = [x[0] for x in db.query(m.ConversionTx.payin_tx_id).filter(
                m.ConversionTx.conversion_id.in_(conv_ids)).all()]
            if tx_ids:
                db.query(m.PayinTxUse).filter(m.PayinTxUse.tx_id.in_(tx_ids)).delete(synchronize_session=False)
                db.query(m.ConversionTx).filter(m.ConversionTx.payin_tx_id.in_(tx_ids)).delete(synchronize_session=False)
                db.query(m.PayinTx).filter(m.PayinTx.id.in_(tx_ids)).delete(synchronize_session=False)
            db.query(m.ConversionSource).filter(m.ConversionSource.sber_income_id.in_(income_ids)).delete(synchronize_session=False)
            if conv_ids:
                db.query(m.Conversion).filter(m.Conversion.id.in_(conv_ids)).delete(synchronize_session=False)
            db.query(m.SberIncome).filter(m.SberIncome.id.in_(income_ids)).delete(synchronize_session=False)
            db.query(m.Deal).filter(m.Deal.id.in_(ids)).delete(synchronize_session=False)
            db.query(m.AdminUser).filter_by(id=user_id).delete()
            db.commit()
        finally:
            db.close()


def _proposal(board, rows):
    state = copy.deepcopy(board)
    deal = state['deals'][0]
    deal.update(step='s18w', cnvId=1, walletId='grusha')
    deal['rates']['broker'] = '100'
    deal['brokerCrmDraftIds'] = [r['id'] for r in rows[1:]]
    sources = [{'dealId': deal['id'], 'rub': 10000, 'clientRub': 10000, 'usdt': 99.63, 'bankNet': True}]
    for row in rows[1:]:
        sources.append({'dealId': None, 'crmIncomeId': row['id'], 'clientRub': row['rub'], 'incomeId': 'sber:' + row['uuid'],
                        'rub': row['rub'], 'usdt': round(64765 * row['rub'] / 65000 / 100, 2)})
        state['incomes'].append({'id': 'sber:' + row['uuid'], 'source': 'sber',
                                 'rub': row['rub'], 'grossRub': row['rub'],
                                 'dealId': None, 'cnvId': 1, 'batchRub': row['rub']})
    for source, planned in zip(sources, stand_funding.incoming_shares(
            [Decimal(str(x['rub'])) for x in sources], Decimal('647.65'))):
        source['usdt'] = float(planned)
    state['incomes'][0]['cnvId'] = 1
    state['convs'] = [{'id': 1, 'broker': 'Tradex', 'requestNo': '41', 'rate': '100',
                       'status': 'sent', 'at': '13.10, 12:00', 'sentTs': 1791892800000,
                       'walletId': 'grusha', 'rubTotal': 65000, 'clientRubTotal': 65000, 'held': 235,
                       'sent': 64765, 'feePct': .3, 'feeFix': 40,
                       'feeCtrl': 105, 'feeOurs': 130, 'feeCtrlPct': .1,
                       'feeOursPct': .2, 'sources': sources, 'txs': []}]
    return state


def test_sber_crm_and_unlinked_in_one_batch(sber_board):
    client, rows = sber_board
    before = client.get('/api/stand/state').json
    candidates = client.get('/api/stand/s18/sber-candidates').json['incomes']
    assert {r['id'] for r in candidates} >= {r['id'] for r in rows}
    assert [r['dealId'] for r in candidates if r['id'] in (rows[1]['id'], rows[2]['id'])] == [rows[2]['claimed'], rows[1]['claimed']]
    by_id = {r['id']: r for r in candidates}
    assert by_id[rows[1]['id']]['dealRub'] == 20000
    assert by_id[rows[1]['id']]['payoutUsdt'] == 150
    assert by_id[rows[3]['id']]['payoutUsdt'] is None
    proposal = _proposal(before['data'], rows)
    assert stand_funding.check_batch(proposal, proposal['convs'][0]) is None
    response = client.put('/api/stand/state', json={'version': before['version'],
                                                    'data': proposal})
    assert response.status_code == 200, response.json
    saved = response.json['data']
    assert saved['deals'][0]['step'] == 's18w'
    assert saved['convs'][0]['crmConversionId']
    assert len(saved['convs'][0]['sources']) == 4
    assert saved['convs'][0]['sources'][1]['crmDealId'] == rows[1]['claimed']
    assert saved['convs'][0]['sources'][1]['crmClient'] == 'Обмен 1'
    assert saved['convs'][0]['sources'][3]['crmDealId'] is None
    db = m.get_session()
    try:
        crm = db.query(m.Conversion).get(saved['convs'][0]['crmConversionId'])
        assert crm.sent_at == m.datetime.utcfromtimestamp(saved['convs'][0]['sentTs'] / 1000)
        assert crm.status == m.ConversionStatus.SENT
        assert crm.sources_rub() == 65000
        assert crm.sent_rub() == 64765
        assert {s.sber_income_id for s in crm.sources} == {r['id'] for r in rows}
        assert [round(x, 2) for x in m.conversion_shares_for(crm, True).values()] == [99.64, 199.28, 298.91, 49.82]
    finally:
        db.close()
    after = client.get('/api/stand/s18/sber-candidates').json['incomes']
    assert not {r['id'] for r in rows} & {r['id'] for r in after}


def test_s18_rejects_before_registry_bank_date(sber_board):
    client, rows = sber_board
    before = client.get('/api/stand/state').json
    proposal = _proposal(before['data'], rows)
    proposal['convs'][0]['sentTs'] = 1791752400000  # 12.10 00:00 МСК < выписка 13.10.
    response = client.put('/api/stand/state', json={'version': before['version'], 'data': proposal})
    assert response.status_code == 409, response.json
    assert 'банковского прихода' in response.json['error']


def test_s18_rejects_mixed_accounts(sber_board):
    client, rows = sber_board
    db = m.get_session()
    try:
        db.query(m.SberIncome).filter_by(id=rows[1]['id']).update(
            {'account_key': 'flow_sole'})
        db.commit()
    finally:
        db.close()
    before = client.get('/api/stand/state').json
    proposal = _proposal(before['data'], rows)
    proposal['incomes'][1]['source'] = 'registry'
    proposal['incomes'][1]['accountKey'] = 'flow_sole'
    response = client.put('/api/stand/state', json={
        'version': before['version'], 'data': proposal})
    assert response.status_code == 409, response.json
    assert 'разных счет' in response.json['error'].lower()


def test_reuse_rejected_after_other_tab_took_income(sber_board):
    client, rows = sber_board
    before = client.get('/api/stand/state').json
    proposal = _proposal(before['data'], rows)
    first = client.put('/api/stand/state', json={'version': before['version'],
                                                 'data': proposal})
    assert first.status_code == 200, first.json
    stale = client.put('/api/stand/state', json={'version': before['version'],
                                                 'data': proposal})
    assert stale.status_code == 409
    db = m.get_session()
    try:
        assert db.query(m.ConversionSource).filter(m.ConversionSource.sber_income_id == rows[1]['id']).count() == 1
    finally:
        db.close()


def test_main_sber_income_also_reaches_crm_without_small_exchange(sber_board):
    client, rows = sber_board
    before = client.get('/api/stand/state').json
    proposal = _proposal(before['data'], rows)
    proposal['convs'][0]['sources'] = proposal['convs'][0]['sources'][:1]
    proposal['deals'][0]['brokerCrmDraftIds'] = []
    proposal['convs'][0].update(rubTotal=10000, clientRubTotal=10000, sent=9930, held=70,
                               feeCtrl=50, feeOurs=20)
    proposal['convs'][0]['sources'][0]['usdt'] = 99.30
    proposal['incomes'] = proposal['incomes'][:1]
    response = client.put('/api/stand/state', json={'version': before['version'],
                                                    'data': proposal})
    assert response.status_code == 200, response.json
    db = m.get_session()
    try:
        crm = db.query(m.Conversion).get(response.json['data']['convs'][0]['crmConversionId'])
        assert [s.sber_income_id for s in crm.sources] == [rows[0]['id']]
    finally:
        db.close()


@pytest.mark.parametrize('ledger_share', [False, True])
def test_received_batch_distributes_crm_deal_shares(sber_board, ledger_share):
    client, rows = sber_board
    before = client.get('/api/stand/state').json
    sent = client.put('/api/stand/state', json={'version': before['version'],
                                               'data': _proposal(before['data'], rows)})
    assert sent.status_code == 200, sent.json
    crm_id = sent.json['data']['convs'][0]['crmConversionId']
    # Проверенный сетевой приход уже добавлен сервером на s18w.
    incoming_hash = secrets.token_hex(32)
    db = m.get_session()
    try:
        stand = m._stand_row(db)
        state = json.loads(stand.data)
        state['convs'][0]['txs'] = [{'hash': incoming_hash, 'net': 'TRC20',
                                    'amount': 647.65, 'status': 'confirmed'}]
        if ledger_share:
            tx = m.PayinTx(tx_hash=incoming_hash, amount_usdt=1000, source='tronscan')
            db.add(tx); db.flush()
            use = m.PayinTxUse(tx_id=tx.id, stand_generation=stand.generation,
                              stand_cnv_id='1', amount_usdt=647.65)
            db.add(use); db.flush()
            state['convs'][0]['txs'][0].update(ledgerUseId=use.id, verifiedAmount=1000)
        stand.data = json.dumps(state, ensure_ascii=False)
        stand.version += 1
        db.commit()
    finally:
        db.close()
    before = client.get('/api/stand/state').json
    done = copy.deepcopy(before['data'])
    done['convs'][0]['status'] = 'received'
    for source, value in zip(done['convs'][0]['sources'], [99.63, 199.27, 298.91, 49.84]):
        source['usdtFact'] = value
    response = client.put('/api/stand/state', json={'version': before['version'], 'data': done})
    assert response.status_code == 200, response.json
    db = m.get_session()
    try:
        crm = db.query(m.Conversion).get(crm_id)
        assert crm.status == m.ConversionStatus.RECEIVED
        assert crm.received_usdt() == 647.65
        tx = db.query(m.PayinTx).filter_by(tx_hash=incoming_hash).first()
        uses = {u.deal_id: u.amount_usdt for u in db.query(m.PayinTxUse).filter_by(tx_id=tx.id)}
        assert uses[rows[1]['claimed']] == (199.27 if ledger_share else 199.28)
        assert uses[rows[2]['claimed']] == 298.91
        assert db.query(m.Deal).get(rows[1]['claimed']).payin_amount_usdt == (199.27 if ledger_share else 199.28)
        assert db.query(m.Deal).get(rows[2]['claimed']).payin_amount_usdt == 298.91
        assert rows[3]['claimed'] is None
        if ledger_share:
            assert tx.free_usdt() == 352.35
            assert uses[None] == 149.47
            m._apply_conversion_shares(db, crm)
            assert tx.free_usdt() == 352.35
    finally:
        db.close()


@pytest.mark.parametrize('registry_link', [True, False])
@pytest.mark.parametrize('board_key', [None, 'flow_sole', 'bank:044525094:40807810819000000261'])
def test_flowsole_alias_draft_handoff_and_sql_actual_sent(sber_board, board_key, registry_link):
    """Старый приход стенда + CRM alias: выбор, сохранение, отправка и SQL."""
    client, rows = sber_board
    db = m.get_session()
    try:
        state = json.loads(m._stand_row(db).data)
        deal = state['deals'][0]
        receipt_id = 'alias-' + secrets.token_hex(8)
        rows[0]['uuid'] = 'manual:' + receipt_id
        own = db.query(m.SberIncome).get(rows[0]['id'])
        own.uuid = rows[0]['uuid']
        for row in rows:
            db.query(m.SberIncome).get(row['id']).account_key = 'flow_sole'
        # SQL тоже может хранить полную пару, не только старый alias.
        own.account_key = 'bank:044525094:40807810819000000261'
        deal['manualBankReceipt'] = {'id': receipt_id, 'status': 'confirmed',
            'actualMode': 'custom', 'bankBik': '044525094', 'account': '40807810819000000261',
            'confirmedAt': '2026-10-16', 'confirmedBy': 12, 'actualAmount': 10000}
        deal['rubReceivingAccount'] = {'mode': 'custom', 'bank': 'БАНК СГБ',
                                      'correspondent': '30101810245250000094', 'bik': '044525094',
                                      'account': '40807810819000000261'}
        deal['payinParts'] = [{'incId': 'manual-own', 'amountRub': 10000,
                              'crmIncomeId': own.id, 'manualReceiptId': receipt_id}]
        if not registry_link:
            deal['payinParts'][0].pop('crmIncomeId')
        state['incomes'] = [{'id': 'manual-own', 'dealId': deal['id'], 'source': 'manual_confirmed',
            'manualReceiptId': receipt_id, 'crmIncomeId': own.id, 'rub': 10000, 'grossRub': 10000}]
        if board_key:
            state['incomes'][0]['accountKey'] = board_key
        m._stand_row(db).data = json.dumps(state)
        db.commit()
    finally:
        db.close()
    before = client.get('/api/stand/state').json
    draft = copy.deepcopy(before['data'])
    draft['deals'][0]['brokerCrmDraftIds'] = [r['id'] for r in rows[1:]]
    selected = client.put('/api/stand/state', json={'version': before['version'], 'data': draft})
    if not registry_link:
        assert selected.status_code == 409, selected.json
        assert 'не связан с общим реестром' in selected.json['error']
        assert client.get('/api/stand/state').json['version'] == before['version']
        forged = _proposal(before['data'], rows)
        assert 'не связан с общим реестром' in m._stand_broker_handoff_problem(
            before['data'], forged, before['data']['deals'][0], forged['deals'][0])
        # Подтверждённые деньги остаются доступны отдельной пачкой без изменения связи.
        standalone = copy.deepcopy(before['data'])
        standalone['deals'][0]['brokerSentOverride'] = 9000
        saved = client.put('/api/stand/state', json={'version': before['version'], 'data': standalone})
        assert saved.status_code == 200, saved.json
        proposal = _proposal(saved.json['data'], rows[:1])
        conv = proposal['convs'][0]
        conv.update(feeMode='manual', rubTotal=10000, clientRubTotal=10000, sent=9000, held=1000)
        for key in ('feePct', 'feeFix', 'feeCtrl', 'feeOurs', 'feeCtrlPct', 'feeOursPct'):
            conv.pop(key, None)
        conv['sources'][0]['usdt'] = 90
        response = client.put('/api/stand/state', json={'version': saved.json['version'], 'data': proposal})
        assert response.status_code == 200, response.json
        assert response.json['data']['deals'][0]['step'] == 's18w'
        assert 'crmIncomeId' not in response.json['data']['deals'][0]['payinParts'][0]
        assert not response.json['data']['convs'][0].get('crmConversionId')
        return
    assert selected.status_code == 200, selected.json
    draft = selected.json['data']
    draft['deals'][0]['brokerSentOverride'] = 64000
    saved = client.put('/api/stand/state', json={'version': selected.json['version'], 'data': draft})
    assert saved.status_code == 200, saved.json
    proposal = _proposal(saved.json['data'], rows)
    conv = proposal['convs'][0]
    conv.update(feeMode='manual', sent=64000, held=1000, clientRubTotal=65000)
    for key in ('feePct', 'feeFix', 'feeCtrl', 'feeOurs', 'feeCtrlPct', 'feeOursPct'):
        conv.pop(key, None)
    planned = stand_funding.incoming_shares(
        [Decimal(str(x['rub'])) for x in conv['sources']], Decimal(640))
    for source, share in zip(conv['sources'], planned):
        source['clientRub'] = source['rub']
        source['usdt'] = float(share)
    for source, row in zip(conv['sources'][1:], rows[1:]):
        source['crmIncomeId'] = row['id']
    for income in proposal['incomes'][1:]:
        income.update(source='registry', accountKey='flow_sole')
    assert stand_funding.check_batch(proposal, conv, strict_account=True) is None
    conflict = copy.deepcopy(proposal)
    conflict['convs'][0]['sources'][1]['accountKey'] = 'sber'
    assert 'не совпадает' in stand_funding.check_batch(conflict, conflict['convs'][0], strict_account=True)
    conflict = copy.deepcopy(proposal)
    conflict['deals'][0]['manualBankReceipt']['account'] = '40807810819000000999'
    assert stand_funding.check_batch(conflict, conflict['convs'][0], strict_account=True)
    response = client.put('/api/stand/state', json={'version': saved.json['version'], 'data': proposal})
    assert response.status_code == 200, response.json
    db = m.get_session()
    try:
        crm = db.query(m.Conversion).get(response.json['data']['convs'][0]['crmConversionId'])
        assert crm.amount_rub_sent == 64000
        assert crm.held_percent == 0
        assert crm.held_fixed_rub == 1000
        assert crm.sources_rub() == 65000
        assert {s.sber_income_id for s in crm.sources} == {r['id'] for r in rows}
    finally:
        db.close()
