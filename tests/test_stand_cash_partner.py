"""Оплата наличными через партнёра на s14: права, документы и единый реестр USDT."""
import copy
import uuid

import pytest

import app as m
from tests.test_stand_transfers import authenticated_stand_client, _put_board, FROM


pytestmark = pytest.mark.usefixtures('stand_demo_environment')


def _state():
    return {'deals': [{'id': 1483, 'code': 'СД-1483', 'step': 's14',
        'type': 'Оплата недвижимости', 'kind': 'Лизхолд',
        'payType': 'По реквизитам', 'rubReceivingAccount': {'mode': 'flowsole'},
        'walletId': 'grusha', 'payinHashes': [], 'payinParts': [], 'pay': {},
        'docVersion': 2, 'docs': {'signed': [{'file': 'signed.pdf'}]},
        'docFields': {'payTo': 'Flow Sole'}, 'log': [{'at': 1700000000000, 'text': 'Заявка'}]}],
        'incomes': [], 'convs': [], 'wallets': []}


def _legacy_cash_state():
    state = _state()
    state['deals'][0].update(payType='Наличные', cashPartnerUsdt=True)
    return state


def _setup(monkeypatch, state=None):
    monkeypatch.setattr(m, 'STAND_MODE', True)
    monkeypatch.setattr(m, 'current_role', lambda: 'operator')
    _put_board(state or _state())
    return m.app.test_client()


def test_new_cash_method_is_rejected_and_legacy_deal_can_restore(monkeypatch):
    client = _setup(monkeypatch)
    original = client.get('/api/stand/state').json['data']['deals'][0]
    rejected = client.post('/api/stand/payin/cash-method', json={'dealId': 1483})
    assert rejected.status_code == 409, rejected.json
    assert 'сверку прихода по выписке' in rejected.json['error']
    unchanged = client.get('/api/stand/state').json['data']['deals'][0]
    assert unchanged['payType'] == 'По реквизитам'
    assert unchanged['docs'] == original['docs']

    legacy_client = _setup(monkeypatch, _legacy_cash_state())
    legacy = legacy_client.get('/api/stand/state').json['data']['deals'][0]
    restored = legacy_client.post('/api/stand/payin/cash-method',
        json={'dealId': 1483, 'restore': True})
    assert restored.status_code == 200, restored.json
    restored_deal = restored.json['data']['deals'][0]
    assert restored_deal['payType'] == 'По реквизитам'
    assert restored_deal['docs'] == legacy['docs']
    assert restored_deal['cashPartnerUsdt'] is False


def test_cash_method_denied_after_bank_credit_and_for_manager(monkeypatch):
    state = _state()
    state['deals'][0]['payinParts'] = [{'incId': 1, 'amountRub': 1000}]
    client = _setup(monkeypatch, state)
    assert client.post('/api/stand/payin/cash-method', json={'dealId': 1483}).status_code == 409
    state['deals'][0]['payinParts'] = []
    state['incomes'] = [{'id': 1, 'dealId': 1483, 'rub': 1000}]
    _put_board(state)
    assert client.post('/api/stand/payin/cash-method', json={'dealId': 1483}).status_code == 409
    _put_board(_state())
    monkeypatch.setattr(m, 'current_role', lambda: 'manager')
    assert client.post('/api/stand/payin/cash-method', json={'dealId': 1483}).status_code == 403


def test_two_partner_hashes_use_shared_ledger_and_block_duplicate(monkeypatch):
    client = _setup(monkeypatch, _legacy_cash_state())
    first, second = uuid.uuid4().hex * 2, uuid.uuid4().hex * 2
    def verified(ref, network, sender, receiver, amount):
        return {'status': 'confirmed', 'verifiedAmount': 120 if ref == first else 80,
            'verifiedAt': 'now', 'timestampMs': 1700000000001, 'from': FROM, 'to': receiver}
    monkeypatch.setattr(m, 'verify_transfer', verified)
    for ref in (first, second):
        result = client.post('/api/stand/payin/check', json={'dealId': 1483, 'hash': ref})
        assert result.status_code == 200, result.json
    deal = client.get('/api/stand/state').json['data']['deals'][0]
    assert [h['amount'] for h in deal['payinHashes']] == [120, 80]
    assert all(h['verified'] and h['ledgerUseId'] for h in deal['payinHashes'])
    assert client.post('/api/stand/payin/check', json={'dealId': 1483, 'hash': first}).status_code == 409
    ledger = client.get('/api/payin-txs/' + first).json['tx']
    assert ledger['free_usdt'] == 0 and ledger['used_usdt'] == 120
    forged = copy.deepcopy(client.get('/api/stand/state').json)
    forged['data']['deals'][0]['payinHashes'].pop()
    rejected = client.put('/api/stand/state', json={'version': forged['version'], 'data': forged['data']})
    assert rejected.status_code == 409
    advancing = copy.deepcopy(client.get('/api/stand/state').json)
    advancing['data']['deals'][0]['step'] = 's22'
    advancing['data']['deals'][0]['amountUsdt'] = 200
    advancing['data']['deals'][0]['pay']['usdt'] = 200
    routed = client.put('/api/stand/state', json={
        'version': advancing['version'], 'data': advancing['data']})
    assert routed.status_code == 200, routed.json
    assert routed.json['data']['deals'][0]['step'] == 's22'
    db = m.get_session()
    try:
        stand = m._stand_row(db)
        original_uses = {u.tx.tx_hash: u.id for u in db.query(m.PayinTxUse).filter_by(
            stand_generation=stand.generation, stand_cnv_id='cash:1483').all()}
        crm = m.Deal(client_name='cash partner', deal_type=m.DealType.PAY_IN)
        db.add(crm); db.flush()
        db.info['stand_payin_origin'] = (stand.generation, 'cash:1483')
        db.info['stand_payin_hashes'] = {first, second}
        m._sync_payin_tx_uses(db, crm, [
            {'hash': first, 'network': 'trc20', 'amount_usdt': 120},
            {'hash': second, 'network': 'trc20', 'amount_usdt': 80}])
        uses = db.query(m.PayinTxUse).filter_by(deal_id=crm.id).all()
        assert {u.id for u in uses} == set(original_uses.values())
        assert all(u.tx.used_usdt() == u.amount_usdt for u in uses)
    finally:
        db.info.pop('stand_payin_origin', None)
        db.info.pop('stand_payin_hashes', None)
        db.rollback(); db.close()


def test_partner_hash_already_allocated_in_crm_is_rejected(monkeypatch):
    client = _setup(monkeypatch, _legacy_cash_state())
    ref = uuid.uuid4().hex * 2
    db = m.get_session()
    try:
        tx = m.PayinTx(tx_hash=ref, network='trc20', amount_usdt=100, source='tronscan')
        db.add(tx); db.flush()
        db.add(m.PayinTxUse(tx_id=tx.id, stand_generation='another-board',
                            stand_cnv_id='another-conversion', amount_usdt=100))
        db.commit()
    finally:
        db.close()
    monkeypatch.setattr(m, 'verify_transfer', lambda ref, network, sender, receiver, amount: {
        'status': 'confirmed', 'verifiedAmount': 100, 'verifiedAt': 'now',
        'timestampMs': 1700000000001, 'from': FROM, 'to': receiver})
    result = client.post('/api/stand/payin/check', json={'dealId': 1483, 'hash': ref})
    assert result.status_code == 409, result.json
    assert client.get('/api/stand/state').json['data']['deals'][0]['payinHashes'] == []


def test_incoming_list_shows_available_wallet_transfers(monkeypatch):
    client = _setup(monkeypatch, _legacy_cash_state())
    available, occupied = uuid.uuid4().hex * 2, uuid.uuid4().hex * 2
    db = m.get_session()
    try:
        tx = m.PayinTx(tx_hash=occupied, network='trc20', amount_usdt=50, source='tronscan')
        db.add(tx); db.flush()
        db.add(m.PayinTxUse(tx_id=tx.id, stand_generation='another-board',
                            stand_cnv_id='other', amount_usdt=50))
        db.commit()
    finally:
        db.close()
    import stand_transfer_discovery
    seen = {}
    def discover(**kwargs):
        seen.update(kwargs)
        return {'status': 'complete', 'candidates': [
            {'hash': ref, 'amount': amount, 'from': FROM, 'timestamp_ms': 1700000000001}
            for ref, amount in ((available, 100), (occupied, 50))]}
    monkeypatch.setattr(stand_transfer_discovery, 'discover_transfers', discover)
    result = client.get('/api/stand/payin/cash-incoming?dealId=1483')
    assert result.status_code == 200, result.json
    assert [x['hash'] for x in result.json['incoming']] == [available]
    assert seen['wallet_addr'] == 'TKkeEVf2zySaWTLyX2qPwvi6kcdHRuPxkJ'
    assert seen['direction'] == 'incoming'


_SETUP = {'name': 'Cash Partner QA', 'location': 'Test meeting place',
          'contact': 'Test contact', 'appointmentAt': '2026-11-26T15:40'}
_ACTION = '/api/stand/payin/cash-partner'


@pytest.fixture
def cash_board(monkeypatch):
    from tests.test_stand_transfers import TO

    monkeypatch.setattr(m, 'STAND_MODE', True)
    client = m.app.test_client()
    db = m.get_session()
    try:
        users = {}
        for key, role in (('manager', 'manager'), ('other', 'manager'), ('operator', 'operator')):
            username = f'cash_partner_test_{key}'
            user = db.query(m.AdminUser).filter_by(username=username).first()
            if user is None:
                user = m.AdminUser(username=username, role=role, password_hash='qa')
                db.add(user)
                db.flush()
            users[key] = user.id
        wallets = {}
        for key, address, chain in (('tron', TO, 'TRON'),
                                    ('erc', '0x' + 'e' * 40, 'ETH'),
                                    ('alternate', FROM, 'TRON')):
            wallet = db.query(m.Wallet).filter_by(address=address).first()
            if wallet is None:
                wallet = m.Wallet(address=address, blockchain=chain, label=key)
                db.add(wallet)
            wallet.active = wallet.accepts_payin = True
            wallet.not_for_new_deals = False
            db.flush()
            wallets[key] = wallet.id
        db.commit()
    finally:
        db.close()

    def use_role(key):
        with client.session_transaction() as session:
            session['user_id'] = users[key]

    state = _state()
    deal = state['deals'][0]
    deal.update(managerUserId=users['manager'], step='s12', cashPartner=dict(_SETUP),
                payType='Наличные', docPack={'method': 'cash', 'version': 2},
                docsSent=True, amountRub=20000, isTask=True)
    deal.pop('rubReceivingAccount')
    _put_board(state)
    use_role('manager')
    return client, use_role, wallets, users


def _save_deal(client, edit):
    snapshot = client.get('/api/stand/state').json
    edit(snapshot['data']['deals'][0])
    return client.put('/api/stand/state', json={
        'version': snapshot['version'], 'data': snapshot['data']})


def _partner_action(client, operation, **values):
    return client.post(_ACTION, json={'dealId': 1483, 'op': operation, **values})


def _native_verify(client, tx_hash):
    return client.post('/api/stand/payin/check', json={'dealId': 1483, 'hash': tx_hash})


def test_cash_setup_belongs_to_manager_then_locked_on_s11(cash_board):
    client, use_role, _, users = cash_board
    state = _state()
    deal = state['deals'][0]
    deal.update(step='s8', payType='Наличные', managerUserId=users['manager'])
    for key in ('docVersion', 'docs', 'walletId', 'rubReceivingAccount'):
        deal.pop(key)
    _put_board(state)

    use_role('other')
    assert _save_deal(client, lambda d: d.update(cashPartner=_SETUP)).status_code == 409

    use_role('manager')
    malformed = {**_SETUP, 'appointmentAt': '2026-02-30T15:40'}
    assert _save_deal(client, lambda d: d.update(cashPartner=malformed)).status_code == 409
    assert _save_deal(client, lambda d: d.update(step='s11')).json['error'].startswith('Укажите партнёра')
    saved = _save_deal(client, lambda d: d.update(cashPartner=_SETUP))
    assert saved.status_code == 200, saved.json

    deal.update(step='s11', cashPartner=_SETUP)
    _put_board(state)
    use_role('operator')
    assert _save_deal(client, lambda d: d.update(cashPartner={**_SETUP, 'name': 'Different'})).status_code == 409
    del deal['cashPartner']
    _put_board(state)
    assert _save_deal(client, lambda d: d.update(cashPartner=_SETUP)).status_code == 200


def test_cash_lifecycle_binds_roles_and_exact_ledger_funding(cash_board, monkeypatch):
    client, use_role, wallets, users = cash_board
    assert _save_deal(client, lambda d: d.update(step='s14')).status_code == 409
    handed = _save_deal(client, lambda d: d.update(step='s14c'))
    assert handed.status_code == 200, handed.json

    use_role('other')
    assert _partner_action(client, 'receive', amountRub=20000).status_code == 403
    use_role('manager')
    assert _partner_action(client, 'receive', amountRub='20 000,001').status_code == 400
    assert _save_deal(client, lambda d: d.update(step='s14', cashPartnerReceipt={
        'amountRub': 20000, 'at': 'now', 'by': users['manager']})).status_code == 409
    received = _partner_action(client, 'receive', amountRub='20 000,00')
    assert received.status_code == 200, received.json
    deal = received.json['data']['deals'][0]
    assert deal['step'] == 's14'
    assert deal['isTask'] is False
    assert deal['cashPartnerReceipt']['amountRub'] == 20000
    assert deal['cashPartnerReceipt']['by'] == users['manager']
    assert 'cashPartnerWalletId' not in deal
    assert _partner_action(client, 'receive', amountRub=30000).status_code == 409
    assert _partner_action(client, 'rate', rate=100).status_code == 403
    lost = client.post('/api/stand/deals/1483/crm-close-lose', json={
        'version': received.json['version'], 'reason': next(iter(m.STAND_CLOSE_LOSE_REASONS))})
    assert lost.status_code == 409 and 'получил наличные' in lost.json['error']
    manual = client.post('/api/stand/deals/1483/crm-close', json={
        'version': received.json['version'], 'crm': {}, 'manualOverride': {}})
    assert manual.json['error'] == 'manual_override_not_applicable'

    use_role('operator')
    first, second = uuid.uuid4().hex * 2, uuid.uuid4().hex * 2
    seen = []
    amounts = {first: 140.123456, second: 59.876123}

    def verify(ref, network, sender, receiver, amount):
        seen.append((network, receiver))
        return {'status': 'confirmed', 'verifiedAmount': amounts[ref],
                'verifiedAt': 'now', 'timestampMs': 1700000000001, 'from': FROM, 'to': receiver}

    monkeypatch.setattr(m, 'verify_transfer', verify)
    assert _native_verify(client, first).status_code == 409
    assert seen == []
    assert _partner_action(client, 'wallet', walletId='grusha').status_code == 400
    assert _partner_action(client, 'wallet', walletId=wallets['erc']).status_code == 400
    selected = _partner_action(client, 'wallet', walletId=wallets['tron'])
    assert selected.status_code == 200, selected.json
    assert selected.json['data']['deals'][0]['walletId'] == wallets['tron']
    assert _partner_action(client, 'rate', rate=100, rateAt='2026-11-26T15:41').status_code == 200
    assert _native_verify(client, first).status_code == 200
    assert _partner_action(client, 'wallet', walletId=wallets['alternate']).status_code == 409
    assert _save_deal(client, lambda d: d.update(step='s18')).status_code == 409

    def route(deal, amount=200):
        deal.update(step='s22', amountUsdt=amount)
        deal['pay'].update(usdt=amount, hash=first)

    short = _save_deal(client, route)
    assert short.status_code == 409 and 'отличается' in short.json['error']
    assert _native_verify(client, second).status_code == 200
    assert _native_verify(client, second).status_code == 409
    assert _save_deal(client, lambda deal: route(deal, 300)).status_code == 409
    staged = _save_deal(client, route)
    assert staged.status_code == 200, staged.json
    deal = staged.json['data']['deals'][0]
    assert deal['step'] == 's22'
    assert deal['amountUsdt'] == deal['pay']['usdt'] == 199.999579
    assert seen and {entry[0] for entry in seen} == {'trc20'}
    assert _partner_action(client, 'unlink', hash=second, reason='Ошибся переводом').status_code == 409
    too_much = _save_deal(client, lambda d: d.update(step='s23', transfer={'amount': 200.01}))
    assert 'превышает подтверждённый приход' in too_much.json['error']

    db = m.get_session()
    try:
        db.get(m.Wallet, wallets['tron']).active = False
        db.commit()
        state = {'deals': [deal]}
        assert m._stand_close_fact_source(state, deal, 'payin', db=db, row=m._stand_row(db)) == (
            'verified_partner_network', None)
    finally:
        db.close()


    from tests.test_stand_crm_close_atomic import s26_legacy_trail

    deal.update(step='s27', client='Cash CRM QA', sentToClient=True,
                postConv='keep', payTo={'bank': 'Test bank', 'acc': 'QA', 'purpose': 'QA invoice'},
                amountThb=2500, rates={'client': 8, 'usdtThb': 33},
                files={'receipt': [{'file': 'receipt.pdf', 'mime': 'application/pdf',
                                    'data': 'data:application/pdf;base64,JVBERi0='}]})
    deal['pay']['invoicePaid'] = True
    deal['log'].extend(s26_legacy_trail(deal))
    _put_board({'deals': [deal], 'notes': []})
    use_role('manager')
    crm = {'deal_kind': 'mf_realty', 'client_name': deal['client'], 'payin_method': 'partners_cash',
           'payin_amount_rub': 20000, 'payin_amount_usdt': 200, 'payin_rate_rub_usdt': 100,
           'payin_wallet_id': wallets['tron'], 'payin_partner_name': _SETUP['name'],
           'payin_tx_hashes': [{'hash': ref, 'network': 'trc20', 'amount_usdt': amount}
                              for ref, amount in amounts.items()],
           'invoice_amount_thb': 2500, 'buy_rate_thb_usdt': 33, 'sell_rate_thb_usdt': 8,
           'realty_purpose': 'QA invoice', 'company_percent': 1}
    closed = client.post('/api/stand/deals/1483/crm-close', json={'version': 1, 'crm': crm})
    assert closed.status_code == 201, closed.json
    assert closed.json['deal']['payin_amount_usdt'] == 199.999579
    assert closed.json['deal']['payin_amount_rub'] == 20000
    assert closed.json['deal']['payin_rate_rub_usdt'] == 100
    assert closed.json['deal']['payin_partner_name'] == _SETUP['name']
    assert closed.json['deal']['payin_wallet_id'] == wallets['tron']
    assert closed.json['deal']['payin_tx_verified'] is True
    crm_id = closed.json['deal']['id']
    edited = client.put(f'/api/deals/{crm_id}', json={'notes': 'QA', 'payin_extra': []})
    assert edited.status_code == 200, edited.json
    assert edited.json['deal']['payin_rate_rub_usdt'] == 100
    changed = client.put(f'/api/deals/{crm_id}', json={'payin_rate_rub_usdt': 88})
    assert changed.status_code == 409
    deal = closed.json['data']['deals'][0]
    db = m.get_session()
    try:
        assert m._stand_close_fact_source({'deals': [deal]}, deal, 'payin', db=db, row=m._stand_row(db)) == (
            'verified_partner_network', None)
        for item in deal['payinHashes']:
            assert db.get(m.PayinTxUse, item['ledgerUseId']).deal_id == deal['crmDealId']
        other = m.Deal(client_name='Other', deal_type=m.DealType.PAY_IN)
        db.add(other)
        db.flush()
        with pytest.raises(ValueError, match='уже засчитан'):
            m._sync_payin_tx_uses(db, other, [{'hash': first, 'network': 'trc20', 'amount_usdt': 0.001}])
    finally:
        db.rollback()
        db.close()


def test_cash_rejects_wrong_wallet_and_shared_ledger_even_for_tiny_use(cash_board, monkeypatch):
    client, use_role, wallets, _ = cash_board
    assert _save_deal(client, lambda d: d.update(step='s14c')).status_code == 200
    assert _partner_action(client, 'receive', amountRub=20000).status_code == 200
    use_role('operator')
    assert _partner_action(client, 'wallet', walletId=wallets['tron']).status_code == 200
    ref = uuid.uuid4().hex * 2

    verification = {'status': 'confirmed', 'verifiedAmount': 200, 'verifiedAt': 'now',
                    'timestampMs': 1700000000001, 'from': FROM, 'to': FROM}
    monkeypatch.setattr(m, 'verify_transfer', lambda *args: verification)
    assert _native_verify(client, ref).status_code == 422

    db = m.get_session()
    try:
        wallet = db.get(m.Wallet, wallets['tron'])
        verification['to'] = wallet.address
        tx = m.PayinTx(tx_hash='0x' + ref.upper(), network='trc20', amount_usdt=200,
                       source='tronscan', to_address=wallet.address)
        db.add(tx)
        db.flush()
        use = m.PayinTxUse(tx_id=tx.id, stand_generation='other-board',
                           stand_cnv_id='other-transaction', amount_usdt=0.001)
        db.add(use)
        db.commit()
        use_id = use.id
    finally:
        db.close()
    assert _native_verify(client, ref).status_code == 409

    db = m.get_session()
    try:
        db.delete(db.get(m.PayinTxUse, use_id))
        conversion = m.Conversion()
        db.add(conversion)
        db.flush()
        link = m.ConversionTx(conversion_id=conversion.id,
                              payin_tx_id=m._payin_find(db, ref).id, amount_usdt=200)
        db.add(link)
        db.commit()
        conversion_id, link_id = conversion.id, link.id
    finally:
        db.close()
    assert _native_verify(client, ref).status_code == 409

    db = m.get_session()
    try:
        db.delete(db.get(m.ConversionTx, link_id))
        db.commit()
    finally:
        db.close()
    assert _native_verify(client, ref).status_code == 200
    cannot_share = client.post(f'/api/conversions/{conversion_id}/txs',
                               json={'tx_hash': '0x' + ref.upper(), 'amount_usdt': 1})
    assert 'уже засчитан' in cannot_share.json['error']
    assert _partner_action(client, 'unlink', hash=ref, reason='').status_code == 400
    unlinked = _partner_action(client, 'unlink', hash=ref, reason='Выбран перевод другой сделки')
    assert unlinked.status_code == 200, unlinked.json
    assert not unlinked.json['data']['deals'][0]['payinHashes']
    db = m.get_session()
    try:
        assert m._payin_exact_used(db, m._payin_find(db, ref, lock=False)) == 0
    finally:
        db.close()


def test_cash_freehold_can_set_verified_amount_on_ipps_handoff(cash_board, monkeypatch):
    client, use_role, wallets, _ = cash_board
    snapshot = client.get('/api/stand/state').json['data']
    snapshot['deals'][0].update(kind='Фрихолд', invoiceUsd=100, ippsTariff='bank')
    _put_board(snapshot)
    assert _save_deal(client, lambda d: d.update(step='s14c')).status_code == 200
    assert _partner_action(client, 'receive', amountRub=20000).status_code == 200
    use_role('operator')
    assert _partner_action(client, 'wallet', walletId=wallets['tron']).status_code == 200
    assert _partner_action(client, 'rate', rate=100).status_code == 200
    ref = uuid.uuid4().hex * 2
    monkeypatch.setattr(m, 'verify_transfer', lambda h, network, sender, receiver, amount: {
        'status': 'confirmed', 'verifiedAmount': 200, 'verifiedAt': 'now',
        'timestampMs': 1700000000001, 'from': FROM, 'to': receiver})
    assert _native_verify(client, ref).status_code == 200

    def route(deal, amount):
        deal.update(step='s22', postConv='ipps_swift', amountUsdt=amount,
                    pay={'usdt': amount, 'hash': ref}, reqTask='open')

    assert _save_deal(client, lambda deal: route(deal, 190)).status_code == 409
    advanced = _save_deal(client, lambda deal: route(deal, 200))
    assert advanced.status_code == 200, advanced.json
    deal = advanced.json['data']['deals'][0]
    assert (deal['step'], deal['postConv'], deal['pay']['usdt']) == ('s22', 'ipps_swift', 200)
    assert any(note['role'] == 'manager' and note['dealId'] == deal['id']
               and 'реквизиты' in note['text'] for note in advanced.json['data']['notes'])
