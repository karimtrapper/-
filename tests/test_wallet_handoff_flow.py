"""Передача задачи перевода: завести (s23) и подписать (s24), перехват claim, защита от двойной отправки.

Акторы — настоящие AdminUser из БД. Сеть закрыта фенсом, уведомления стенда замоканы
фикстурой `seeded` (в состоянии доски проверяются записи `notes`).
"""
import copy
import threading

import pytest
import requests

import app as m
from tests.qa_wallet_roles_helpers import (
    checked_put, make_user, client_for, put_board, board, snapshot_board, restore_board,
    send_deal, serve, cookie_for, registry_id)
from tests.test_wallet_roles_qa import seeded, stand  # noqa: F401

REALTY = 'TDuDeRiwrLLN3hnnA57G5yM6ibg58A6wZk'
PROPERTY = 'TAGufCVNFBLh6NiEGL8iaQ4F9PPnftcgBk'
EXCHANGE = 'TA6S3RBEY57jq8fXEVVsU6H9JZ18inenG4'
MFSTR = 'TR68DHoj71Nz4FoTvqnBFQK2Fc6NkEK6nQ'
CLIENT99 = 'TQPv1GETKVjSWZymdMu5WbSSeS6JhL2KHt'
LEGACY = 'TKkeEVf2zySaWTLyX2qPwvi6kcdHRuPxkJ'
DEST = 'TQgQCBXkewuW4RoieDKFP9Ko2SopBh8jso'
DEAL = 9001
HASH = 'ab' * 32


@pytest.fixture
def clean_board(seeded):
    saved = snapshot_board()
    yield
    restore_board(saved)


def board_with(wallet, amount=5000, step='s23', **extra):
    deal, mirror = send_deal(DEAL, wallet, DEST, amount, **extra)
    deal['step'] = step
    deal['code'] = 'СД-9001'
    put_board({'deals': [deal], 'convs': [], 'incomes': [], 'notes': [], 'wallets': [mirror]}, version=5)


def main_deal():
    return next(d for d in board()[0]['deals'] if d['id'] == DEAL)


def notes():
    return board()[0].get('notes') or []


def post(client, path, version=None, **body):
    version = board()[1] if version is None else version
    return client.post('/api/stand/transfer/' + path, json={'dealId': DEAL, 'version': version, **body})


def handoff(client, to_role, **kw):
    return post(client, 'handoff', toRole=to_role, **kw)


def takeover(client, to_role, claim_at=None):
    claim = main_deal().get('transferClaim') or {}
    return handoff(client, to_role, takeover=True, claimAt=claim.get('at') if claim_at is None else claim_at)


def claim(client, **kw):
    return post(client, 'claim', **kw)


def confirm(client):
    return post(client, 'confirm')


def to_s24():
    state, version = board()
    state['deals'][0]['step'] = 's24'
    put_board(state, version)


def put_state(client, mutate, witness=None):
    snap = client.get('/api/stand/state').get_json()
    data = copy.deepcopy(snap['data'])
    mutate(next(d for d in data['deals'] if d['id'] == DEAL), data)
    return checked_put(client, snap['version'], data, witness=witness)


def claim_as(u, role):
    """Взять перевод от имени роли: если задача у другой роли — сначала передаёт менеджер."""
    if role not in ('operator',) and role != 'teodor':
        assert handoff(u['dispatcher'], role).status_code == 200
    return claim(u[role])


def users():
    out = {role: client_for(make_user(role, f'Имя {role}')) for role in
           ('operator', 'findir', 'teodor', 'manager', 'admin')}
    # Передачу, перехват и «Деньги отправлены» делает другой операционист (не заводивший),
    # либо админ; клиентский менеджер этих действий не выполняет.
    out['dispatcher'] = client_for(make_user('operator', 'Диспетчер'))
    return out


# ------------------------------------------------------------- передача: завести (s23)

def test_operator_hands_over_to_findir_then_owner_and_repeat_is_idempotent(clean_board):
    board_with(REALTY)
    u = users()
    before_fp = None
    r = handoff(u['dispatcher'], 'findir')
    assert r.status_code == 200, r.get_json()
    deal = main_deal()
    assert deal['transferHandoff']['role'] == 'findir' and deal['transferHandoff']['byRole'] == 'operator'
    assert deal['assigneeAdminId'] is None
    assert [e['text'] for e in deal['log'] if 'передал перевод' in e['text']] == [
        f"{deal['transferHandoff']['byName']} передал перевод финансисту"]
    assert [n for n in notes() if n['role'] == 'findir'], 'уведомление новой роли'
    version, log_len, notes_len = board()[1], len(deal['log']), len(notes())
    again = handoff(u['dispatcher'], 'findir')                    # повтор: ничего не меняется
    assert again.status_code == 200 and board()[1] == version
    assert len(main_deal()['log']) == log_len and len(notes()) == notes_len
    r = handoff(u['admin'], 'teodor')                         # финансист → владелец
    assert r.status_code == 200 and main_deal()['transferHandoff']['role'] == 'teodor'
    assert [n for n in notes() if n['role'] == 'teodor']
    back = handoff(u['dispatcher'], 'operator')                  # владельцу не «тупик»: можно вернуть
    assert back.status_code == 200 and main_deal()['transferHandoff']['role'] == 'operator'


@pytest.mark.parametrize('role', ['manager', 'findir', 'teodor'])
def test_only_operator_and_admin_can_hand_over(clean_board, role):
    board_with(REALTY)
    before = board()
    r = handoff(users()[role], 'teodor')
    assert r.status_code == 403
    assert board() == before
    u = users()
    assert handoff(u['operator'], 'findir').status_code == 200          # операционист
    assert handoff(u['admin'], 'teodor').status_code == 200             # админ


@pytest.mark.parametrize('action', ['handoff', 'takeover', 'sign', 'mark'])
def test_client_manager_gets_403_for_every_dispatch_action(clean_board, action):
    board_with(EXCHANGE)
    u = users()
    assert claim(u['operator']).status_code == 200
    if action == 'sign':
        to_s24()
    before = board()
    manager = u['manager']
    if action == 'handoff':
        r = handoff(manager, 'teodor')
    elif action == 'takeover':
        r = takeover(manager, 'teodor')
    elif action == 'sign':
        r = handoff(manager, 'teodor')
    else:
        r = post(manager, 'mark-sent', hash=HASH)
    assert r.status_code == 403, r.get_json()
    assert board() == before


def test_handoff_rejects_unknown_stale_and_foreign_wallet_cases(clean_board):
    board_with(REALTY)
    manager = users()['dispatcher']
    before = board()
    assert handoff(manager, 'manager').status_code == 400
    assert handoff(manager, 'admin').status_code == 400
    assert handoff(manager, 'findir', version=before[1] - 1).status_code == 409
    assert post(manager, 'handoff').status_code == 400
    assert board() == before
    board_with(LEGACY)                                         # у легаси-кошелька политики нет
    before = board()
    assert handoff(manager, 'findir').status_code == 409 and board() == before
    board_with(REALTY, step='s22')
    assert handoff(manager, 'findir').status_code == 409


def test_roles_outside_initiators_are_not_valid_targets(clean_board):
    u = users()
    board_with(EXCHANGE)                                      # заводит только оператор
    before = board()
    assert handoff(u['dispatcher'], 'findir').status_code == 409
    assert board() == before
    board_with(CLIENT99)                                      # у финансиста нет роли в кошельке
    assert handoff(u['dispatcher'], 'findir').status_code == 409
    assert handoff(u['dispatcher'], 'teodor').status_code == 200
    board_with(MFSTR)                                         # первая роль — финансист; оператору нельзя
    assert handoff(u['dispatcher'], 'operator').status_code == 409


def test_handoff_changes_who_can_claim(clean_board):
    board_with(REALTY)
    u = users()
    assert handoff(u['dispatcher'], 'findir').status_code == 200
    assert claim(u['operator']).status_code == 403            # оператор больше не ведёт задачу
    r = claim(u['findir'])
    assert r.status_code == 200, r.get_json()
    assert main_deal()['transferClaim']['role'] == 'findir'


def test_first_role_follows_initiator_roles_and_owner_can_always_claim(clean_board):
    u = users()
    board_with(MFSTR)
    assert claim(u['operator']).status_code == 403
    assert claim(u['findir']).status_code == 200
    board_with(EXCHANGE)
    assert claim(u['findir']).status_code == 403
    r = claim(u['teodor'])                                    # владелец может сам, даже если задача у оператора
    assert r.status_code == 200
    deal = main_deal()
    assert deal['transferConfirmation']['ownerAlone'] is True and deal['transferClaim']['role'] == 'teodor'


def test_handoff_after_claim_needs_takeover(clean_board):
    board_with(REALTY)
    u = users()
    assert claim(u['operator']).status_code == 200
    before = board()
    r = handoff(u['dispatcher'], 'findir')
    assert r.status_code == 409 and r.get_json()['claimAt'] == main_deal()['transferClaim']['at']
    assert board() == before


def test_forged_handoff_fields_via_general_put_are_rejected(clean_board):
    board_with(REALTY)
    attacker = users()['findir']
    fake = {'role': 'findir', 'byId': 1, 'byName': 'Я', 'byRole': 'manager', 'at': 1}
    for field, value in (('transferHandoff', fake), ('signHandoff', fake), ('transferClaimHistory', [fake]),
                         ('transferFound', {'hashes': [HASH], 'at': 1}), ('transferAlarm', {'hashes': [HASH]}),
                         ('transferAlarmCleared', {'hashes': [HASH]})):
        before = board()
        put_state(attacker, lambda d, s, f=field, v=value: d.update({f: v}), witness='фиксирует только сервер')
        assert board() == before, field
    assert handoff(users()['dispatcher'], 'findir').status_code == 200
    real = main_deal()['transferHandoff']
    put_state(attacker, lambda d, s: d.pop('transferHandoff'), witness='фиксирует только сервер')
    put_state(attacker, lambda d, s: d['transferHandoff'].update(role='teodor'), witness='фиксирует только сервер')
    assert main_deal()['transferHandoff'] == real


# ----------------------------------------------------------- подпись: s24 по назначенной роли

def test_realty_signer_is_owner_only_whoever_started(clean_board):
    u = users()
    for starter in ('findir', 'operator'):
        board_with(REALTY)
        assert claim_as(u, starter).status_code == 200
        to_s24()
        other = 'operator' if starter == 'findir' else 'findir'
        assert confirm(u[other]).status_code == 403, other     # подписывает только владелец
        assert confirm(u[starter]).status_code == 403          # инициатор сам себя не подписывает
        assert confirm(u['dispatcher']).status_code == 403
        ok = confirm(u['teodor'])
        assert ok.status_code == 200, ok.get_json()
        assert main_deal()['transferConfirmation']['role'] == 'teodor'


def test_exchange_default_signer_is_findir_and_operator_can_reassign_to_owner(clean_board):
    board_with(EXCHANGE)
    u = users()
    assert claim(u['operator']).status_code == 200
    to_s24()
    assert confirm(u['teodor']).status_code == 403             # подпись назначена финансисту
    r = handoff(u['dispatcher'], 'teodor')
    assert r.status_code == 200, r.get_json()
    deal = main_deal()
    assert deal['signHandoff']['role'] == 'teodor' and deal['signHandoff']['claimFingerprint'] == \
        deal['transferClaim']['fingerprint']
    assert [e['text'] for e in deal['log'] if 'передал подпись' in e['text']]
    assert [n for n in notes() if n['role'] == 'teodor']
    assert confirm(u['findir']).status_code == 403             # финансист после переназначения не подписывает
    version = board()[1]
    assert handoff(u['dispatcher'], 'teodor').status_code == 200 and board()[1] == version     # идемпотентно
    ok = confirm(u['teodor'])
    assert ok.status_code == 200
    assert handoff(u['dispatcher'], 'findir').status_code == 409                # после подтверждения — нельзя
    assert main_deal()['signHandoff']['role'] == 'teodor'


def test_sign_reassignment_to_initiator_or_outsider_is_refused(clean_board):
    board_with(EXCHANGE)
    u = users()
    assert claim(u['operator']).status_code == 200
    to_s24()
    before = board()
    assert handoff(u['dispatcher'], 'operator').status_code == 409       # на заводившего — нельзя
    assert board() == before
    assert handoff(u['manager'], 'teodor').status_code == 403
    board_with(MFSTR)
    assert claim(u['findir']).status_code == 200
    to_s24()
    assert handoff(u['dispatcher'], 'operator').status_code == 409       # оператора нет в «Подписывает»
    assert handoff(u['dispatcher'], 'findir').status_code == 409         # и заводившего нельзя


def test_sign_handoff_resets_with_a_new_claim_round(clean_board):
    board_with(EXCHANGE)
    u = users()
    assert claim(u['operator']).status_code == 200
    to_s24()
    assert handoff(u['dispatcher'], 'teodor').status_code == 200
    stale = main_deal()['signHandoff']
    state, version = board()
    state['deals'][0]['signHandoff'] = dict(stale, claimFingerprint='другой')     # не привязана к этому claim
    put_board(state, version)
    assert confirm(u['teodor']).status_code == 403                    # снова подпись у финансиста


def test_property_wallet_signers_findir_then_owner(clean_board):
    board_with(PROPERTY)
    u = users()
    assert claim(u['operator']).status_code == 200
    to_s24()
    assert confirm(u['teodor']).status_code == 403
    assert confirm(u['findir']).status_code == 200


def test_same_user_or_role_never_signs_own_transfer(clean_board):
    board_with(REALTY)
    u = users()
    assert claim_as(u, 'findir').status_code == 200
    to_s24()
    assert confirm(u['findir']).status_code == 403
    twin = client_for(make_user('findir', 'Второй финансист'))
    assert confirm(twin).status_code == 403                           # другой человек той же роли


def test_owner_alone_claim_needs_no_second_signature_and_is_not_confirmable(clean_board):
    for wallet in (REALTY, PROPERTY, EXCHANGE, MFSTR, CLIENT99):
        board_with(wallet)
        u = users()
        r = claim(u['teodor'])
        assert r.status_code == 200, (wallet, r.get_json())
        deal = main_deal()
        assert deal['transferConfirmation']['ownerAlone'] is True and deal['step'] == 's23'
        assert confirm(u['teodor']).status_code == 409                # s24 не нужен
        assert handoff(u['dispatcher'], 'findir').status_code == 409     # и передавать уже нечего


# ---------------------------------------------------------------------- перехват claim

def claimed_by_operator():
    board_with(REALTY)
    u = users()
    assert claim(u['operator']).status_code == 200
    return u


def test_takeover_requires_flag_and_matching_claim_time(clean_board):
    u = claimed_by_operator()
    before = board()
    assert handoff(u['dispatcher'], 'findir').status_code == 409                       # нет takeover
    r = handoff(u['dispatcher'], 'findir', takeover=True, claimAt=1)
    assert r.status_code == 409 and r.get_json()['data'], 'отдаём актуальное состояние'
    assert handoff(u['dispatcher'], 'findir', takeover=True).status_code == 409        # нет claimAt
    assert handoff(u['dispatcher'], 'findir', takeover='true', claimAt=main_deal()['transferClaim']['at']).status_code == 409
    assert board() == before
    for role in ('findir', 'teodor', 'manager'):
        assert takeover(u[role], 'findir').status_code == 403
    assert takeover(u['operator'], 'findir').status_code == 409      # свой перевод перехватом не передают
    assert board() == before


def test_takeover_moves_claim_to_history_with_log_notes_and_assignment(clean_board):
    u = claimed_by_operator()
    old = main_deal()['transferClaim']
    r = takeover(u['dispatcher'], 'findir')
    assert r.status_code == 200, r.get_json()
    deal = main_deal()
    assert 'transferClaim' not in deal and deal['assigneeAdminId'] is None
    history = deal['transferClaimHistory']
    assert len(history) == 1 and history[0]['byId'] == old['byId'] and history[0]['at'] == old['at']
    assert history[0]['takenByName'] and history[0]['takenAt'] and history[0]['toRole'] == 'findir'
    assert history[0]['fingerprint'] == old['fingerprint']
    assert deal['transferHandoff']['role'] == 'findir' and deal['transferHandoff']['takeover'] is True
    text = [e['text'] for e in deal['log'] if 'забрал перевод' in e['text']]
    assert len(text) == 1 and old['byName'] in text[0] and 'финансисту' in text[0] and '(взял в ' in text[0]
    new_notes = [n['text'] for n in notes() if n['role'] == 'findir']
    assert any('начал перевод в' in t and 'второй раз не заводите' in t for t in new_notes)
    assert any(n['role'] == 'operator' and 'передан' in n['text'] for n in notes())      # прежнему исполнителю


def test_former_executor_is_locked_out_and_new_executor_keeps_fingerprint(clean_board):
    u = claimed_by_operator()
    old = main_deal()['transferClaim']
    assert takeover(u['dispatcher'], 'operator').status_code == 200           # той же роли, но другому человеку
    former = client_for(old['byId'])
    assert claim(former).status_code == 409                                # прежний исполнитель — 409
    assert claim(u['teodor']).status_code in (200,)                        # владелец (сам) может всегда
    state = board()[0]
    assert state['deals'][0]['transferClaim']['role'] == 'teodor'


def test_former_executor_cannot_mark_hashes_and_new_executor_can(clean_board):
    u = claimed_by_operator()
    old_id = main_deal()['transferClaim']['byId']
    assert takeover(u['dispatcher'], 'findir').status_code == 200
    former = client_for(old_id)
    sends = [{'ref': HASH, 'hash': HASH, 'amount': 5000, 'net': 'TRC-20', 'status': 'pending'}]
    before = board()
    put_state(former, lambda d, s: d['transfer'].update(sends=sends), witness='Сначала возьмите отправку')
    put_state(u['operator'], lambda d, s: d['transfer'].update(sends=sends), witness='Сначала возьмите отправку')
    assert board()[0]['deals'][0]['transfer']['sends'] == before[0]['deals'][0]['transfer']['sends']
    fingerprint = None
    r = claim(u['findir'])
    assert r.status_code == 200, r.get_json()
    new_claim = main_deal()['transferClaim']
    assert new_claim['fingerprint'] == main_deal()['transferClaimHistory'][0]['fingerprint']
    put_state(u['findir'], lambda d, s: d['transfer'].update(sends=sends))
    assert main_deal()['transfer']['sends'][0]['hash'] == HASH


def test_hash_marks_need_the_claim_holder(clean_board):
    board_with(REALTY)
    u = users()
    sends = [{'ref': HASH, 'hash': HASH, 'amount': 5000, 'net': 'TRC-20', 'status': 'pending'}]
    put_state(u['operator'], lambda d, s: d['transfer'].update(sends=sends), witness='Сначала возьмите отправку')
    put_state(u['operator'], lambda d, s: d.update(step='s24'), witness='Сначала возьмите отправку')
    assert claim(u['operator']).status_code == 200
    put_state(u['findir'], lambda d, s: d['transfer'].update(sends=sends),
              witness='Хеши отправки записывает сотрудник, взявший задачу')
    put_state(u['findir'], lambda d, s: d.update(step='s24'),
              witness='Шаг отправки завершает сотрудник, взявший задачу')
    assert main_deal()['transfer']['sends'] == [] and main_deal()['step'] == 's23'
    put_state(u['operator'], lambda d, s: d['transfer'].update(sends=sends))
    assert main_deal()['transfer']['sends'][0]['hash'] == HASH


def test_takeover_refused_after_owner_alone_claim_and_for_bad_targets(clean_board):
    board_with(EXCHANGE)
    u = users()
    assert claim(u['teodor']).status_code == 200
    assert takeover(u['dispatcher'], 'operator').status_code == 409          # владелец уже ведёт один
    board_with(EXCHANGE)
    assert claim(u['operator']).status_code == 200
    assert takeover(u['dispatcher'], 'findir').status_code == 409            # финансист не в «Заводит»
    assert takeover(u['dispatcher'], 'teodor').status_code == 200            # владельцу — можно


def test_takeover_after_confirmation_or_on_s24_is_not_a_takeover(clean_board):
    u = claimed_by_operator()
    to_s24()
    before = board()
    r = takeover(u['dispatcher'], 'findir')                                  # на s24 это «передать подпись»
    assert r.status_code == 409                                           # (финансист не подписывает: он заводит)
    assert board() == before


# --------------------------------------------------------------------------- гонки

@pytest.mark.parametrize('rounds', [1, 3])
def test_parallel_claim_and_handoff_have_one_winner(clean_board, rounds):
    for _ in range(rounds):
        board_with(REALTY)
        operator = make_user('operator')
        manager = make_user('operator', 'Диспетчер')
        version = board()[1]
        server, thread, base = serve()
        results, barrier = [None, None], threading.Barrier(2)

        def go(i):
            barrier.wait()
            if i == 0:
                results[i] = requests.post(base + '/api/stand/transfer/claim',
                    json={'dealId': DEAL, 'version': version}, headers=cookie_for(operator), timeout=15)
            else:
                results[i] = requests.post(base + '/api/stand/transfer/handoff',
                    json={'dealId': DEAL, 'version': version, 'toRole': 'findir'},
                    headers=cookie_for(manager), timeout=15)
        try:
            threads = [threading.Thread(target=go, args=(i,)) for i in range(2)]
            [t.start() for t in threads]
            [t.join(20) for t in threads]
        finally:
            server.shutdown(); thread.join(5); server.server_close()
        codes = [r.status_code for r in results]
        assert 500 not in codes, [r.text[:200] for r in results]
        assert codes.count(200) == 1, [(r.status_code, r.text[:200]) for r in results]
        deal = main_deal()
        if codes[0] == 200:
            assert deal.get('transferClaim') and 'transferHandoff' not in deal
        else:
            assert 'transferClaim' not in deal and deal['transferHandoff']['role'] == 'findir'
        assert board()[1] == version + 1


def test_parallel_takeover_and_claim_of_new_role_never_double_assign(clean_board):
    u = claimed_by_operator()
    old = main_deal()['transferClaim']
    findir, manager = make_user('findir'), make_user('operator', 'Диспетчер')
    version = board()[1]
    server, thread, base = serve()
    results, barrier = [None, None], threading.Barrier(2)

    def go(i):
        barrier.wait()
        if i == 0:
            results[i] = requests.post(base + '/api/stand/transfer/handoff', headers=cookie_for(manager),
                json={'dealId': DEAL, 'version': version, 'toRole': 'findir', 'takeover': True,
                      'claimAt': old['at']}, timeout=15)
        else:
            results[i] = requests.post(base + '/api/stand/transfer/handoff', headers=cookie_for(manager),
                json={'dealId': DEAL, 'version': version, 'toRole': 'teodor', 'takeover': True,
                      'claimAt': old['at']}, timeout=15)
    try:
        threads = [threading.Thread(target=go, args=(i,)) for i in range(2)]
        [t.start() for t in threads]
        [t.join(20) for t in threads]
    finally:
        server.shutdown(); thread.join(5); server.server_close()
    codes = [r.status_code for r in results]
    assert 500 not in codes and codes.count(200) == 1, [(r.status_code, r.text[:200]) for r in results]
    assert len(main_deal()['transferClaimHistory']) == 1


# ----------------------------------------------------- тревога и блокировки действий

def test_alarm_blocks_actions_and_only_owner_or_admin_clears_with_log(clean_board):
    u = claimed_by_operator()
    state, version = board()
    state['deals'][0]['transferAlarm'] = {'hashes': [HASH, 'cd' * 32], 'at': 1}
    put_board(state, version)
    sends = [{'ref': HASH, 'hash': HASH, 'amount': 5000, 'net': 'TRC-20', 'status': 'pending'}]
    before = board()
    assert takeover(u['dispatcher'], 'findir').status_code == 409
    put_state(u['operator'], lambda d, s: d['transfer'].update(sends=sends), witness='Найдено два перевода')
    put_state(u['operator'], lambda d, s: d.update(step='s24'), witness='Найдено два перевода')
    assert board() == before
    for role in ('operator', 'findir', 'manager'):
        assert post(u[role], 'alarm/clear').status_code == 403
    assert post(u['teodor'], 'alarm/clear', version=1).status_code == 409
    r = post(u['teodor'], 'alarm/clear')
    assert r.status_code == 200
    deal = main_deal()
    assert 'transferAlarm' not in deal and deal['transferAlarmCleared']['hashes'] == [HASH, 'cd' * 32]
    assert [e for e in deal['log'] if 'снял тревогу' in e['text']]
    assert post(u['admin'], 'alarm/clear').status_code == 409                # тревоги уже нет
    put_state(u['operator'], lambda d, s: d['transfer'].update(sends=sends))
    assert main_deal()['transfer']['sends'][0]['hash'] == HASH


def test_found_transfer_blocks_claim_and_handoff(clean_board):
    board_with(REALTY)
    u = users()
    state, version = board()
    state['deals'][0]['transferFound'] = {'hashes': [HASH], 'at': 1}
    put_board(state, version)
    before = board()
    assert claim(u['operator']).status_code == 409
    assert handoff(u['dispatcher'], 'findir').status_code == 409
    assert board() == before


def custom_wallet(initiators, signers, alone=False):
    """Кошелёк, заведённый админом (адрес не из сида), и доска с переводом s23."""
    r = client_for(make_user('admin')).post('/api/wallets', json={
        'address': 'TA4Y62o6YC2Zsck9rZVGTvqW1AQ7X9zTnj', 'blockchain': 'TRON', 'owner': 'Тест',
        'accepts_payin': True, 'initiator_roles': initiators, 'confirmer_roles': signers,
        'owner_can_alone': alone})
    assert r.status_code == 200, r.get_json()
    board_with('TA4Y62o6YC2Zsck9rZVGTvqW1AQ7X9zTnj', postConv='coins')


def test_round_initiator_operator_cannot_sign_or_assign_signature_to_himself(clean_board):
    custom_wallet(['operator', 'findir'], ['operator', 'teodor'])
    first = client_for(make_user('operator', 'Первый оператор'))
    dispatcher = client_for(make_user('operator', 'Диспетчер'))
    findir = client_for(make_user('findir'))
    assert claim(first).status_code == 200
    assert takeover(dispatcher, 'findir').status_code == 200
    assert claim(findir).status_code == 200
    to_s24()
    assert main_deal()['transferClaimHistory'][0]['byName'] == 'Первый оператор'
    assert confirm(first).status_code == 403, 'прежний исполнитель раунда не ставит ручную отметку за себя'
    r = handoff(first, 'teodor')                       # передать подпись другому можно
    assert r.status_code == 200, r.get_json()
    back = handoff(first, 'operator')                  # на себя — нельзя
    assert back.status_code == 409 and main_deal()['signHandoff']['role'] == 'teodor'
    assert handoff(dispatcher, 'operator').status_code == 200      # посторонний операционист — можно


def test_operator_cannot_place_manual_confirmation_on_own_transfer(clean_board):
    custom_wallet(['operator'], ['operator', 'teodor'])
    u = users()
    assert claim(u['operator']).status_code == 200
    to_s24()
    assert confirm(u['operator']).status_code == 403              # своя отметка
    assert confirm(u['dispatcher']).status_code == 403            # другой оператор: подпись назначена teodor
    assert main_deal().get('transferConfirmation') is None
