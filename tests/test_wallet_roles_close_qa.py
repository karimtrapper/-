"""QA пункта 6: закрытие сделки стенда в CRM (crm-close) и обменный кошелёк.

Менеджер не может поставить владельческий флаг; закрытие сделки > лимита с обменного кошелька
без серверного одобрения доски не проходит, а закрытие в пределах лимита и на легаси-кошельке
остаётся как раньше.
"""
import json
import secrets

import pytest

import app as m
from tests.test_stand_crm_close_atomic import _client, _seed_evidence
from tests.test_wallet_roles_qa import REALTY, EXCHANGE, LEGACY, seeded, stand  # noqa: F401
from tests.qa_wallet_roles_helpers import registry_id

pytestmark = pytest.mark.usefixtures('stand_demo_environment')
MSG = 'Для отправки свыше 10 000 USDT требуется подтверждение владельца'


def board_for(amount, wallet_id):
    return {'deals': [{'id': 1474, 'code': 'СД-1474', 'client': 'Synthetic QA',
                       'type': 'Обмен валюты', 'step': 's27', 'closed': False,
                       'crmDealId': None, 'sentToClient': True, 'pay': {},
                       'amountUsdt': amount + 100, 'payout': {'usdt': amount, 'walletId': wallet_id},
                       'files': {'receipt': [{'file': 'receipt.pdf', 'mime': 'application/pdf',
                                              'data': 'data:application/pdf;base64,JVBERi0='}]},
                       'log': []}], 'notes': []}


def crm_for(amount, wallet_id, **extra):
    data = {'deal_kind': 'exchange', 'client_name': 'Synthetic QA', 'manager_name': 'Елизавета',
            'payin_method': 'sber_reqs', 'payin_amount_usdt': amount + 100,
            'payout_method': 'transfer', 'payout_source': 'binance',
            'payout_amount_usdt': amount, 'payout_wallet_id': wallet_id}
    data.update(extra)
    return data


def setup_close(amount, wallet_address, role='manager'):
    wid = registry_id(wallet_address)
    db = m.get_session()
    try:
        user = m.AdminUser(username='close-' + secrets.token_hex(5), display_name='QA manager',
                           role=role, password_hash='unused')
        db.add(user)
        db.flush()
        uid = user.id
        row = db.query(m.StandState).filter_by(id=1).first()
        if row is None:
            row = m.StandState(id=1)
            db.add(row)
        board = board_for(amount, wid)
        row.data, row.version, row.generation = json.dumps(board), 1, secrets.token_hex(16)
        db.commit()
        _seed_evidence(db, row, board=board, actor_id=uid)
    finally:
        db.close()
    return uid, wid


def close(uid, wid, amount, **extra):
    return _client(uid).post('/api/stand/deals/1474/crm-close',
                             json={'version': 1, 'crm': crm_for(amount, wid, **extra)})


def deals_for(name='Synthetic QA'):
    db = m.get_session()
    try:
        return db.query(m.Deal).filter_by(client_name=name).count()
    finally:
        db.close()


def test_close_within_limit_on_exchange_wallet_works(seeded):
    uid, wid = setup_close(5000, EXCHANGE)
    r = close(uid, wid, 5000)
    assert r.status_code in (200, 201), r.json


def test_close_over_limit_without_board_approval_is_refused(seeded):
    uid, wid = setup_close(15000, EXCHANGE)
    before = deals_for()
    r = close(uid, wid, 15000)
    assert r.status_code == 400, r.json
    assert MSG in json.dumps(r.json, ensure_ascii=False)
    assert deals_for() == before


@pytest.mark.parametrize('role', ['manager', 'admin', 'operator'])
def test_closing_user_cannot_supply_owner_flag(seeded, role):
    uid, wid = setup_close(15000, EXCHANGE, role=role)
    before = deals_for()
    r = close(uid, wid, 15000, payout_owner_approved=True)
    assert r.status_code in (400, 403), r.json
    assert deals_for() == before


def test_close_on_legacy_wallet_has_no_new_limit(seeded):
    uid, wid = setup_close(15000, LEGACY)
    r = close(uid, wid, 15000)
    assert r.status_code in (200, 201), r.json


# ---------------- положительный путь: одобрение доски переносится в CRM сервером

DEST = 'TQgQCBXkewuW4RoieDKFP9Ko2SopBh8jso'


def approved_board(amount=15000, **tamper):
    """Синтетическая доска, как после реального claim/approve/confirm/Success в сети.

    Подписи ставятся напрямую в состояние: это фикстура серверных меток, их корректность
    обходом через API проверяют test_wallet_roles_claim_qa / approve_qa / confirm_qa.
    """
    from tests.qa_wallet_roles_helpers import make_user
    wid = registry_id(EXCHANGE)
    claimer, confirmer, approver = (make_user('operator'), make_user('findir'), make_user('teodor'))
    ref = 'ab' * 32
    deal = {'id': 1474, 'code': 'СД-1474', 'client': 'Synthetic QA', 'type': 'Обмен валюты',
            'step': 's27', 'closed': False, 'crmDealId': None, 'sentToClient': True,
            'pay': {'invoicePaid': True, 'coinsNotified': True, 'coinsCredit': {'thb': 500000}},
            'amountUsdt': amount + 100, 'walletId': wid, 'postConv': 'coins',
            'payout': {'usdt': amount, 'walletId': wid},
            'transfer': {'addr': DEST, 'amount': amount, 'net': 'TRC-20', 'sends': [
                {'ref': ref, 'amount': amount, 'net': 'TRC-20', 'status': 'confirmed',
                 'verifiedAmount': amount, 'from': EXCHANGE, 'to': DEST}]},
            'serverTransferComplete': True,
            'files': {'receipt': [{'file': 'receipt.pdf', 'mime': 'application/pdf',
                                   'data': 'data:application/pdf;base64,JVBERi0='}]},
            'log': []}
    from tests.qa_wallet_roles_helpers import send_deal
    _, mirror = send_deal(1474, EXCHANGE, DEST, amount)       # зеркало с реальными полями политики из SQL
    state = {'deals': [deal], 'convs': [], 'incomes': [], 'notes': [], 'wallets': [mirror]}
    db = m.get_session()
    try:
        policy = m._stand_transfer_policy(db, state, deal)
    finally:
        db.close()
    fp = policy['fingerprint']
    now = 1700000000000
    deal['transferClaim'] = {'byId': claimer, 'byName': 'Настя', 'role': 'operator', 'at': now,
                             'walletId': wid, 'amount': str(policy['amount']), 'fingerprint': fp}
    deal['transferConfirmation'] = {'byId': confirmer, 'byName': 'Виталий', 'role': 'findir',
                                    'at': now, 'claimFingerprint': fp, 'ownerAlone': False}
    deal['transferOwnerApproval'] = {'byId': approver, 'byName': 'Теодор', 'role': 'teodor',
                                     'at': now, 'walletId': wid, 'amount': str(policy['amount']),
                                     'fingerprint': fp}
    for key, mutate in tamper.items():
        mutate(deal)
    return state, approver


def seed_close(state, role='manager'):
    db = m.get_session()
    try:
        user = m.AdminUser(username='closeok-' + secrets.token_hex(5), display_name='QA manager',
                           role=role, password_hash='unused')
        db.add(user)
        db.flush()
        row = db.query(m.StandState).filter_by(id=1).first()
        if row is None:
            row = m.StandState(id=1)
            db.add(row)
        row.data, row.version, row.generation = json.dumps(state), 1, secrets.token_hex(16)
        db.commit()
        _seed_evidence(db, row, board=state, actor_id=user.id)
        return user.id
    finally:
        db.close()


def crm_deal():
    db = m.get_session()
    try:
        d = db.query(m.Deal).filter_by(client_name='Synthetic QA').order_by(m.Deal.id.desc()).first()
        return d.to_dict() if d else None
    finally:
        db.close()


@pytest.mark.parametrize('crm_wallet', ['omitted', 'exact'])
def test_board_approved_over_limit_close_completes_and_carries_original_approver(seeded, crm_wallet):
    # при пропущенном кошельке CRM на доске тоже нет walletId: сервер подставит кошелёк отправки сам
    tamper = {'a': lambda d: d['payout'].pop('walletId')} if crm_wallet == 'omitted' else {}
    state, approver = approved_board(15000, **tamper)
    uid = seed_close(state)
    wid = registry_id(EXCHANGE)
    extra = {} if crm_wallet == 'omitted' else {'payout_wallet_id': wid}
    data = crm_for(15000, wid, **extra)
    if crm_wallet == 'omitted':
        data.pop('payout_wallet_id')
    r = _client(uid).post('/api/stand/deals/1474/crm-close', json={'version': 1, 'crm': data})
    assert r.status_code in (200, 201), r.json
    deal = crm_deal()
    assert deal['payout_wallet_id'] == wid and deal['payout_owner_approved'] is True
    marker = deal['payout_owner_approval']
    assert marker['byId'] == approver and marker['role'] == 'teodor', 'исходный одобривший, не закрывающий'
    assert marker.get('standFingerprint') and marker['walletId'] == wid and marker['amount'] == '15000'


@pytest.mark.parametrize('case', [
    'no_approval', 'bad_fingerprint', 'same_actor', 'not_server_complete', 'approver_wrong_role',
    'amount_changed_after_approval', 'no_confirmation', 'no_claim'])
def test_close_over_limit_refused_when_board_evidence_is_missing_or_invalid(seeded, case):
    tamper = {
        'no_approval': {'a': lambda d: d.pop('transferOwnerApproval')},
        'bad_fingerprint': {'a': lambda d: d['transferOwnerApproval'].update(fingerprint='x')},
        'same_actor': {'a': lambda d: d['transferConfirmation'].update(
            byId=d['transferClaim']['byId'])},
        'not_server_complete': {'a': lambda d: d.update(serverTransferComplete=False)},
        'approver_wrong_role': {'a': lambda d: d['transferOwnerApproval'].update(role='operator')},
        'amount_changed_after_approval': {'a': lambda d: d['transfer'].update(amount=16000)},
        'no_confirmation': {'a': lambda d: d.pop('transferConfirmation')},
        'no_claim': {'a': lambda d: d.pop('transferClaim')}}[case]
    state, _ = approved_board(15000, **tamper)
    uid = seed_close(state)
    wid = registry_id(EXCHANGE)
    before = deals_for()
    r = _client(uid).post('/api/stand/deals/1474/crm-close',
                          json={'version': 1, 'crm': crm_for(15000, wid)})
    assert r.status_code in (400, 409), (case, r.json)
    assert deals_for() == before


def test_close_crm_wallet_must_equal_board_send_wallet(seeded):
    state, _ = approved_board(15000)
    uid = seed_close(state)
    r = _client(uid).post('/api/stand/deals/1474/crm-close', json={
        'version': 1, 'crm': crm_for(15000, registry_id(LEGACY))})
    assert r.status_code in (400, 409), r.json


@pytest.mark.parametrize('field', [{'payout_owner_approved': True},
                                   {'payout_owner_approval': {'byId': 1, 'role': 'teodor'}}])
def test_closing_manager_cannot_inject_approval_metadata_even_with_board_approval(seeded, field):
    state, _ = approved_board(15000)
    uid = seed_close(state)
    before = deals_for()
    r = _client(uid).post('/api/stand/deals/1474/crm-close', json={
        'version': 1, 'crm': crm_for(15000, registry_id(EXCHANGE), **field)})
    assert r.status_code in (400, 403), r.json
    assert deals_for() == before
