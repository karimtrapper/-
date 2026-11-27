"""Исправления по независимому ревью: общая проверка перевода для закрытия раунда политики,
custom-кошелёк и кошельки админа, серверные поля отправки (markedBy/signers), удаление и отключение кошелька.

Сеть — только моки (см. test_wallet_handoff_tracking.py).
"""
import copy
import json
import time

import pytest

import app as m
from tests.qa_wallet_roles_helpers import (
    checked_put, make_user, client_for, put_board, board, send_deal, registry_id)
from tests.test_wallet_roles_qa import seeded, stand, wallet_row  # noqa: F401
from tests.test_wallet_handoff_tracking import (  # noqa: F401
    chain, Chain, transfer, ref, roles, exchange_claimed, settle, mark, main_deal, api, claim_now,
    EXCHANGE, REALTY, DEST, DEST2, OTHER, DEAL, closure_notes, sent)

NEW_ADDR = 'TA4Y62o6YC2Zsck9rZVGTvqW1AQ7X9zTnj'


def put_sends(client, sends):
    """Держатель claim записывает хеши обычным общим PUT состояния."""
    snap = client.get('/api/stand/state').get_json()
    data = copy.deepcopy(snap['data'])
    next(d for d in data['deals'] if d['id'] == DEAL)['transfer']['sends'] = sends
    return checked_put(client, snap['version'], data)


def pending(n, amount=5000, **extra):
    return dict({'ref': ref(n), 'hash': ref(n), 'amount': amount, 'net': 'TRC-20', 'status': 'pending'}, **extra)


# ============================ 1. одна проверка «перевод годится для закрытия раунда» на всех путях

def test_holder_cannot_close_the_step_with_an_old_hash(chain):
    u, at = exchange_claimed(chain)
    chain.rows.append(transfer(1, 5000, sender=EXCHANGE, ts=at - 3600_000))     # тот же кошелёк, получатель и сумма, но час назад
    assert put_sends(u['operator'], [pending(1)]).status_code == 200
    settle()
    deal = main_deal()
    assert deal['step'] == 's23' and not deal.get('serverTransferComplete'), 'старый перевод не закрывает шаг'
    send = deal['transfer']['sends'][0]
    assert send['status'] != 'confirmed' and 'раньше начала отправки' in send['checkError'], 'причина видна в задаче'
    # новый перевод после claim по-прежнему закрывает
    chain.rows.append(transfer(2, 5000, sender=EXCHANGE, ts=at + 5000))
    assert put_sends(u['operator'], [pending(2)]).status_code == 200
    settle()
    assert main_deal()['step'] == 's25'


def test_holder_cannot_close_the_step_with_a_hash_used_elsewhere(chain, monkeypatch):
    u, at = exchange_claimed(chain)
    chain.rows.append(transfer(1, 5000, sender=EXCHANGE, ts=at + 5000))
    monkeypatch.setattr(m, 'get_used_transaction_hashes', lambda db: {ref(1)})     # хеш занят реестром CRM
    assert put_sends(u['operator'], [pending(1)]).status_code == 200
    settle()
    deal = main_deal()
    assert deal['step'] == 's23' and 'уже использован' in deal['transfer']['sends'][0]['checkError']


def test_holder_cannot_close_the_step_with_a_hash_of_another_deal(chain):
    u, at = exchange_claimed(chain)
    chain.rows.append(transfer(1, 5000, sender=EXCHANGE, ts=at + 5000))
    state, version = board()
    state['deals'].append({'id': 9500, 'step': 's27', 'code': 'СД-9500', 'log': [],
                           'transfer': {'addr': DEST2, 'amount': 5000, 'sends': [
                               {'ref': ref(1), 'hash': ref(1), 'amount': 5000, 'net': 'TRC-20', 'status': 'confirmed',
                                'from': EXCHANGE, 'to': DEST2, 'verifiedAmount': 5000}]}})
    put_board(state, version)
    assert put_sends(u['operator'], [pending(1)]).status_code == 200
    settle()
    deal = main_deal()
    assert deal['step'] == 's23'
    assert any(t in deal['transfer']['sends'][0]['checkError'] for t in ('уже использован', 'уже указан в другой'))


def test_one_shared_check_guards_poller_holder_and_marking(chain, monkeypatch):
    """Три пути закрытия берут решение у одной функции: если она отказывает, не закрывает ни один."""
    seen = []

    def refuse(*args, **kwargs):
        seen.append(args)
        return 'тест: отказ общей проверки'
    u, at = exchange_claimed(chain)
    chain.rows.append(transfer(1, 5000, sender=EXCHANGE, ts=at + 5000))
    monkeypatch.setattr(m, '_stand_policy_send_problem', refuse)
    # поллер: хеш не привязывается
    m._stand_track_policy_outgoing(DEAL)
    assert main_deal()['transfer']['sends'] == [] and 'transferFound' not in main_deal()
    # «Деньги отправлены»
    r = mark(u['dispatcher'], ref(1))
    assert r.status_code == 409 and 'тест: отказ общей проверки' in r.get_json()['error']
    # «Я отправил» держателя claim
    assert put_sends(u['operator'], [pending(1)]).status_code == 200
    settle()
    deal = main_deal()
    assert deal['step'] == 's23' and 'тест: отказ общей проверки' in deal['transfer']['sends'][0]['checkError']
    assert len(seen) >= 3


# ===================== 2. custom-кошелёк не обходит политику кошелька, созданного админом

def admin_wallet():
    r = client_for(make_user('admin')).post('/api/wallets', json={
        'address': NEW_ADDR, 'blockchain': 'TRON', 'owner': 'Тест', 'accepts_payin': True,
        'initiator_roles': ['operator'], 'confirmer_roles': ['teodor'], 'owner_can_alone': True})
    assert r.status_code == 200, r.get_json()


def test_custom_source_cannot_bypass_admin_created_wallet_policy(seeded):
    admin_wallet()
    deal, mirror = send_deal(DEAL, REALTY, DEST, 1000)
    deal['walletId'] = 'custom'
    deal['payinCustom'] = {'network': 'TRC-20', 'addr': NEW_ADDR, 'owner': 'компания', 'multisig': False}
    state = {'deals': [deal], 'convs': [], 'incomes': [], 'notes': [], 'wallets': [mirror]}
    db = m.get_session()
    try:
        with pytest.raises(ValueError):
            m._stand_transfer_policy(db, state, deal)
        deal['payinCustom']['addr'] = 'TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn'      # обычный свой адрес — прежний путь
        assert m._stand_transfer_policy(db, state, deal) is None
    finally:
        db.close()


def test_state_put_refuses_custom_payin_wallet_with_admin_policy_address(seeded):
    admin_wallet()
    base = {'id': 9001, 'code': 'СД-9001', 'type': 'Оплата недвижимости', 'kind': 'Лизхолд', 'payType': 'Крипта',
            'step': 's11', 'walletId': 'grusha', 'log': [], 'transfer': {}}
    forged = dict(base, walletId='custom', payinCustom={'network': 'TRC-20', 'addr': NEW_ADDR, 'owner': 'компания',
                                                          'multisig': False})
    db = m.get_session()
    try:
        problem = m._stand_guard_transition({'deals': [base]}, {'deals': [forged]}, 'operator',
                                            make_user('operator'), db)
    finally:
        db.close()
    assert problem == 'Кошелёк с политикой подписей выбирают из реестра'


def test_policy_lookup_by_address_covers_registry_wallets_with_ready_policy(seeded):
    admin_wallet()
    db = m.get_session()
    try:
        assert NEW_ADDR in m._stand_policy_addresses(db)
        assert REALTY in m._stand_policy_addresses(db)
        assert 'TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn' not in m._stand_policy_addresses(db)
    finally:
        db.close()


# ============================== 3. markedBy и signers — серверные поля отправки

def test_forged_marked_by_and_signers_through_state_put_are_dropped(chain, sent):
    u, at = exchange_claimed(chain)
    chain.rows.append(transfer(1, 5000, sender=EXCHANGE, ts=at + 5000))
    forged = pending(1, markedBy={'kind': 'operator', 'byName': 'Хакер', 'forName': 'кого угодно'},
                     signers=[m.POLICY_SIGNER_ADDRESSES['operator'], m.POLICY_SIGNER_ADDRESSES['teodor']])
    assert put_sends(u['operator'], [forged]).status_code == 200
    send = main_deal()['transfer']['sends'][0]
    assert 'markedBy' not in send and 'signers' not in send, 'при записи через общий PUT серверные поля отбрасываются'
    m._stand_track_policy_outgoing(DEAL)
    assert main_deal()['transferFound']['hashes'] == [ref(1)], 'transferFound выставляется как обычно'
    settle()
    log = [e['text'] for e in main_deal()['log']]
    assert 'Подписано в сети' in log and not any('Хакер' in t for t in log)
    assert not any('Подписали в сети' in t for t in log)
    note = closure_notes()[0]['text']
    assert 'Хакер' not in note and 'подписано в сети' in note and 'Отметил: Имя operator' in note


def test_forged_signers_on_an_attached_send_cannot_be_replaced_later(chain):
    u, at = exchange_claimed(chain)
    chain.signers = [m.POLICY_SIGNER_ADDRESSES['teodor'], m.POLICY_SIGNER_ADDRESSES['findir']]
    chain.rows.append(transfer(1, 5000, sender=EXCHANGE, ts=at + 5000))
    m._stand_track_policy_outgoing(DEAL)
    trusted = copy.deepcopy(main_deal()['transfer']['sends'][0])
    assert trusted['markedBy'] == {'kind': 'poller'}
    tampered = dict(trusted, markedBy={'kind': 'operator', 'byName': 'Хакер'}, signers=[m.POLICY_SIGNER_ADDRESSES['operator']])
    put_sends(u['operator'], [tampered])
    send = main_deal()['transfer']['sends'][0]
    assert send['markedBy'] == {'kind': 'poller'} and send['signers'] == trusted['signers']


# ===================== 4. удаление и отключение кошелька с готовой политикой

def policy_log(address):
    s = m.get_session()
    try:
        return json.loads(s.query(m.Wallet).filter_by(address=address).one().policy_log or '[]')
    finally:
        s.close()


def board_on_wallet(address, step='s23'):
    deal, mirror = send_deal(DEAL, address, DEST, 1000)
    deal['step'] = step
    deal['code'] = 'СД-9001'
    put_board({'deals': [deal], 'convs': [], 'incomes': [], 'notes': [], 'wallets': [mirror]}, 5)


def wid():
    return wallet_row(NEW_ADDR)['id']


@pytest.mark.parametrize('role', ['operator', 'findir', 'manager', 'teodor'])
def test_only_admin_deletes_or_deactivates_wallet_with_ready_policy(seeded, role):
    admin_wallet()
    client = client_for(make_user(role))
    assert client.delete(f'/api/wallets/{wid()}').status_code == 403
    assert client.patch(f'/api/wallets/{wid()}', json={'active': False}).status_code == 403
    assert wallet_row(NEW_ADDR)['active'] is True
    admin = client_for(make_user('admin'))
    assert admin.patch(f'/api/wallets/{wid()}', json={'active': False}).status_code == 200
    assert wallet_row(NEW_ADDR)['active'] is False
    assert admin.delete(f'/api/wallets/{wid()}').status_code == 200
    assert wallet_row(NEW_ADDR) is None


def test_active_change_of_policy_wallet_is_logged(seeded):
    admin_wallet()
    admin = client_for(make_user('admin'))
    assert admin.patch(f'/api/wallets/{wid()}', json={'active': False}).status_code == 200
    assert admin.patch(f'/api/wallets/{wid()}', json={'active': False}).status_code == 200      # без изменения — без записи
    assert admin.patch(f'/api/wallets/{wid()}', json={'active': True}).status_code == 200
    log = policy_log(NEW_ADDR)
    changes = [(e['before'].get('active'), e['after'].get('active')) for e in log if 'active' in e['after']]
    assert changes == [(True, False), (False, True)]
    assert all(e['by_id'] and e['by_name'] for e in log)


def test_busy_wallet_cannot_be_deleted_or_deactivated_by_anyone(seeded):
    admin_wallet()
    for step in ('s23', 's24'):
        board_on_wallet(NEW_ADDR, step)
        admin = client_for(make_user('admin'))
        for r in (admin.delete(f'/api/wallets/{wid()}'), admin.patch(f'/api/wallets/{wid()}', json={'active': False})):
            assert r.status_code == 409, (step, r.get_json())
            assert 'СД-9001' in r.get_json()['error'], 'в отказе номер сделки'
        assert wallet_row(NEW_ADDR)['active'] is True
    board_on_wallet(NEW_ADDR, 's27')                                    # сделка ушла дальше — можно
    assert client_for(make_user('admin')).patch(f'/api/wallets/{wid()}', json={'active': False}).status_code == 200


def test_other_wallets_keep_their_delete_and_patch_behavior(seeded):
    operator = client_for(make_user('operator'))
    r = operator.post('/api/wallets', json={'address': NEW_ADDR, 'blockchain': 'TRON', 'owner': 'Тест', 'accepts_payin': True})
    assert r.status_code == 200 and wallet_row(NEW_ADDR)['initiator_roles'] == []          # политики нет
    assert operator.patch(f'/api/wallets/{wid()}', json={'active': False}).status_code == 200
    assert wallet_row(NEW_ADDR)['active'] is False
    assert operator.delete(f'/api/wallets/{wid()}').status_code == 200
    assert wallet_row(NEW_ADDR) is None
