"""Поиск исходящих переводов с кошелька политики после claim: автопривязка хеша, тревога «два перевода».

Сеть — только моки: `stand_egress.read_get` (список переводов TronScan) и `verify_transfer`
(доказательство по хешу), как в test_stand_outgoing_review.py.
"""
import threading
import time
from decimal import Decimal

import requests

import pytest

import app as m
import stand_egress
from stand_transfer_discovery import USDT_TRC20
from tests.qa_wallet_roles_helpers import (
    make_user, client_for, put_board, board, snapshot_board, restore_board, send_deal, registry_id,
    serve, cookie_for)
from tests.test_wallet_roles_qa import seeded, stand  # noqa: F401

REALTY = 'TDuDeRiwrLLN3hnnA57G5yM6ibg58A6wZk'
EXCHANGE = 'TA6S3RBEY57jq8fXEVVsU6H9JZ18inenG4'
DEST = 'TQgQCBXkewuW4RoieDKFP9Ko2SopBh8jso'
DEST2 = 'TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn'
OTHER = 'TA4Y62o6YC2Zsck9rZVGTvqW1AQ7X9zTnj'
DEAL = 9001


def transfer(n, amount, *, to=DEST, sender=REALTY, ts):
    return dict(transaction_id=f'{n:064x}', quant=str(int(Decimal(str(amount)) * 1000000)),
                block_ts=ts, from_address=sender, to_address=to,
                contract_address=USDT_TRC20, confirmed=True, finalResult='SUCCESS',
                event_type='Transfer', contractRet='SUCCESS', status=0)


def ref(n):
    return f'{n:064x}'


class Chain:
    def __init__(self):
        self.rows = []
        self.broken = False
        self.verified = True
        self.calls = 0
        self.signers = None

    def read(self, op, params):
        self.calls += 1
        if self.broken:
            return None, None, 'сеть недоступна'
        assert op == 'tron_trc20_transfers'
        rows = sorted(self.rows, key=lambda t: -t['block_ts'])
        return 200, {'token_transfers': rows, 'total': len(rows)}, None

    def verify(self, tx_ref, net, sender, recipient, amount, **kw):
        row = next((t for t in self.rows if t['transaction_id'] == tx_ref and t['from_address'] == sender
                    and t['to_address'] == recipient), None)
        if not row:
            return {'status': 'mismatch', 'checkError': 'адрес не совпал'}
        if not self.verified:
            return {'status': 'pending'}
        actual = Decimal(row['quant']) / 1000000
        if amount is not None and abs(actual - Decimal(str(amount))) > Decimal('0.01'):
            return {'status': 'mismatch', 'checkError': 'Токен, адреса или сумма не совпали'}
        proof = {'status': 'confirmed', 'verifiedAmount': float(Decimal(row['quant']) / 1000000),
                 'timestampMs': row['block_ts'], 'from': sender, 'to': recipient}
        if self.signers is not None:
            proof['signers'] = list(self.signers)
        return proof


@pytest.fixture
def chain(seeded, monkeypatch):
    c = Chain()
    monkeypatch.setattr(stand_egress, 'read_get', c.read)
    monkeypatch.setattr(m, 'verify_transfer', c.verify)
    saved = snapshot_board()
    yield c
    restore_board(saved)


def board_with(wallet=REALTY, amount=5000, **extra):
    deal, mirror = send_deal(DEAL, wallet, DEST, amount, **extra)
    deal['code'] = 'СД-9001'
    deal['client'] = 'Клиент Тест'
    put_board({'deals': [deal], 'convs': [], 'incomes': [], 'notes': [], 'wallets': [mirror]}, version=5)


def main_deal(deal_id=DEAL):
    return next(d for d in board()[0]['deals'] if d['id'] == deal_id)


def api(client, path, **body):
    return client.post('/api/stand/transfer/' + path, json={'dealId': DEAL, 'version': board()[1], **body})


def roles():
    out = {r: client_for(make_user(r, f'Имя {r}')) for r in ('operator', 'findir', 'teodor', 'manager', 'admin')}
    out['dispatcher'] = client_for(make_user('operator', 'Диспетчер'))
    return out


def claim_now(u, role='operator'):
    assert api(u[role], 'claim').status_code == 200
    return main_deal()['transferClaim']['at']


def notes_for(text_part):
    return sorted(n['role'] for n in board()[0].get('notes') or [] if text_part in n['text'])


# ---------------------------------------------------------------- один перевод

def test_single_transfer_after_claim_is_bound_like_initiator_hash(chain):
    board_with()
    u = roles()
    at = claim_now(u)
    chain.rows.append(transfer(1, 5000, ts=at + 5000))
    m._stand_track_policy_outgoing(DEAL)
    deal = main_deal()
    assert [s['hash'] for s in deal['transfer']['sends']] == [ref(1)]
    send = deal['transfer']['sends'][0]
    assert send['amount'] == 5000.0 and send['net'] == 'TRC-20' and send['status'] == 'confirmed'
    assert deal['transferFound']['hashes'] == [ref(1)]
    assert [e['text'] for e in deal['log'] if 'найден в сети' in e['text']] == [f'Перевод найден в сети: {ref(1)}']
    assert notes_for('перевод найден в сети') == [], 'уведомление одно — о закрытии отправки (см. closure-тесты)'
    # кнопки гаснут: сервер отклоняет claim/передачу/перехват
    state_before = board()
    assert api(u['dispatcher'], 'handoff', toRole='findir').status_code == 409
    assert api(u['dispatcher'], 'handoff', toRole='findir', takeover=True, claimAt=at).status_code == 409
    assert api(u['teodor'], 'claim').status_code == 409
    assert board() == state_before


def test_polling_is_idempotent(chain):
    board_with()
    u = roles()
    at = claim_now(u)
    chain.rows.append(transfer(1, 5000, ts=at + 5000))
    m._stand_track_policy_outgoing(DEAL)
    snapshot = board()
    calls = chain.calls
    m._stand_track_policy_outgoing(DEAL)
    m._stand_track_policy_outgoing()
    assert board() == snapshot, 'повторный опрос не меняет доску: ни версию, ни журнал, ни уведомления'
    assert chain.calls == calls, 'после находки сеть больше не опрашивается'


def test_transfer_before_earliest_claim_does_not_count(chain):
    board_with()
    u = roles()
    at = claim_now(u)
    chain.rows.append(transfer(1, 5000, ts=at - 60000))
    version = board()[1]
    m._stand_track_policy_outgoing(DEAL)
    assert board()[1] == version and main_deal()['transfer']['sends'] == []
    assert 'transferFound' not in main_deal()


@pytest.mark.parametrize('row', [
    dict(amount=4999.99, to=DEST), dict(amount=5000.01, to=DEST), dict(amount=5000, to=OTHER),
    dict(amount=5000, to=DEST, sender=OTHER),
], ids=['меньше', 'больше', 'другой получатель', 'другой отправитель'])
def test_only_exact_amount_to_order_address_from_wallet_matches(chain, row):
    board_with()
    u = roles()
    at = claim_now(u)
    chain.rows.append(transfer(1, row['amount'], to=row['to'], sender=row.get('sender', REALTY), ts=at + 5000))
    version = board()[1]
    m._stand_track_policy_outgoing(DEAL)
    assert board()[1] == version and main_deal()['transfer']['sends'] == []


def test_no_claim_no_tracking(chain):
    board_with()
    chain.rows.append(transfer(1, 5000, ts=int(time.time() * 1000) + 5000))
    version = board()[1]
    m._stand_track_policy_outgoing(DEAL)
    assert board()[1] == version and chain.calls == 0


def test_incomplete_scan_or_dead_channel_attaches_nothing(chain):
    board_with()
    u = roles()
    at = claim_now(u)
    chain.rows.append(transfer(1, 5000, ts=at + 5000))
    chain.broken = True
    version = board()[1]
    m._stand_track_policy_outgoing(DEAL)
    assert board()[1] == version and main_deal()['transfer']['sends'] == []


def test_hash_already_used_by_another_operation_is_skipped(chain):
    board_with()
    u = roles()
    at = claim_now(u)
    chain.rows.append(transfer(1, 5000, ts=at + 5000))
    state, version = board()
    state['deals'].append({'id': 9500, 'step': 's27', 'code': 'СД-9500', 'log': [],
                           'transfer': {'sends': [{'ref': ref(1), 'hash': ref(1), 'amount': 5000,
                                                   'net': 'TRC-20', 'status': 'confirmed'}]}})
    put_board(state, version)
    m._stand_track_policy_outgoing(DEAL)
    assert main_deal()['transfer']['sends'] == [] and 'transferFound' not in main_deal()


def test_hash_entered_by_initiator_is_recognised_without_duplicate(chain):
    board_with()
    u = roles()
    at = claim_now(u)
    chain.rows.append(transfer(1, 5000, ts=at + 5000))
    state, version = board()
    state['deals'][0]['transfer']['sends'] = [{'ref': ref(1), 'hash': ref(1), 'amount': 5000,
                                               'net': 'TRC-20', 'status': 'pending'}]
    put_board(state, version)
    m._stand_track_policy_outgoing(DEAL)
    deal = main_deal()
    assert len(deal['transfer']['sends']) == 1 and deal['transferFound']['hashes'] == [ref(1)]


def test_unconfirmed_proof_attaches_pending_send_for_normal_verification(chain):
    board_with()
    u = roles()
    at = claim_now(u)
    chain.verified = False
    chain.rows.append(transfer(1, 5000, ts=at + 5000))
    m._stand_track_policy_outgoing(DEAL)
    send = main_deal()['transfer']['sends'][0]
    assert send['hash'] == ref(1) and send['status'] == 'pending'


def test_tracking_never_replaces_the_signers_confirmation(chain):
    """Автопривязка — только хеш; подтверждение второго подписанта на s24 остаётся обязательным."""
    board_with(EXCHANGE)
    u = roles()
    at = claim_now(u)
    chain.rows.append(transfer(1, 5000, sender=EXCHANGE, ts=at + 5000))
    m._stand_track_policy_outgoing(DEAL)
    deal = main_deal()
    assert deal['step'] == 's23' and 'transferConfirmation' not in deal
    assert not deal.get('serverTransferComplete')


# ---------------------------------------------------------------- перехват и ранний claim

def test_transfer_of_former_executor_between_claims_is_found_and_claim_restored(chain):
    board_with()
    u = roles()
    at = claim_now(u)
    former = main_deal()['transferClaim']
    chain.rows.append(transfer(1, 5000, ts=at + 30000))                 # прежний исполнитель успел отправить
    assert api(u['dispatcher'], 'handoff', toRole='findir', takeover=True, claimAt=at).status_code == 200
    assert 'transferClaim' not in main_deal()
    m._stand_track_policy_outgoing(DEAL)
    deal = main_deal()
    assert deal['transfer']['sends'][0]['hash'] == ref(1) and deal['transferFound']
    # завершить шаг некому, если claim не вернуть: он возвращается тому, кто заводил
    assert deal['transferClaim']['byId'] == former['byId'] and deal['transferClaim']['at'] == former['at']
    assert deal.get('transferClaimHistory') == []
    assert deal['assigneeAdminId'] == former['byId']
    assert api(u['findir'], 'claim').status_code == 409


def test_earliest_claim_of_the_round_sets_the_search_window(chain):
    board_with()
    u = roles()
    first = claim_now(u)
    assert api(u['dispatcher'], 'handoff', toRole='findir', takeover=True, claimAt=first).status_code == 200
    assert api(u['findir'], 'claim').status_code == 200
    second = main_deal()['transferClaim']['at']
    assert second >= first
    chain.rows.append(transfer(1, 5000, ts=first + 1))                  # после первого claim, до второго
    m._stand_track_policy_outgoing(DEAL)
    assert main_deal()['transfer']['sends'][0]['hash'] == ref(1)


# ----------------------------------------------------------------- два перевода — тревога

def two_transfers(chain, at):
    chain.rows.extend([transfer(1, 5000, ts=at + 5000), transfer(2, 5000, ts=at + 9000)])


def test_two_matching_transfers_raise_alarm_without_binding(chain):
    board_with()
    u = roles()
    at = claim_now(u)
    two_transfers(chain, at)
    m._stand_track_policy_outgoing(DEAL)
    deal = main_deal()
    assert deal['transfer']['sends'] == [] and 'transferFound' not in deal
    assert deal['transferAlarm']['hashes'] == sorted([ref(1), ref(2)])
    assert any('Найдено два перевода' in e['text'] and ref(1) in e['text'] for e in deal['log'])
    assert notes_for('найдено два перевода') == ['operator', 'teodor'], 'тревога: операционисту и владельцу, не менеджеру'
    # отправка заблокирована
    assert api(u['dispatcher'], 'handoff', toRole='findir', takeover=True, claimAt=at).status_code == 409
    snapshot = board()
    m._stand_track_policy_outgoing(DEAL)
    assert board() == snapshot, 'повторный опрос не дублирует тревогу, журнал и уведомления'


def test_alarm_clear_then_no_repeat_but_new_transfer_raises_again(chain):
    board_with()
    u = roles()
    at = claim_now(u)
    two_transfers(chain, at)
    m._stand_track_policy_outgoing(DEAL)
    assert api(u['teodor'], 'alarm/clear').status_code == 200
    version = board()[1]
    m._stand_track_policy_outgoing(DEAL)
    assert board()[1] == version and 'transferAlarm' not in main_deal()
    chain.rows.append(transfer(3, 5000, ts=at + 20000))
    m._stand_track_policy_outgoing(DEAL)
    assert main_deal()['transferAlarm']['hashes'] == sorted([ref(1), ref(2), ref(3)])


def test_alarm_blocks_hash_entry_and_step_through_state_put(chain):
    board_with()
    u = roles()
    at = claim_now(u)
    two_transfers(chain, at)
    m._stand_track_policy_outgoing(DEAL)
    snap = u['operator'].get('/api/stand/state').get_json()
    data = snap['data']
    data['deals'][0]['transfer']['sends'] = [{'ref': ref(1), 'hash': ref(1), 'amount': 5000, 'net': 'TRC-20'}]
    r = u['operator'].put('/api/stand/state', json={'version': snap['version'], 'data': data})
    assert r.status_code == 409 and 'Найдено два перевода' in r.get_data(as_text=True)
    assert main_deal()['transfer']['sends'] == []


def identical_batch():
    wid = registry_id(REALTY)
    main, mirror = send_deal(DEAL, REALTY, DEST, 3000, cnvId=1, conv=[9002])
    side, _ = send_deal(9002, REALTY, DEST, 3000, cnvId=1, conv=[])
    for d in (main, side):
        d['code'] = f"СД-{d['id']}"
    put_board({'deals': [main, side], 'incomes': [], 'notes': [], 'wallets': [mirror],
               'convs': [{'id': 1, 'walletId': wid, 'status': 'received',
                          'sources': [{'dealId': DEAL}, {'dealId': 9002}]}]}, version=5)


def test_two_identical_orders_two_transfers_is_not_an_alarm(chain):
    """Пачка из двух одинаковых поручений ждёт двух одинаковых переводов: это норма."""
    identical_batch()
    u = roles()
    at = claim_now(u)
    chain.rows.extend([transfer(1, 3000, ts=at + 1000), transfer(2, 3000, ts=at + 2000)])
    m._stand_track_policy_outgoing(DEAL)
    assert main_deal(DEAL)['transfer']['sends'][0]['hash'] == ref(1)
    assert main_deal(9002)['transfer']['sends'][0]['hash'] == ref(2)
    assert 'transferAlarm' not in main_deal()


def test_two_identical_orders_three_transfers_is_an_alarm(chain):
    identical_batch()
    u = roles()
    at = claim_now(u)
    chain.rows.extend([transfer(1, 3000, ts=at + 1000), transfer(2, 3000, ts=at + 2000),
                       transfer(3, 3000, ts=at + 3000)])
    m._stand_track_policy_outgoing(DEAL)
    assert main_deal()['transferAlarm']['hashes'] == [ref(1), ref(2), ref(3)]
    assert main_deal(DEAL)['transfer']['sends'] == [] and main_deal(9002)['transfer']['sends'] == []


def test_batch_orders_are_matched_one_by_one(chain):
    wid = registry_id(REALTY)
    main, mirror = send_deal(DEAL, REALTY, DEST, 6000, cnvId=1, conv=[9002])
    side, _ = send_deal(9002, REALTY, DEST2, 4000, cnvId=1, conv=[])
    for d in (main, side):
        d['code'] = f"СД-{d['id']}"
    put_board({'deals': [main, side], 'incomes': [], 'notes': [], 'wallets': [mirror],
               'convs': [{'id': 1, 'walletId': wid, 'status': 'received',
                          'sources': [{'dealId': DEAL}, {'dealId': 9002}]}]}, version=5)
    u = roles()
    at = claim_now(u)
    chain.rows.extend([transfer(1, 6000, to=DEST, ts=at + 1000), transfer(2, 4000, to=DEST2, ts=at + 2000),
                       transfer(3, 6000, to=DEST2, ts=at + 3000)])         # сумма от другого поручения
    m._stand_track_policy_outgoing(DEAL)
    assert [s['hash'] for s in main_deal(DEAL)['transfer']['sends']] == [ref(1)]
    assert [s['hash'] for s in main_deal(9002)['transfer']['sends']] == [ref(2)]
    assert 'transferAlarm' not in main_deal()


# ============================ проверенный перевод = подписано и отправлено (решение Карима 28.10)

SIGNER = m.POLICY_SIGNER_ADDRESSES if hasattr(m, 'POLICY_SIGNER_ADDRESSES') else {}


@pytest.fixture
def sent(monkeypatch):
    """Журнал вызовов общего канала уведомлений (в стенде он отключён, но вызов обязан быть один)."""
    calls = []
    monkeypatch.setattr(m, '_stand_tg_send', lambda text: calls.append(text) or False)
    return calls


def closure_notes():
    return [n for n in board()[0].get('notes') or [] if 'отправка закрыта' in n['text']]


def settle(deal_id=DEAL):
    return m._stand_check_transfers(deal_id)


def exchange_claimed(chain, amount=5000):
    board_with(EXCHANGE, amount, postConv='coins')
    u = roles()
    at = claim_now(u)
    return u, at


def test_polled_transfer_closes_the_step_without_manual_signature(chain, sent):
    u, at = exchange_claimed(chain)
    chain.signers = [m.POLICY_SIGNER_ADDRESSES['operator'], m.POLICY_SIGNER_ADDRESSES['teodor']]
    chain.rows.append(transfer(1, 5000, sender=EXCHANGE, ts=at + 5000))
    settle()
    deal = main_deal()
    assert deal['step'] == 's25' and deal['serverTransferComplete'] is True
    assert 'transferConfirmation' not in deal, 'отметка второго подписанта не нужна'
    assert [e['text'] for e in deal['log'] if e['text'].startswith('Подписали в сети')] == [
        'Подписали в сети: операционист, владелец']
    assert deal['transfer']['sends'][0]['markedBy'] == {'kind': 'poller'}
    assert len(sent) == 1, 'общий канал — один раз'
    settle(); m._stand_track_policy_outgoing(DEAL)
    assert len(closure_notes()) == len({n['role'] for n in closure_notes()}) and len(sent) == 1


def test_manually_entered_hash_with_success_also_closes(chain, sent):
    u, at = exchange_claimed(chain)
    chain.rows.append(transfer(1, 5000, sender=EXCHANGE, ts=at + 5000))
    state, version = board()
    state['deals'][0]['transfer']['sends'] = [{'ref': ref(1), 'hash': ref(1), 'amount': 5000,
                                               'net': 'TRC-20', 'status': 'pending'}]
    put_board(state, version)
    settle()
    deal = main_deal()
    assert deal['step'] == 's25' and deal['serverTransferComplete'] is True
    assert 'Подписано в сети' in [e['text'] for e in deal['log']], 'нет данных о подписантах'


def test_manual_confirmation_without_success_does_not_finish_the_deal(chain):
    u, at = exchange_claimed(chain)
    state, version = board()
    state['deals'][0]['step'] = 's24'
    state['deals'][0]['transfer']['sends'] = [{'ref': ref(1), 'hash': ref(1), 'amount': 5000,
                                               'net': 'TRC-20', 'status': 'pending'}]
    put_board(state, version)
    assert api(u['findir'], 'confirm').status_code == 200            # ручная отметка есть
    settle()                                                         # перевода в сети нет
    deal = main_deal()
    assert deal['step'] == 's24' and not deal.get('serverTransferComplete')
    assert deal['transferConfirmation']['role'] == 'findir'


@pytest.mark.parametrize('listed, expected', [
    (['operator', 'teodor'], 'Подписали в сети: операционист, владелец'),
    (['findir', 'teodor'], 'Подписали в сети: финансист, владелец'),
    (['teodor', 'TXFqZbXCqoq5QVxRpp9EGLSzkeLMz8iG5D'],
     'Подписали в сети: владелец, неизвестный адрес TXFqZbXCqoq5QVxRpp9EGLSzkeLMz8iG5D'),
])
def test_signer_names_come_from_the_network_answer(chain, listed, expected):
    u, at = exchange_claimed(chain)
    chain.signers = [m.POLICY_SIGNER_ADDRESSES.get(a, a) for a in listed]
    chain.rows.append(transfer(1, 5000, sender=EXCHANGE, ts=at + 5000))
    settle()
    log = [e['text'] for e in main_deal()['log']]
    assert expected in log
    assert not any('Предупреждение' in t for t in log), 'порог набран — предупреждения нет'


def test_known_signers_below_threshold_warn_but_do_not_block_money(chain):
    u, at = exchange_claimed(chain)
    chain.signers = [m.POLICY_SIGNER_ADDRESSES['findir']]           # вес 1 при пороге 2
    chain.rows.append(transfer(1, 5000, sender=EXCHANGE, ts=at + 5000))
    settle()
    deal = main_deal()
    assert deal['step'] == 's25' and deal['serverTransferComplete'] is True
    assert any(e['text'].startswith('Предупреждение') and 'порог' in e['text'] for e in deal['log'])


def test_closure_notification_text_and_recipients(chain, sent):
    u, at = exchange_claimed(chain)
    chain.signers = [m.POLICY_SIGNER_ADDRESSES['operator'], m.POLICY_SIGNER_ADDRESSES['teodor']]
    chain.rows.append(transfer(1, 5000, sender=EXCHANGE, ts=at + 5000))
    settle()
    notes = closure_notes()
    assert sorted(n['role'] for n in notes) == ['findir', 'manager', 'operator', 'teodor']
    text = notes[0]['text']
    for part in ('СД-9001', 'Клиент Тест', '5 000,00 USDT', 'Груша Обменник', ref(1),
                 'Подписали: операционист, владелец', 'Отметил: найден поиском в сети'):
        assert part in text, part
    assert len({n['text'] for n in notes}) == 1 and sent == [text]
    # без данных о подписантах
    board_with(EXCHANGE, 5000, postConv='coins')
    at = claim_now(u)
    chain.signers = None
    chain.rows[:] = [transfer(2, 5000, sender=EXCHANGE, ts=at + 5000)]
    settle()
    assert 'подписано в сети' in closure_notes()[0]['text']


# --------------------------------------------------------------- «Деньги отправлены»

def mark(client, tx_hash=None, **kw):
    body = {'dealId': DEAL, 'version': board()[1], **kw}
    if tx_hash is not None:
        body['hash'] = tx_hash
    return client.post('/api/stand/transfer/mark-sent', json=body)


def test_operator_closes_for_owner_without_claim(chain, sent):
    board_with(EXCHANGE, 5000, postConv='coins')
    u = roles()
    now = int(time.time() * 1000)
    state, version = board()
    state['deals'][0]['stepEnteredAt'] = now - 1000
    put_board(state, version)
    assert api(u['dispatcher'], 'handoff', toRole='teodor').status_code == 200      # задача у владельца
    chain.signers = [m.POLICY_SIGNER_ADDRESSES['teodor'], m.POLICY_SIGNER_ADDRESSES['findir']]
    chain.rows.append(transfer(1, 5000, sender=EXCHANGE, ts=now + 1000))
    r = mark(u['dispatcher'], ref(1))
    assert r.status_code == 200, r.get_json()
    deal = main_deal()
    assert deal['step'] == 's25' and deal['serverTransferComplete'] is True
    assert [e['text'] for e in deal['log'] if 'Отправку отметил' in e['text']] == [
        f"Отправку отметил Диспетчер за владельца: {ref(1)}"]
    assert 'Подписали в сети: финансист, владелец' in [e['text'] for e in deal['log']]
    assert deal['transfer']['sends'][0]['markedBy']['kind'] == 'operator'
    assert 'Отметил: Диспетчер за владельца.' in closure_notes()[0]['text']
    assert 'transferConfirmation' not in deal and len(sent) == 1


def test_operator_closes_for_named_claim_holder_and_holder_marks_without_for(chain):
    u, at = exchange_claimed(chain)                       # claim у «Имя operator»
    chain.rows.append(transfer(1, 5000, sender=EXCHANGE, ts=at + 1000))
    r = mark(u['dispatcher'], ref(1))
    assert r.status_code == 200, r.get_json()
    assert f"Отправку отметил Диспетчер за Имя operator: {ref(1)}" in [e['text'] for e in main_deal()['log']]
    u, at = exchange_claimed(chain)                       # сам держатель claim
    chain.rows[:] = [transfer(2, 5000, sender=EXCHANGE, ts=at + 1000)]
    r = mark(u['operator'], ref(2))
    assert r.status_code == 200, r.get_json()
    texts = [e['text'] for e in main_deal()['log']]
    assert f'Имя operator отметил отправку: {ref(2)}' in texts and not any(' за ' in t for t in texts if 'отметил' in t.lower())


def test_admin_may_mark_and_found_hash_is_taken_by_default(chain):
    u, at = exchange_claimed(chain)
    chain.rows.append(transfer(1, 5000, sender=EXCHANGE, ts=at + 1000))
    m._stand_track_policy_outgoing(DEAL)                  # система нашла перевод и привязала его
    assert main_deal()['transferFound']['hashes'] == [ref(1)]
    r = mark(u['admin'])                                  # хеш не указан: берём найденный
    assert r.status_code == 200, r.get_json()
    assert main_deal()['step'] == 's25'


@pytest.mark.parametrize('role', ['findir', 'teodor', 'manager'])
def test_other_roles_cannot_mark_for_somebody_else(chain, role):
    u, at = exchange_claimed(chain)
    chain.rows.append(transfer(1, 5000, sender=EXCHANGE, ts=at + 1000))
    before = board()
    assert mark(u[role], ref(1)).status_code == 403
    assert board() == before


@pytest.mark.parametrize('case', ['recipient', 'amount', 'wallet', 'not_success', 'used', 'too_early', 'no_hash', 'unknown'])
def test_unverified_hash_never_closes(chain, case):
    u, at = exchange_claimed(chain)
    row = dict(n=1, amount=5000, to=DEST, sender=EXCHANGE, ts=at + 1000)
    tx_hash = ref(1)
    if case == 'recipient':
        row['to'] = OTHER
    elif case == 'amount':
        row['amount'] = 4990
    elif case == 'wallet':
        row['sender'] = OTHER
    elif case == 'not_success':
        chain.verified = False
    elif case == 'too_early':
        row['ts'] = at - 60000
    elif case == 'used':
        state, version = board()
        state['deals'].append({'id': 9500, 'step': 's27', 'code': 'СД-9500', 'log': [],
                               'transfer': {'sends': [{'ref': ref(1), 'hash': ref(1), 'amount': 5000,
                                                       'net': 'TRC-20', 'status': 'confirmed'}]}})
        put_board(state, version)
    elif case == 'no_hash':
        tx_hash = ''
    elif case == 'unknown':
        tx_hash = ref(77)
    chain.rows.append(transfer(row['n'], row['amount'], to=row['to'], sender=row['sender'], ts=row['ts']))
    before = board()
    r = mark(u['dispatcher'], tx_hash)
    assert r.status_code in (400, 409), r.get_json()
    assert r.get_json()['error']
    assert board() == before and main_deal()['step'] == 's23'


def test_alarm_blocks_marking(chain):
    u, at = exchange_claimed(chain)
    chain.rows.extend([transfer(1, 5000, sender=EXCHANGE, ts=at + 1000), transfer(2, 5000, sender=EXCHANGE, ts=at + 2000)])
    m._stand_track_policy_outgoing(DEAL)
    assert 'transferAlarm' in main_deal()
    before = board()
    assert mark(u['dispatcher'], ref(1)).status_code == 409
    assert board() == before


def test_without_claim_the_transfer_must_be_after_the_step_started(chain):
    board_with(EXCHANGE, 5000, postConv='coins')
    u = roles()
    now = int(time.time() * 1000)
    state, version = board()
    state['deals'][0]['stepEnteredAt'] = now
    put_board(state, version)
    chain.rows.append(transfer(1, 5000, sender=EXCHANGE, ts=now - 60000))
    assert mark(u['dispatcher'], ref(1)).status_code == 409
    chain.rows.append(transfer(2, 5000, sender=EXCHANGE, ts=now + 1000))
    assert mark(u['dispatcher'], ref(2)).status_code == 200


def test_marking_twice_and_poller_after_marking_give_one_log_and_one_notification(chain, sent):
    u, at = exchange_claimed(chain)
    chain.rows.append(transfer(1, 5000, sender=EXCHANGE, ts=at + 1000))
    assert mark(u['dispatcher'], ref(1)).status_code == 200
    snapshot = board()
    assert mark(u['dispatcher'], ref(1)).status_code == 200            # повторное нажатие
    settle(); m._stand_track_policy_outgoing(DEAL)                     # и поллер
    assert board() == snapshot
    assert len(sent) == 1 and len({n['role'] for n in closure_notes()}) == len(closure_notes())
    deal = main_deal()
    assert len([e for e in deal['log'] if 'Отправку отметил' in e['text']]) == 1
    assert len([e for e in deal['log'] if e['text'].startswith('Подписано')]) == 1


def test_race_poller_vs_operator_marking_is_one_event(chain, sent):
    u, at = exchange_claimed(chain)
    chain.rows.append(transfer(1, 5000, sender=EXCHANGE, ts=at + 1000))
    dispatcher = make_user('operator', 'Диспетчер')
    version = board()[1]
    server, thread, base = serve()
    results, barrier = [None, None], threading.Barrier(2)

    def go(i):
        barrier.wait()
        if i == 0:
            m._stand_check_transfers(DEAL)
        else:
            results[1] = requests.post(base + '/api/stand/transfer/mark-sent', headers=cookie_for(dispatcher),
                json={'dealId': DEAL, 'version': version, 'hash': ref(1)}, timeout=20)
    try:
        threads = [threading.Thread(target=go, args=(i,)) for i in range(2)]
        [t.start() for t in threads]
        [t.join(30) for t in threads]
    finally:
        server.shutdown(); thread.join(5); server.server_close()
    assert results[1].status_code in (200, 409), results[1].text[:200]
    deal = main_deal()
    assert deal['step'] == 's25' and deal['serverTransferComplete'] is True
    assert len(sent) == 1, 'уведомление в общий канал — одно'
    per_role = {}
    for n in closure_notes():
        per_role[n['role']] = per_role.get(n['role'], 0) + 1
    assert per_role and set(per_role.values()) == {1}
    assert len([e for e in deal['log'] if e['text'].startswith('Подписано')]) == 1
