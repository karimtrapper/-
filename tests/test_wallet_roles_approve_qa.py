"""QA пункта 6, путь задач: владельческое одобрение отправки с обменника свыше 10 000 USDT.

Одобрение ставит только аутентифицированный финансист/владелец до claim, оно привязано
к кошельку, сумме всей пачки и поручению; общий PUT состояния его подделать не может.
"""
import copy
import json

import pytest

import app as m
from tests.qa_wallet_roles_helpers import (
    checked_put,
    make_user, client_for, put_board, board, snapshot_board, restore_board, send_deal,
    registry_id)
from tests.test_wallet_roles_qa import REALTY, EXCHANGE, LEGACY, seeded, stand  # noqa: F401

DEST = 'TQgQCBXkewuW4RoieDKFP9Ko2SopBh8jso'
MSG = 'Для отправки свыше 10 000 USDT требуется подтверждение владельца'


@pytest.fixture
def clean_board(seeded):
    saved = snapshot_board()
    yield
    restore_board(saved)


def set_board(wallet, amount, step='s23', deal_id=9001):
    deal, mirror = send_deal(deal_id, wallet, DEST, amount)
    deal['step'] = step
    put_board({'deals': [deal], 'convs': [], 'incomes': [], 'notes': [], 'wallets': [mirror]}, 5)


def set_batch(amounts, wallet=EXCHANGE):
    wid = registry_id(wallet)
    deals = []
    for i, amount in enumerate(amounts):
        d, mirror = send_deal(9001 + i, wallet, DEST, amount, cnvId=1,
                              conv=[9001 + j for j in range(len(amounts)) if j != i] if i == 0 else [])
        deals.append(d)
    put_board({'deals': deals, 'incomes': [], 'notes': [], 'wallets': [mirror],
               'convs': [{'id': 1, 'walletId': wid, 'status': 'received',
                          'sources': [{'dealId': d['id']} for d in deals]}]}, 5)


def main_deal(deal_id=9001):
    return next(d for d in board()[0]['deals'] if d['id'] == deal_id)


def approve(client, deal_id=9001, version=None, **extra):
    return client.post('/api/stand/transfer/approve',
                       json={'dealId': deal_id, 'version': board()[1] if version is None else version,
                             **extra})


def claim(client, deal_id=9001):
    return client.post('/api/stand/transfer/claim', json={'dealId': deal_id, 'version': board()[1]})


# ----------------------------------------------------------------- роли

@pytest.mark.parametrize('role', ['findir', 'teodor'])
def test_financier_or_owner_approves_and_operator_then_claims(clean_board, role):
    set_board(EXCHANGE, 15000)
    operator = client_for(make_user('operator', 'Настя'))
    assert claim(operator).status_code == 400            # до одобрения нельзя
    uid = make_user(role, 'Одобряющий')
    r = approve(client_for(uid))
    assert r.status_code == 200, r.get_json()
    marker = main_deal()['transferOwnerApproval']
    assert marker['byId'] == uid and marker['role'] == role
    assert marker['walletId'] == registry_id(EXCHANGE) and marker['amount'] == '15000'
    assert r.get_json()['approval'] == marker
    assert claim(operator).status_code == 200            # теперь оператор берёт отправку
    assert main_deal()['transferClaim']['role'] == 'operator'


@pytest.mark.parametrize('role', ['operator', 'manager', 'admin', 'buyer'])
def test_other_roles_cannot_approve(clean_board, role):
    set_board(EXCHANGE, 15000)
    before = board()
    assert approve(client_for(make_user(role))).status_code == 403
    assert approve(m.app.test_client()).status_code in (401, 403)
    assert board() == before


def test_approval_identity_comes_from_session_not_body(clean_board):
    set_board(EXCHANGE, 15000)
    real = make_user('findir')
    other = make_user('teodor', 'Чужой владелец')
    r = approve(client_for(real), byId=other, role='teodor', actorId=other, byName='Чужой владелец')
    assert r.status_code == 200
    marker = main_deal()['transferOwnerApproval']
    assert marker['byId'] == real and marker['role'] == 'findir'


def test_exchange_roles_after_approval_are_unchanged(clean_board):
    """Одобрение не расширяет инициаторов: финдир по-прежнему не начинает отправку.

    Изменено по новому ТЗ (wallet-handoff): владелец может отправить с обменника сам
    (owner_can_alone), поэтому его claim после одобрения разрешён и идёт без s24."""
    set_board(EXCHANGE, 15000)
    assert approve(client_for(make_user('findir'))).status_code == 200
    for role in ('findir', 'manager', 'admin'):
        assert claim(client_for(make_user(role))).status_code == 403
    assert main_deal().get('transferClaim') is None
    assert claim(client_for(make_user('teodor'))).status_code == 200
    assert main_deal()['transferConfirmation']['ownerAlone'] is True


# ---------------------------------------------------- когда одобрение применимо

def test_approval_not_needed_or_available_in_other_situations(clean_board):
    findir = client_for(make_user('findir'))
    set_board(EXCHANGE, 10000)                       # ровно лимит: не нужно
    assert approve(findir).status_code == 409
    set_board(REALTY, 50000)                         # у недвижимости нет лимита
    assert approve(findir).status_code == 409
    set_board(LEGACY, 50000)                         # легаси — прежний порядок
    assert approve(findir).status_code == 409
    set_board(EXCHANGE, 15000, step='s22')           # не тот шаг
    assert approve(findir).status_code == 409
    set_board(EXCHANGE, 15000)
    assert approve(findir, version=board()[1] - 1).status_code == 409
    assert main_deal().get('transferOwnerApproval') is None


def test_approval_after_claim_is_refused(clean_board):
    set_board(EXCHANGE, 5000)
    assert claim(client_for(make_user('operator'))).status_code == 200
    state, v = board()
    state['deals'][0]['transfer']['amount'] = 15000     # прямая правка БД: сумма выросла после claim
    put_board(state, v)
    assert approve(client_for(make_user('findir'))).status_code == 409


def test_repeat_approval_is_idempotent(clean_board):
    set_board(EXCHANGE, 15000)
    findir = client_for(make_user('findir'))
    first = approve(findir).get_json()['approval']
    again = approve(findir)
    assert again.status_code == 200 and main_deal()['transferOwnerApproval'] == first


# ------------------------------------------------- привязка к сумме и поручению

def test_approval_is_bound_to_amount_and_order(clean_board):
    set_board(EXCHANGE, 15000)
    assert approve(client_for(make_user('findir'))).status_code == 200
    operator = client_for(make_user('operator'))
    for mutate in (lambda d: d['transfer'].update(amount=16000),
                   lambda d: d['transfer'].update(addr='TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn'),
                   lambda d: d.update(ippsPayoutOrder={'amount': 15000, 'address': DEST})):
        set_board(EXCHANGE, 15000)
        assert approve(client_for(make_user('findir'))).status_code == 200
        state, v = board()
        mutate(state['deals'][0])
        put_board(state, v)                     # изменение поручения после одобрения
        r = claim(operator)
        assert r.status_code == 400 and MSG in r.get_json()['error'], r.get_json()
        assert main_deal().get('transferClaim') is None


def test_state_put_cannot_forge_or_copy_approval(clean_board):
    set_board(EXCHANGE, 15000)
    operator = client_for(make_user('operator'))
    snap = operator.get('/api/stand/state').get_json()
    forged = copy.deepcopy(snap['data'])
    forged['deals'][0]['transferOwnerApproval'] = {
        'byId': 1, 'byName': 'x', 'role': 'teodor', 'at': 1, 'walletId': registry_id(EXCHANGE),
        'amount': '15000', 'fingerprint': 'anything'}
    checked_put(operator, snap['version'], forged, witness='фиксирует только сервер')
    assert main_deal().get('transferOwnerApproval') is None
    assert claim(operator).status_code == 400
    # одобрение, поставленное сервером, нельзя стереть общим сохранением
    assert approve(client_for(make_user('findir'))).status_code == 200
    real = main_deal()['transferOwnerApproval']
    snap = operator.get('/api/stand/state').get_json()
    snap['data']['deals'][0].pop('transferOwnerApproval')
    checked_put(operator, snap['version'], snap['data'], witness='фиксирует только сервер')
    assert main_deal()['transferOwnerApproval'] == real


# -------------------------------------------------------------------- пачка

def test_mixed_batch_each_under_limit_but_sum_over_needs_approval(clean_board):
    set_batch([6000, 6000])                           # по 6000, вместе 12000
    operator = client_for(make_user('operator'))
    r = claim(operator)
    assert r.status_code == 400 and MSG in r.get_json()['error']
    findir = client_for(make_user('findir'))
    assert approve(findir, deal_id=9002).status_code == 200      # через побочную сделку
    marker = main_deal(9001)['transferOwnerApproval']
    assert marker['amount'] == '12000', 'одобрение привязано к сумме всей пачки на основной сделке'
    assert main_deal(9002).get('transferOwnerApproval') is None
    assert claim(operator).status_code == 200


def test_batch_change_after_approval_invalidates_it(clean_board):
    set_batch([6000, 6000])
    assert approve(client_for(make_user('findir'))).status_code == 200
    state, v = board()
    state['deals'][1]['transfer']['amount'] = 7000     # сумма пачки изменилась
    put_board(state, v)
    r = claim(client_for(make_user('operator')))
    assert r.status_code == 400 and MSG in r.get_json()['error']


def test_batch_exactly_at_limit_needs_no_approval(clean_board):
    set_batch([6000, 4000])
    assert claim(client_for(make_user('operator'))).status_code == 200


@pytest.mark.parametrize('stored, roundtrip', [(15000.0, 15000), (15000, 15000.0), (15000, '15000.00')])
def test_equivalent_amount_representation_keeps_approval_valid(clean_board, stored, roundtrip):
    set_board(EXCHANGE, stored)
    assert approve(client_for(make_user('findir'))).status_code == 200
    operator = client_for(make_user('operator'))
    snap = operator.get('/api/stand/state').get_json()
    snap['data']['deals'][0]['transfer']['amount'] = roundtrip
    stored, sent = main_deal(), snap['data']['deals'][0]
    diff = {k: (stored.get(k), sent.get(k)) for k in set(stored) | set(sent)
            if json.dumps(stored.get(k), sort_keys=True) != json.dumps(sent.get(k), sort_keys=True)}
    r = checked_put(operator, snap['version'], snap['data'])
    assert r.status_code == 200, (r.get_json().get('error'), 'отличия сохранённой и присланной сделки:', diff)
    assert claim(operator).status_code == 200, 'одобрение действует при эквивалентной записи суммы'


def test_real_amount_change_before_claim_is_not_a_noop_autosave(clean_board):
    """Канонизация равных чисел не даёт оператору менять реальные суммы поручения до claim."""
    set_board(EXCHANGE, 15000)
    assert approve(client_for(make_user('findir'))).status_code == 200
    operator = client_for(make_user('operator'))
    snap = operator.get('/api/stand/state').get_json()
    snap['data']['deals'][0]['transfer']['amount'] = 16000
    r = checked_put(operator, snap['version'], snap['data'])
    stored = main_deal()['transfer']['amount']
    claim_ = claim(operator)
    # либо PUT отвергнут и сумма прежняя, либо сумма изменена и одобрение утратило силу
    assert (r.status_code == 409 and float(stored) == 15000) or (
        claim_.status_code == 400 and MSG in claim_.get_json()['error']), (r.status_code, stored)
    assert main_deal().get('transferClaim') is None or float(stored) == 15000


@pytest.mark.parametrize('wallet,amount,role', [(EXCHANGE, 5000, 'operator'), (REALTY, 5000, 'operator'),
                                                (REALTY, 5000, 'findir')])
def test_unchanged_roundtrip_put_before_claim_is_accepted(clean_board, wallet, amount, role):
    """Просмотр s23 без правок (GET -> PUT того же состояния) инициатором не должен давать 409."""
    set_board(wallet, amount)
    c = client_for(make_user(role))
    snap = c.get('/api/stand/state').get_json()
    stored, sent = main_deal(), snap['data']['deals'][0]
    diff = {k: (stored.get(k), sent.get(k)) for k in set(stored) | set(sent)
            if json.dumps(stored.get(k), sort_keys=True) != json.dumps(sent.get(k), sort_keys=True)}
    r = checked_put(c, snap['version'], snap['data'])
    assert r.status_code == 200, (r.get_json().get('error'), 'отличия:', diff)
