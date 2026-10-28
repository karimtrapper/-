"""QA пункта 5: s24 подтверждает другая роль-подписант; деньги — только по Success в сети.

Подтверждение/клейм сами по себе не доказывают отправку: переход после s23/s24
возможен только после сетевого подтверждения суммы и адресов.
"""
import copy
import time

import pytest

import app as m
from tests.qa_wallet_roles_helpers import (
    checked_put,
    make_user, client_for, put_board, board, snapshot_board, restore_board, send_deal,
    registry_id)
from tests.test_wallet_roles_qa import REALTY, EXCHANGE, LEGACY, seeded, stand  # noqa: F401
from tests.test_stand_freehold_e2e_fixes import chain  # noqa: F401
from tests.test_stand_outgoing_review import tx

DEST = 'TQgQCBXkewuW4RoieDKFP9Ko2SopBh8jso'
DEAL = 9001


@pytest.fixture
def clean_board(seeded):
    saved = snapshot_board()
    yield
    restore_board(saved)


def set_board(wallet, amount=5000, step='s23', ref=None):
    deal, mirror = send_deal(DEAL, wallet, DEST, amount, postConv='coins')
    deal['transfer']['sends'] = [{'ref': ref, 'amount': amount, 'net': 'TRC-20'}] if ref else []
    put_board({'deals': [deal], 'convs': [], 'incomes': [], 'notes': [], 'wallets': [mirror]}, 5)
    return deal


def main_deal():
    return next(d for d in board()[0]['deals'] if d['id'] == DEAL)


def advance(step):
    state, version = board()
    state['deals'][0]['step'] = step
    put_board(state, version)


def claim(client):
    return client.post('/api/stand/transfer/claim', json={'dealId': DEAL, 'version': board()[1]})


def confirm(client, version=None):
    return client.post('/api/stand/transfer/confirm',
                       json={'dealId': DEAL, 'version': board()[1] if version is None else version})


def check(client):
    return client.post('/api/stand/transfers/check', json={'dealId': DEAL})


def claimed_s24(wallet, claimer_role='operator', amount=5000, ref=None):
    set_board(wallet, amount, ref=ref)
    if claimer_role == 'findir':      # задача у первой роли «Заводит»; финансисту её передаёт менеджер
        r = client_for(make_user('operator', 'Диспетчер')).post('/api/stand/transfer/handoff', json={
            'dealId': DEAL, 'version': board()[1], 'toRole': 'findir'})
        assert r.status_code == 200, r.get_json()
    uid = make_user(claimer_role, f'Клеймер {claimer_role}')
    c = client_for(uid)
    assert claim(c).status_code == 200
    advance('s24')
    return uid, c


# ----------------------------------------------------------- самоподтверждение

@pytest.mark.parametrize('wallet,claimer', [(REALTY, 'operator'), (REALTY, 'findir'),
                                             (EXCHANGE, 'operator')])
def test_claimer_cannot_confirm_own_transfer(clean_board, wallet, claimer):
    uid, c = claimed_s24(wallet, claimer)
    before = board()
    r = confirm(c)
    assert r.status_code == 403 and 'собственную' in r.get_json()['error']
    assert board() == before and main_deal().get('transferConfirmation') is None
    assert check(c).status_code == 403


@pytest.mark.parametrize('new_role', ['teodor', 'findir', 'operator', 'admin'])
def test_role_change_of_same_actor_cannot_approve_self(clean_board, new_role):
    uid, c = claimed_s24(EXCHANGE, 'operator')
    db = m.get_session()
    try:
        db.query(m.AdminUser).filter_by(id=uid).one().role = new_role
        db.commit()
    finally:
        db.close()
    r = confirm(c)
    assert r.status_code in (403, 409), r.get_json()
    assert main_deal().get('transferConfirmation') is None
    assert check(c).status_code in (403, 409)


def test_second_account_with_same_person_role_is_a_different_actor_by_id(clean_board):
    """Идентичность — AdminUser.id: другой оператор не подтверждает, потому что роль не подписант."""
    uid, c = claimed_s24(EXCHANGE, 'operator')
    other_operator = client_for(make_user('operator'))
    assert confirm(other_operator).status_code == 403
    assert main_deal().get('transferConfirmation') is None


# ------------------------------------------------------------- допустимые роли

@pytest.mark.parametrize('wallet,claimer,confirmer,ok', [
    (REALTY, 'operator', 'teodor', True), (REALTY, 'findir', 'teodor', True),
    (REALTY, 'operator', 'findir', False), (REALTY, 'operator', 'operator', False),
    (REALTY, 'operator', 'manager', False), (REALTY, 'operator', 'admin', False),
    # Изменено по новому ТЗ: подпись у ОДНОЙ назначенной роли — первой из «Подписывает»,
    # которая не завела (обменник: финансист). Владелец подписывает после переназначения
    # менеджером (см. test_wallet_handoff_flow.py).
    (EXCHANGE, 'operator', 'findir', True), (EXCHANGE, 'operator', 'teodor', False),
    (EXCHANGE, 'operator', 'operator', False), (EXCHANGE, 'operator', 'manager', False)])
def test_confirmer_roles_follow_registry(clean_board, wallet, claimer, confirmer, ok):
    claimed_s24(wallet, claimer)
    uid = make_user(confirmer, 'Подтверждающий')
    r = confirm(client_for(uid))
    assert (r.status_code == 200) == ok, r.get_json()
    saved = main_deal().get('transferConfirmation')
    if ok:
        assert saved['byId'] == uid and saved['role'] == confirmer and saved['ownerAlone'] is False
        assert r.get_json()['confirmation'] == saved
    else:
        assert saved is None


def test_confirmation_identity_ignores_body_and_session_role(clean_board):
    claimed_s24(REALTY, 'operator')
    real = make_user('teodor')
    impostor = make_user('manager')
    c = client_for(impostor)
    with c.session_transaction() as sess:
        sess['role'] = 'teodor'
    r = c.post('/api/stand/transfer/confirm', json={
        'dealId': DEAL, 'version': board()[1], 'byId': real, 'role': 'teodor', 'actorId': real})
    assert r.status_code == 403 and main_deal().get('transferConfirmation') is None


def test_only_one_confirmer_and_repeat_is_idempotent(clean_board):
    claimed_s24(EXCHANGE, 'operator')
    a, b = make_user('findir', 'Финдир'), make_user('teodor', 'Владелец')
    assert confirm(client_for(a)).status_code == 200
    again = confirm(client_for(a))
    assert again.status_code == 200
    # Изменено по новому ТЗ: подпись назначена одной роли, владелец (не назначен) получает 403,
    # а не 409; второго подтверждения всё равно нет.
    second = confirm(client_for(b))
    assert second.status_code == 403 and main_deal()['transferConfirmation']['byId'] == a
    other_findir = confirm(client_for(make_user('findir', 'Второй финдир')))
    assert other_findir.status_code == 409 and main_deal()['transferConfirmation']['byId'] == a


def test_confirm_needs_claim_s24_fresh_version_and_matching_fingerprint(clean_board):
    set_board(REALTY)
    teodor = client_for(make_user('teodor'))
    assert confirm(teodor).status_code == 409            # шаг s23
    c = client_for(make_user('operator'))
    assert claim(c).status_code == 200
    advance('s24')
    stale = confirm(teodor, version=board()[1] - 1)
    assert stale.status_code == 409 and main_deal().get('transferConfirmation') is None
    # поручение изменено после claim -> подтверждение старого отпечатка невозможно
    state, version = board()
    state['deals'][0]['transfer']['amount'] = 4999
    put_board(state, version)
    changed = confirm(teodor)
    assert changed.status_code == 409 and main_deal().get('transferConfirmation') is None
    # claim потерян -> отказ
    state, version = board()
    state['deals'][0].pop('transferClaim')
    state['deals'][0]['transfer']['amount'] = 5000
    put_board(state, version)
    assert confirm(teodor).status_code == 409


# --------------------------------------------- деньги только по Success в сети

def settle_ready(wallet, claimer, confirmer, amount=5000):
    """s24 с распознанным claim/confirm и зарегистрированной отправкой; возвращает клиентов."""
    ref = None
    return ref


def test_confirmation_alone_never_advances_without_chain_success(clean_board, chain):
    ref = chain.ref(1)
    claimed_s24(REALTY, 'operator', ref=ref)
    teodor = client_for(make_user('teodor'))
    assert confirm(teodor).status_code == 200
    r = check(teodor)             # сеть ничего не знает про хеш
    assert main_deal()['step'] == 's24' and not main_deal().get('serverTransferComplete')
    assert not any(s.get('status') == 'confirmed' for s in main_deal()['transfer']['sends'])


def test_chain_success_without_distinct_confirmation_does_not_advance(clean_board, chain):
    chain.append(tx(1, 5000, to=DEST, sender=REALTY, ts=int(time.time() * 1000) + 1000))
    uid, c = claimed_s24(REALTY, 'operator', ref=chain.ref(1))
    teodor = client_for(make_user('teodor'))
    r = check(teodor)             # без confirm
    assert r.status_code in (403, 409), r.get_json()
    assert main_deal()['step'] == 's24' and not main_deal().get('serverTransferComplete')
    # claimer видит отказ на s24 и тоже не продвигает
    assert check(c).status_code == 403
    assert main_deal()['step'] == 's24'


def test_distinct_confirmation_plus_chain_success_advances(clean_board, chain):
    chain.append(tx(1, 5000, to=DEST, sender=REALTY, ts=int(time.time() * 1000) + 1000))
    claimed_s24(REALTY, 'operator', ref=chain.ref(1))
    teodor = client_for(make_user('teodor'))
    assert confirm(teodor).status_code == 200
    r = check(teodor)
    assert r.status_code == 200, r.get_json()
    deal = main_deal()
    assert deal['step'] == 's25' and deal['serverTransferComplete'] is True
    assert deal['transfer']['sends'][0]['status'] == 'confirmed'


@pytest.mark.parametrize('chain_amount, to, sender', [
    (2500, DEST, REALTY),                                   # сумма меньше
    (5000, 'TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn', REALTY),   # чужой получатель
    (5000, DEST, 'TVmgzMQ2zwV2DVPscBf98WRRdhrcpf5x5p')])    # чужой отправитель
def test_wrong_chain_facts_do_not_settle_even_with_confirmation(clean_board, chain, chain_amount, to, sender):
    chain.append(tx(1, chain_amount, to=to, sender=sender, ts=int(time.time() * 1000) + 1000))
    claimed_s24(REALTY, 'operator', ref=chain.ref(1))
    teodor = client_for(make_user('teodor'))
    assert confirm(teodor).status_code == 200
    check(teodor)
    deal = main_deal()
    assert deal['step'] == 's24' and not deal.get('serverTransferComplete')
    assert not any(s.get('status') == 'confirmed' for s in deal['transfer']['sends'])


# ---------------------------------------------------------------- owner alone

def owner_claim(chain_ref=None, amount=5000):
    set_board(REALTY, amount, ref=chain_ref)
    uid = make_user('teodor', 'Владелец')
    c = client_for(uid)
    r = claim(c)
    assert r.status_code == 200, r.get_json()
    return uid, c


def test_owner_alone_claim_marks_confirmation_but_not_funds(clean_board, chain):
    uid, c = owner_claim(chain.ref(2))
    deal = main_deal()
    assert deal['transferConfirmation']['ownerAlone'] is True
    assert deal['transferConfirmation']['byId'] == uid == deal['transferClaim']['byId']
    check(c)                                            # сети нет -> ничего не засчитано
    deal = main_deal()
    assert deal['step'] == 's23' and not deal.get('serverTransferComplete')
    assert not any(s.get('status') == 'confirmed' for s in deal['transfer']['sends'])


def test_owner_alone_skips_s24_only_on_verified_success(clean_board, chain):
    chain.append(tx(2, 5000, to=DEST, sender=REALTY, ts=int(time.time() * 1000) + 1000))
    uid, c = owner_claim(chain.ref(2))
    r = check(c)
    assert r.status_code == 200, r.get_json()
    deal = main_deal()
    assert deal['step'] == 's25' and deal['serverTransferComplete'] is True, 's24 пропущен автоматически'
    assert deal['transfer']['sends'][0]['status'] == 'confirmed'
    assert not any('s24' in str(e.get('text', '')) for e in deal.get('log', []))


def test_owner_alone_never_available_for_other_roles(clean_board):
    # Изменено по новому ТЗ: с обменника владелец тоже может отправить сам (owner_can_alone);
    # одиночная отправка по-прежнему только у владельца — оператор и финансист её не получают.
    set_board(EXCHANGE, 5000)
    teodor = client_for(make_user('teodor'))
    assert claim(teodor).status_code == 200
    assert main_deal()['transferConfirmation']['ownerAlone'] is True
    set_board(REALTY, 5000)
    for role in ('operator', 'findir'):
        c = client_for(make_user(role))
        state, v = board()
        state['deals'][0].pop('transferClaim', None)
        state['deals'][0].pop('transferHandoff', None)
        put_board(state, v)
        if role == 'findir':
            r = client_for(make_user('operator', 'Диспетчер')).post('/api/stand/transfer/handoff', json={
                'dealId': DEAL, 'version': board()[1], 'toRole': 'findir'})
            assert r.status_code == 200, r.get_json()
        assert claim(c).status_code == 200
        assert main_deal()['transferConfirmation'] is None if 'transferConfirmation' in main_deal() else True
        assert not (main_deal().get('transferConfirmation') or {}).get('ownerAlone')


def test_owner_alone_flag_cannot_be_forged_through_state_put(clean_board, chain):
    chain.append(tx(2, 5000, to=DEST, sender=REALTY, ts=int(time.time() * 1000) + 1000))
    set_board(REALTY, ref=chain.ref(2))
    operator = client_for(make_user('operator'))
    assert claim(operator).status_code == 200
    attacker = client_for(make_user('findir'))
    snap = attacker.get('/api/stand/state').get_json()
    forged = copy.deepcopy(snap['data'])
    forged['deals'][0]['transferConfirmation'] = {
        'byId': snap['data']['deals'][0]['transferClaim']['byId'], 'byName': 'x', 'role': 'teodor',
        'at': 1, 'claimFingerprint': snap['data']['deals'][0]['transferClaim']['fingerprint'],
        'ownerAlone': True}
    checked_put(attacker, snap['version'], forged, witness='фиксирует только сервер')
    assert main_deal().get('transferConfirmation') is None
    check(operator)
    # Изменено (решение Карима 28.10: перевод, проверенный в сети, = подписано): шаг закрывает
    # сама проверка сети, а не подделанный маркер — самого маркера на доске по-прежнему нет.
    assert main_deal().get('transferConfirmation') is None
    assert main_deal()['step'] == 's25' and main_deal().get('serverTransferComplete')


def test_state_put_cannot_skip_s24_or_advance_policy_deal(clean_board, chain):
    chain.append(tx(1, 5000, to=DEST, sender=REALTY, ts=int(time.time() * 1000) + 1000))
    claimed_s24(REALTY, 'operator', ref=chain.ref(1))
    attacker = client_for(make_user('findir'))
    for step in ('s25', 's26', 's27', 'done'):
        snap = attacker.get('/api/stand/state').get_json()
        snap['data']['deals'][0]['step'] = step
        checked_put(attacker, snap['version'], snap['data'])
        assert main_deal()['step'] == 's24', f'шаг {step} недопустим без подтверждения и сети'


# ------------------------------------------ легаси-кошелёк: прежний порядок

def test_legacy_wallet_confirm_endpoint_does_not_apply(clean_board):
    set_board(LEGACY, 5000)
    advance('s24')
    before = board()
    r = confirm(client_for(make_user('teodor')))
    assert r.status_code == 409 and board() == before


# ----- серверный гейт расчёта (poller/settle), в обход HTTP-эндпоинтов -------

def test_poller_settles_verified_transfer_without_manual_confirmation(clean_board, chain):
    # Было: «поллер не заменяет подтверждение s24». Изменено по решению Карима 28.10:
    # мультисиг публикует перевод только после всех подписей, значит проверенный перевод = подписано.
    chain.append(tx(1, 5000, to=DEST, sender=REALTY, ts=int(time.time() * 1000) + 1000))
    claimed_s24(REALTY, 'operator', ref=chain.ref(1))      # claim есть, ручной отметки нет
    m._stand_check_transfers(DEAL)                         # то же, что делает фоновый опрос
    deal = main_deal()
    assert deal['step'] == 's25' and deal.get('serverTransferComplete')
    assert 'transferConfirmation' not in deal


def test_poller_settle_ignores_forged_owner_alone_marker(clean_board, chain):
    """Было: маркер «владелец сам» от не-владельца блокировал шаг. Изменено по решению Карима 28.10:
    маркеры подтверждения на закрытие не влияют — решает проверенный перевод в сети."""
    chain.append(tx(1, 5000, to=DEST, sender=REALTY, ts=int(time.time() * 1000) + 1000))
    uid, c = claimed_s24(REALTY, 'operator', ref=chain.ref(1))
    state, version = board()
    claim_ = state['deals'][0]['transferClaim']
    state['deals'][0]['transferConfirmation'] = {
        'byId': uid, 'byName': 'x', 'role': 'operator', 'at': 1,
        'claimFingerprint': claim_['fingerprint'], 'ownerAlone': True}
    put_board(state, version)
    m._stand_check_transfers(DEAL)
    deal = main_deal()
    assert deal['step'] == 's25' and deal.get('serverTransferComplete')


def test_poller_settle_ignores_self_confirmation_marker(clean_board, chain):
    chain.append(tx(1, 5000, to=DEST, sender=REALTY, ts=int(time.time() * 1000) + 1000))
    uid, c = claimed_s24(REALTY, 'operator', ref=chain.ref(1))
    state, version = board()
    state['deals'][0]['transferConfirmation'] = {
        'byId': uid, 'byName': 'x', 'role': 'teodor', 'at': 1,
        'claimFingerprint': state['deals'][0]['transferClaim']['fingerprint'], 'ownerAlone': False}
    put_board(state, version)
    m._stand_check_transfers(DEAL)
    assert main_deal()['step'] == 's25' and main_deal().get('serverTransferComplete')   # Изменено 28.10


# ----- эквивалентные числовые представления суммы не ломают подпись -------

@pytest.mark.parametrize('stored, roundtrip', [(5000.0, 5000), (5000, 5000.0), (5000, '5000.00'),
                                                ('5000', 5000.0)])
def test_equivalent_amount_representation_keeps_claim_valid_across_state_put(clean_board, stored, roundtrip):
    set_board(REALTY, stored)
    c = client_for(make_user('operator'))
    assert claim(c).status_code == 200
    real = main_deal()['transferClaim']
    snap = c.get('/api/stand/state').get_json()
    snap['data']['deals'][0]['transfer']['amount'] = roundtrip       # как после обхода через браузер
    r = checked_put(c, snap['version'], snap['data'])
    assert r.status_code == 200, r.get_json()          # автосохранение просмотра не даёт 409
    assert main_deal()['transferClaim'] == real
    advance('s24')
    teodor = client_for(make_user('teodor'))
    ok = confirm(teodor)
    assert ok.status_code == 200, ok.get_json()       # подпись по-прежнему действительна


@pytest.mark.parametrize('changed', [5001, 4999.99, '5000.01'])
def test_actual_amount_change_after_claim_invalidates_signature(clean_board, changed):
    set_board(REALTY, 5000)
    c = client_for(make_user('operator'))
    assert claim(c).status_code == 200
    snap = c.get('/api/stand/state').get_json()
    snap['data']['deals'][0]['transfer']['amount'] = changed
    checked_put(c, snap['version'], snap['data'])
    advance('s24')
    state, v = board()
    state['deals'][0]['transfer']['amount'] = changed
    put_board(state, v)
    assert confirm(client_for(make_user('teodor'))).status_code == 409
    assert main_deal().get('transferConfirmation') is None


def test_poller_settle_ignores_confirmation_without_actor_id(clean_board, chain):
    """Запись подтверждения с верным отпечатком, но без id подтвердившего, не засчитывается."""
    chain.append(tx(1, 5000, to=DEST, sender=REALTY, ts=int(time.time() * 1000) + 1000))
    uid, c = claimed_s24(REALTY, 'operator', ref=chain.ref(1))
    state, version = board()
    state['deals'][0]['transferConfirmation'] = {
        'byId': None, 'byName': 'x', 'role': 'teodor', 'at': 1,
        'claimFingerprint': state['deals'][0]['transferClaim']['fingerprint'], 'ownerAlone': False}
    put_board(state, version)
    m._stand_check_transfers(DEAL)
    assert main_deal()['step'] == 's25' and main_deal().get('serverTransferComplete')   # Изменено 28.10
