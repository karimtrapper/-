"""QA пункта 4: s23 доступен всем ролям-инициаторам, «Беру» забирает ровно один.

Акторы — настоящие AdminUser из БД; роль из сессии/тела запроса ничего не решает.
"""
import copy
import threading

import pytest
import requests

import app as m
from tests.qa_wallet_roles_helpers import (
    checked_put,
    make_user, client_for, put_board, board, snapshot_board, restore_board,
    send_deal, serve, cookie_for)
from tests.test_wallet_roles_qa import REALTY, EXCHANGE, LEGACY, seeded, stand  # noqa: F401

DEST = 'TQgQCBXkewuW4RoieDKFP9Ko2SopBh8jso'


@pytest.fixture
def clean_board(seeded):
    saved = snapshot_board()
    yield
    restore_board(saved)


def board_with(wallet, amount=5000, deal_id=9001, **extra):
    deal, mirror = send_deal(deal_id, wallet, DEST, amount, **extra)
    state = {'deals': [deal], 'convs': [], 'incomes': [], 'notes': [], 'wallets': [mirror]}
    put_board(state, version=5)
    return state


def claim(client, deal_id=9001, version=None, **body):
    version = board()[1] if version is None else version
    return client.post('/api/stand/transfer/claim',
                       json={'dealId': deal_id, 'version': version, **body})


def stored_claim(deal_id=9001):
    deal = next(d for d in board()[0]['deals'] if d['id'] == deal_id)
    return deal.get('transferClaim')


# -------------------------------------------------------------- роли

@pytest.mark.parametrize('role', ['operator', 'findir', 'teodor'])
def test_realty_wallet_every_initiator_role_can_claim(clean_board, role):
    board_with(REALTY)
    uid = make_user(role)
    r = claim(client_for(uid))
    assert r.status_code == 200, r.get_json()
    saved = stored_claim()
    assert saved['byId'] == uid and saved['role'] == role
    assert saved['walletId'] == registry_wallet_id(REALTY)
    assert r.get_json()['claim'] == saved


@pytest.mark.parametrize('role', ['manager', 'admin', 'buyer', 'findir_x'])
def test_realty_wallet_other_roles_cannot_claim(clean_board, role):
    state = board_with(REALTY)
    before = board()
    r = claim(client_for(make_user(role)))
    assert r.status_code == 403, r.get_json()
    assert board() == before


def test_exchange_wallet_only_operator_initiates(clean_board):
    board_with(EXCHANGE, amount=5000)
    before = board()
    for role in ('findir', 'teodor', 'manager', 'admin'):
        r = claim(client_for(make_user(role)))
        assert r.status_code == 403, (role, r.get_json())
    assert board() == before
    uid = make_user('operator')
    assert claim(client_for(uid)).status_code == 200
    assert stored_claim()['byId'] == uid


def test_unauthenticated_and_disabled_users_cannot_claim(clean_board):
    board_with(REALTY)
    anon = m.app.test_client()
    assert claim(anon).status_code in (401, 403)
    uid = make_user('operator')
    db = m.get_session()
    try:
        db.query(m.AdminUser).filter_by(id=uid).one().login_disabled = True
        db.commit()
    finally:
        db.close()
    assert claim(client_for(uid)).status_code in (401, 403)
    assert stored_claim() is None


# ---------------------------------------------- личность берётся только из сессии

def test_claim_identity_ignores_body_and_session_role(clean_board):
    board_with(REALTY)
    uid = make_user('operator')
    other = make_user('findir', 'Чужой финдир')
    client = client_for(uid)
    with client.session_transaction() as sess:
        sess['role'] = 'teodor'          # подмена роли в cookie
        sess['display_name'] = 'Взломщик'
    r = claim(client, byId=other, byName='Чужой финдир', role='findir',
              actorId=other, userId=other, claimedBy=other)
    assert r.status_code == 200, r.get_json()
    saved = stored_claim()
    assert saved['byId'] == uid and saved['role'] == 'operator'
    assert saved['byName'] != 'Чужой финдир' and saved['byName'] != 'Взломщик'


def test_spoofed_session_role_does_not_grant_access(clean_board):
    board_with(REALTY)
    manager = client_for(make_user('manager'))
    with manager.session_transaction() as sess:
        sess['role'] = 'operator'
    assert claim(manager, role='operator').status_code == 403
    assert stored_claim() is None


def test_role_change_in_db_applies_immediately(clean_board):
    board_with(REALTY)
    uid = make_user('operator')
    client = client_for(uid)
    db = m.get_session()
    try:
        db.query(m.AdminUser).filter_by(id=uid).one().role = 'manager'
        db.commit()
    finally:
        db.close()
    assert claim(client).status_code == 403
    assert stored_claim() is None


# ----------------------------------------------------------- один победитель

def test_second_claimer_gets_named_conflict_not_overwrite(clean_board):
    board_with(REALTY)
    a, b = make_user('operator', 'Настя А'), make_user('findir', 'Виталий Б')
    first = claim(client_for(a))
    assert first.status_code == 200
    stale_version = board()[1] - 1
    for version in (stale_version, board()[1]):       # даже со старой версией проигравший назван
        r = claim(client_for(b), version=version)
        assert r.status_code == 409, r.get_json()
        body = r.get_json()
        assert body['success'] is False and body['taken_by'] == 'Настя А'
        assert 'Настя А' in body['error']
    assert stored_claim()['byId'] == a
    again = claim(client_for(a))      # повтор победителя безопасен
    assert again.status_code == 200 and stored_claim()['byId'] == a


@pytest.mark.parametrize('contenders', [2, 6])
def test_parallel_claims_exactly_one_winner(clean_board, contenders):
    board_with(REALTY)
    roles = (['operator', 'findir', 'teodor'] * 2)[:contenders]
    users = [(make_user(role, f'Игрок {i}'), role) for i, role in enumerate(roles)]
    version = board()[1]
    server, thread, base = serve()
    results, barrier = [None] * contenders, threading.Barrier(contenders)

    def go(i):
        barrier.wait()
        results[i] = requests.post(base + '/api/stand/transfer/claim',
                                   json={'dealId': 9001, 'version': version},
                                   headers=cookie_for(users[i][0]), timeout=15)
    try:
        threads = [threading.Thread(target=go, args=(i,)) for i in range(contenders)]
        [t.start() for t in threads]
        [t.join(20) for t in threads]
    finally:
        server.shutdown(); thread.join(5); server.server_close()
    codes = [r.status_code for r in results]
    assert codes.count(200) == 1, [(r.status_code, r.text[:200]) for r in results]
    assert all(c == 409 for c in codes if c != 200), codes      # ни одной 500
    winner = users[codes.index(200)][0]
    state, new_version = board()
    assert stored_claim()['byId'] == winner
    assert new_version == version + 1, 'победитель — единственная запись на доску'
    deal = state['deals'][0]
    assert sum('взял отправку' in e.get('text', '') for e in deal['log']) == 1
    winner_name = stored_claim()['byName']
    for r in results:
        if r.status_code == 409:
            assert r.json()['taken_by'] == winner_name and winner_name in r.json()['error']


# ------------------------------------------------- старый путь и состояние шага

def test_legacy_wallet_has_no_new_claim_gate(clean_board):
    state = board_with(LEGACY)
    before = board()
    r = claim(client_for(make_user('operator')))
    assert r.status_code == 409
    assert board() == before


def test_claim_requires_s23_and_known_deal(clean_board):
    board_with(REALTY, step='s22')
    c = client_for(make_user('operator'))
    before = board()
    assert claim(c).status_code == 409
    assert claim(c, deal_id=424242).status_code in (404, 409)
    assert board() == before


def test_stale_version_without_claim_is_refused_without_change(clean_board):
    board_with(REALTY)
    before = board()
    r = claim(client_for(make_user('operator')), version=before[1] - 1)
    assert r.status_code == 409 and stored_claim() is None
    assert board() == before


# ------------------------------------------------------------- лимит обменника

@pytest.mark.parametrize('amount, ok', [(5000, True), (10000, True), (10000.01, False), (15000, False)])
def test_exchange_claim_limit_is_inclusive_and_needs_owner_approval(clean_board, amount, ok):
    board_with(EXCHANGE, amount=amount)
    r = claim(client_for(make_user('operator')))
    assert (r.status_code == 200) == ok, r.get_json()
    if not ok:
        assert r.status_code == 400 and 'свыше 10 000' in r.get_json()['error']
        assert stored_claim() is None


# ------------------------------------------ подделка через общий PUT состояния

def put_state(client, mutate, witness=None):
    snap = client.get('/api/stand/state').get_json()
    data = copy.deepcopy(snap['data'])
    mutate(next(d for d in data['deals'] if d['id'] == 9001), data)
    return checked_put(client, snap['version'], data, witness=witness)


def test_state_put_cannot_forge_remove_or_edit_claim(clean_board):
    board_with(REALTY)
    victim = client_for(make_user('operator', 'Победитель'))
    attacker = client_for(make_user('findir'))
    forged = {'byId': 1, 'byName': 'Я', 'role': 'teodor', 'at': 1, 'walletId': 1, 'amount': '1',
              'fingerprint': 'x'}
    put_state(attacker, lambda d, s: d.update(transferClaim=forged), witness='фиксирует только сервер')
    assert stored_claim() is None, 'клейм нельзя создать общим сохранением доски'
    assert claim(victim).status_code == 200
    real = stored_claim()
    for mutate in (lambda d, s: d.pop('transferClaim'),
                   lambda d, s: d.update(transferClaim=None),
                   lambda d, s: d['transferClaim'].update(byId=1, byName='Я'),
                   lambda d, s: d['transferClaim'].update(fingerprint='x')):
        put_state(attacker, mutate, witness='фиксирует только сервер')
        assert stored_claim() == real


def test_state_put_cannot_flip_wallet_or_amount_after_claim(clean_board):
    board_with(REALTY, amount=5000)
    assert claim(client_for(make_user('operator'))).status_code == 200
    attacker = client_for(make_user('findir'))
    for mutate in (lambda d, s: d.update(walletId='custom', payinCustom={
                       'network': 'TRC-20', 'addr': DEST, 'multisig': False}),
                   lambda d, s: d.update(walletId='grusha'),
                   lambda d, s: d['transfer'].update(amount=1),
                   lambda d, s: d['transfer'].update(addr='T' + 'Z' * 33)):
        put_state(attacker, mutate)
        deal = board()[0]['deals'][0]
        assert deal['walletId'] == registry_wallet_id(REALTY)
        assert deal['transfer']['amount'] == 5000 and deal['transfer']['addr'] == DEST


def registry_wallet_id(address):
    from tests.qa_wallet_roles_helpers import registry_id
    return registry_id(address)


def test_non_eligible_user_cannot_set_claim_on_fresh_board(clean_board):
    board_with(REALTY)
    manager = client_for(make_user('manager'))
    put_state(manager, lambda d, s: d.update(transferClaim={
        'byId': 7, 'byName': 'x', 'role': 'operator', 'at': 1, 'walletId': 1, 'amount': '5000',
        'fingerprint': 'f'}))
    assert stored_claim() is None


# ----------------------------------------------------------------- пачка

def test_batch_claim_binds_canonical_main_and_summed_amount(clean_board):
    wid = registry_wallet_id(REALTY)
    main, mirror = send_deal(9001, REALTY, DEST, 6000, cnvId=1, conv=[9002])
    side, _ = send_deal(9002, REALTY, DEST, 4000, cnvId=1, conv=[])
    state = {'deals': [main, side], 'incomes': [], 'notes': [], 'wallets': [mirror],
             'convs': [{'id': 1, 'walletId': wid, 'status': 'received',
                        'sources': [{'dealId': 9001}, {'dealId': 9002}]}]}
    put_board(state, version=5)
    a, b = make_user('operator', 'Первая'), make_user('findir', 'Второй')
    r = claim(client_for(a), deal_id=9002)          # через побочную сделку
    assert r.status_code == 200, r.get_json()
    saved = stored_claim(9001)
    assert saved and saved['byId'] == a and saved['amount'] in ('10000', '10000.0', '10000.00')
    assert stored_claim(9002) is None, 'клейм живёт на канонической основной сделке'
    r = claim(client_for(b), deal_id=9001)
    assert r.status_code == 409 and r.get_json()['taken_by'] == 'Первая'


def batch(main_wallet_id, conv_wallet_id, side_wallet_id):
    main, mirror = send_deal(9001, REALTY, DEST, 6000, cnvId=1, conv=[9002])
    side, _ = send_deal(9002, REALTY, DEST, 4000, cnvId=1, conv=[])
    main['walletId'], side['walletId'] = main_wallet_id, side_wallet_id
    put_board({'deals': [main, side], 'incomes': [], 'notes': [], 'wallets': [mirror],
               'convs': [{'id': 1, 'walletId': conv_wallet_id, 'status': 'received',
                          'sources': [{'dealId': 9001}, {'dealId': 9002}]}]}, version=5)


def test_batch_wallet_is_the_conversion_wallet_not_a_side_deal_field(clean_board):
    """Кошелёк отправки пачки = кошелёк пачки (conv.walletId); поле побочной сделки его не меняет."""
    wid = registry_wallet_id(REALTY)
    batch(wid, wid, 'grusha')
    r = claim(client_for(make_user('operator')))
    assert r.status_code == 200, r.get_json()
    assert stored_claim()['walletId'] == wid


def test_batch_conversion_wallet_legacy_keeps_old_path_even_if_deal_field_is_policy(clean_board):
    """Деньги уходят с кошелька пачки: если он легаси, политика не включается из поля сделки."""
    wid = registry_wallet_id(REALTY)
    batch(wid, 'grusha', wid)
    before = board()
    r = claim(client_for(make_user('operator')))
    assert r.status_code == 409 and board() == before


# --------------------- обход политики через walletId=custom с адресом политики

def custom_board(address, amount, wallet_id='custom', **extra):
    deal, mirror = send_deal(9001, REALTY, DEST, amount)
    deal.update(walletId=wallet_id, **extra)
    deal['payinCustom'] = {'network': 'TRC-20', 'addr': address, 'multisig': True,
                           'owner': 'компания'}
    state = {'deals': [deal], 'convs': [], 'incomes': [], 'notes': [], 'wallets': []}
    put_board(state, version=5)


@pytest.mark.parametrize('address', [REALTY, EXCHANGE])
def test_custom_wallet_with_policy_address_is_not_a_policy_bypass(clean_board, address):
    """Адрес политики, введённый вручную как custom, нельзя использовать в обход ролей и лимита:
    сервер либо применяет ту же политику, либо закрыто отказывает — клейма нет ни у кого."""
    custom_board(address, 15000 if address == EXCHANGE else 5000)
    before = board()
    for role in ('manager', 'operator', 'findir', 'teodor'):
        r = claim(client_for(make_user(role)))
        assert r.status_code in (400, 403, 409), (role, r.get_json())
        assert r.get_json()['success'] is False
        assert 'прежний порядок' not in r.get_json()['error'], 'custom ушёл на легаси-путь'
    assert stored_claim() is None and board() == before


def test_old_wallet_switched_to_custom_before_claim_keeps_policy(clean_board):
    board_with(LEGACY)       # легаси-кошелёк, прежний порядок
    attacker = client_for(make_user('operator'))
    # пытаемся перевести сделку на custom с адресом обменника и суммой > лимита
    put_state(attacker, lambda d, s: (d.update(walletId='custom', payinCustom={
        'network': 'TRC-20', 'addr': EXCHANGE, 'multisig': True, 'owner': 'компания'}),
        d['transfer'].update(amount=15000)))
    deal = board()[0]['deals'][0]
    if deal['walletId'] == 'custom':        # если сохранение прошло — политика обязана сработать
        r = claim(attacker)
        assert r.status_code in (400, 403), r.get_json()
        assert stored_claim() is None


def test_prepay_wallet_with_policy_address_is_governed(clean_board):
    """Оплата наперёд задаёт кошелёк в prepay.wallet — политика та же."""
    deal, mirror = send_deal(9001, EXCHANGE, DEST, 15000)
    deal['prepay'] = {'source': 'company', 'wallet': dict(mirror, id=mirror['id']),
                      'amount': 15000, 'brokerStep': 'done'}
    put_board({'deals': [deal], 'convs': [], 'incomes': [], 'notes': [], 'wallets': [mirror]}, 5)
    over = claim(client_for(make_user('operator')))
    assert over.status_code == 400 and 'свыше 10 000' in over.get_json()['error']
    assert claim(client_for(make_user('findir'))).status_code == 403


@pytest.mark.parametrize('amount', [None, '', 'NaN', 'inf', '-inf', -5, 0, 'abc'])
def test_invalid_amounts_fail_closed_on_exchange_claim(clean_board, amount):
    board_with(EXCHANGE, amount=amount)
    before = board()
    r = claim(client_for(make_user('operator')))
    assert r.status_code in (400, 409), r.get_json()
    assert stored_claim() is None and board() == before


def test_state_put_cannot_swap_batch_wallet_after_claim(clean_board):
    wid = registry_wallet_id(REALTY)
    batch(wid, wid, wid)
    assert claim(client_for(make_user('operator'))).status_code == 200
    attacker = client_for(make_user('findir'))
    snap = attacker.get('/api/stand/state').get_json()
    snap['data']['convs'][0]['walletId'] = 'grusha'
    checked_put(attacker, snap['version'], snap['data'])
    state = board()[0]
    assert state['convs'][0]['walletId'] == wid
    assert stored_claim()['walletId'] == wid


# ----------- удаление/пересоздание сделки с тем же id не сбрасывает подписи

def test_state_put_cannot_delete_or_reinsert_claimed_deal(clean_board):
    board_with(REALTY)
    assert claim(client_for(make_user('operator'))).status_code == 200
    real = stored_claim()
    attacker = client_for(make_user('findir'))
    snap = attacker.get('/api/stand/state').get_json()
    # 1) удалить сделку
    gone = copy.deepcopy(snap['data'])
    gone['deals'] = []
    r = checked_put(attacker, snap['version'], gone)
    assert r.status_code in (400, 403, 409)
    assert stored_claim() == real
    # 2) заменить сделкой с другим id без подписи (старая исчезает)
    swap = copy.deepcopy(snap['data'])
    clone = copy.deepcopy(swap['deals'][0])
    clone['id'] = 9999
    clone.pop('transferClaim')
    swap['deals'] = [clone]
    r = checked_put(attacker, snap['version'], swap)
    assert stored_claim() == real
    assert {d['id'] for d in board()[0]['deals']} == {9001}
    # 3) удалить и вернуть тот же id в одном сохранении нельзя: в новом состоянии claim сверяется с прежним
    again = copy.deepcopy(snap['data'])
    again['deals'][0].pop('transferClaim', None)
    checked_put(attacker, snap['version'], again)
    assert stored_claim() == real
