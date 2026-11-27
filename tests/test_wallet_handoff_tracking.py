"""Поиск исходящих переводов с кошелька политики после claim: автопривязка хеша, тревога «два перевода».

Сеть — только моки: `stand_egress.read_get` (список переводов TronScan) и `verify_transfer`
(доказательство по хешу), как в test_stand_outgoing_review.py.
"""
import threading
import time
from datetime import datetime, timezone
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


def test_proposal_without_hash_reaches_signer_then_operator_verifies(chain):
    board_with(postConv='coins')
    u = roles()
    at = claim_now(u)
    assert api(u['manager'], 'propose').status_code == 403
    assert api(u['operator'], 'propose', check='Сумма и адрес сверены').status_code == 200
    deal = main_deal()
    assert deal['step'] == 's24' and deal['transfer']['sends'] == []
    assert deal['pay']['check'] == 'Сумма и адрес сверены'
    assert m._stand_current_step_role(board()[0], deal) == 'teodor'
    assert notes_for('подпишите перевод') == ['teodor']
    chain.rows.append(transfer(1, 5000, ts=at + 5000))
    m._stand_check_transfers(DEAL)
    assert main_deal()['step'] == 's24' and main_deal()['transfer']['sends'] == [], \
        'proposal не означает, что подписант уже отправил деньги'
    assert api(u['operator'], 'report-sent').status_code == 403
    assert api(u['teodor'], 'report-sent').status_code == 200
    deal = main_deal()
    assert deal['step'] == 's24' and not deal.get('serverTransferComplete')
    assert deal['transfer']['sends'] == [] and m._stand_current_step_role(board()[0], deal) == 'operator'
    assert notes_for('проверьте исходящий перевод') == ['operator']
    assert api(u['teodor'], 'report-sent').status_code == 200  # повтор без второго события
    assert len([n for n in board()[0]['notes'] if 'проверьте исходящий перевод' in n['text']]) == 1
    result = u['operator'].post('/api/stand/transfers/check', json={'dealId': DEAL})
    assert result.status_code == 200, result.get_json()
    deal = main_deal()
    assert deal['serverTransferComplete'] is True and deal['step'] == 's25'
    assert deal['transfer']['sends'][0]['hash'] == ref(1)


def test_admin_operator_mask_keeps_identity_through_proposal_and_verification(chain):
    board_with(postConv='coins')
    u = roles()
    with u['admin'].session_transaction() as session:
        admin_id = session['user_id']
    at_result = api(u['admin'], 'claim', actorRole='operator')
    assert at_result.status_code == 200, at_result.get_json()
    claim = main_deal()['transferClaim']
    assert claim['byId'] == admin_id and claim['role'] == 'operator'
    claim_version = board()[1]
    assert api(u['admin'], 'claim', actorRole='operator').status_code == 200
    assert board()[1] == claim_version, 'повторный клик не создаёт второй claim'
    assert api(u['admin'], 'claim', actorRole='teodor').status_code == 409
    at = claim['at']
    assert api(u['admin'], 'propose', actorRole='operator').status_code == 200
    assert main_deal()['step'] == 's24' and notes_for('подпишите перевод') == ['teodor']
    assert api(u['admin'], 'report-sent', actorRole='teodor').status_code == 403
    assert api(u['admin'], 'confirm', actorRole='teodor').status_code == 403
    assert main_deal().get('transferSentReport') is None
    assert api(u['teodor'], 'report-sent').status_code == 200
    assert notes_for('проверьте исходящий перевод') == ['operator']
    chain.rows.append(transfer(1, 5000, ts=at + 5000))
    result = u['admin'].post('/api/stand/transfers/check', json={'dealId': DEAL})
    assert result.status_code == 200, result.get_json()
    assert main_deal()['serverTransferComplete'] is True
    assert main_deal()['transfer']['sends'][0]['hash'] == ref(1)


def test_only_real_admin_may_supply_policy_actor_role(chain):
    board_with(postConv='coins')
    u = roles()
    before = board()
    assert api(u['manager'], 'claim', actorRole='operator').status_code == 403
    assert api(u['operator'], 'claim', actorRole='teodor').status_code == 403
    assert board() == before
    assert api(u['operator'], 'claim').status_code == 200
    before = board()
    assert api(u['operator'], 'propose', actorRole='operator').status_code == 403
    assert board() == before


def test_admin_owner_mask_direct_send_only_when_wallet_allows_it(chain):
    board_with(postConv='coins')
    u = roles()
    result = api(u['admin'], 'claim', actorRole='teodor')
    assert result.status_code == 200, result.get_json()
    claim = main_deal()['transferClaim']
    assert claim['role'] == 'teodor' and main_deal()['transferConfirmation']['ownerAlone'] is True
    assert api(u['admin'], 'report-sent', actorRole='teodor').status_code == 200
    assert main_deal()['step'] == 's23' and not main_deal().get('serverTransferComplete')

    address = 'TA4Y62o6YC2Zsck9rZVGTvqW1AQ7X9zTnj'
    registered = u['admin'].post('/api/wallets', json={
        'address': address, 'blockchain': 'TRON', 'owner': 'Тест',
        'accepts_payin': True, 'initiator_roles': ['operator'],
        'confirmer_roles': ['teodor'], 'owner_can_alone': False})
    assert registered.status_code == 200, registered.get_json()
    board_with(wallet=address, postConv='coins')
    before = board()
    assert api(u['admin'], 'claim', actorRole='teodor').status_code == 403
    assert board() == before


def test_operator_manual_hash_after_report_requires_verified_transfer(chain):
    board_with(postConv='coins')
    u = roles()
    at = claim_now(u)
    assert api(u['operator'], 'propose').status_code == 200
    assert api(u['teodor'], 'report-sent').status_code == 200
    chain.broken = True  # автосписок пуст, но проверка конкретного хеша доступна
    assert api(u['operator'], 'mark-sent', hash=ref(2)).status_code != 200
    assert main_deal()['step'] == 's24' and not main_deal().get('serverTransferComplete')
    chain.rows.append(transfer(1, 5000, ts=at + 5000))
    assert api(u['operator'], 'mark-sent', hash=ref(1)).status_code == 200
    assert main_deal()['serverTransferComplete'] is True


def test_legacy_missing_network_keeps_claim_fingerprint_and_accepts_verified_hash(chain):
    ordered_at = int(time.time() * 1000) - 2 * 60 * 60 * 1000
    order_iso = datetime.fromtimestamp(ordered_at / 1000, timezone.utc).isoformat()
    board_with(postConv='coins', outgoingOrderAt=order_iso,
               transfer={'addr': DEST, 'amount': '58\xa0515,63', 'sends': []})
    u = roles()
    at = claim_now(u)
    fingerprint = main_deal()['transferClaim']['fingerprint']
    assert 'net' not in main_deal()['transfer']
    assert api(u['operator'], 'propose').status_code == 200
    assert api(u['teodor'], 'report-sent').status_code == 200
    assert main_deal()['transferClaim']['fingerprint'] == fingerprint
    assert ordered_at < at
    chain.rows.append(transfer(2, 58515.63, ts=ordered_at - 1000))
    too_old = api(u['operator'], 'mark-sent', hash=ref(2))
    assert too_old.status_code == 409 and 'раньше начала отправки' in too_old.get_json()['error']
    assert main_deal()['transfer']['sends'] == []
    chain.rows.append(transfer(3, 58515.63, ts=None))
    no_time = api(u['operator'], 'mark-sent', hash=ref(3))
    assert no_time.status_code == 409 and 'не вернула время' in no_time.get_json()['error']
    chain.rows.pop()
    chain.rows.append(transfer(1, 58515.63, ts=ordered_at + 60 * 60 * 1000))
    assert chain.rows[-1]['block_ts'] < at, 'синтетический перевод после поручения, до claim'
    state, version = board()
    state['deals'].append({'id': 9500, 'step': 's27', 'code': 'СД-9500', 'log': [],
                           'transfer': {'sends': [{'ref': ref(1), 'hash': ref(1),
                                                   'amount': 58515.63, 'net': 'TRC-20',
                                                   'status': 'confirmed'}]}})
    put_board(state, version)
    used = api(u['operator'], 'mark-sent', hash=ref(1))
    assert used.status_code == 409 and 'уже использован' in used.get_json()['error']
    state, version = board()
    state['deals'] = [d for d in state['deals'] if d['id'] != 9500]
    put_board(state, version)
    result = api(u['operator'], 'mark-sent', hash=ref(1))
    assert result.status_code == 200, result.get_json()
    deal = main_deal()
    assert deal['serverTransferComplete'] is True and deal['transfer']['sends'][0]['hash'] == ref(1)
    assert 'net' not in deal['transfer']


def test_legacy_missing_network_uses_same_guard_for_auto_lookup(chain):
    ordered_at = int(time.time() * 1000) - 2 * 60 * 60 * 1000
    order_iso = datetime.fromtimestamp(ordered_at / 1000, timezone.utc).isoformat()
    board_with(postConv='coins', outgoingOrderAt=order_iso,
               transfer={'addr': DEST, 'amount': 5000, 'sends': []})
    u = roles()
    at = claim_now(u)
    assert api(u['operator'], 'propose').status_code == 200
    assert api(u['teodor'], 'report-sent').status_code == 200
    chain.rows.append(transfer(1, 5000, ts=ordered_at + 60 * 60 * 1000))
    assert chain.rows[0]['block_ts'] < at
    result = u['operator'].post('/api/stand/transfers/check', json={'dealId': DEAL})
    assert result.status_code == 200, result.get_json()
    deal = main_deal()
    assert deal['serverTransferComplete'] is True and deal['transfer']['sends'][0]['hash'] == ref(1)


def test_missing_network_inference_requires_both_tron_addresses(chain):
    policy = {'address': REALTY}
    order = {'to': DEST, 'net': None}
    assert m._stand_policy_trc20_order(policy, order)
    assert not m._stand_policy_trc20_order(policy, dict(order, net='ERC-20'))
    assert not m._stand_policy_trc20_order(policy, dict(order, net='unknown'))
    assert not m._stand_policy_trc20_order(policy, dict(order, to='0x' + 'a' * 40))
    assert not m._stand_policy_trc20_order({'address': '0x' + 'b' * 40}, order)


def test_owner_direct_send_reports_without_hash_and_needs_network(chain):
    board_with(postConv='coins')
    u = roles()
    at = claim_now(u, 'teodor')
    assert main_deal()['transferConfirmation']['ownerAlone'] is True
    assert api(u['teodor'], 'propose').status_code == 409
    assert api(u['teodor'], 'report-sent').status_code == 200
    deal = main_deal()
    assert deal['step'] == 's23' and deal['transfer']['sends'] == []
    assert not deal.get('serverTransferComplete')
    assert m._stand_current_step_role(board()[0], deal) == 'operator'
    chain.rows.append(transfer(1, 5000, ts=at + 5000))
    assert u['operator'].post('/api/stand/transfers/check', json={'dealId': DEAL}).status_code == 200
    assert main_deal()['serverTransferComplete'] is True


def test_legacy_s24_without_proposal_can_report(chain):
    board_with()
    u = roles()
    claim_now(u)
    data, version = board()
    data['deals'][0]['step'] = 's24'  # уже открытая на stage задача прежней версии
    put_board(data, version)
    assert api(u['teodor'], 'report-sent').status_code == 200
    assert main_deal()['transferSentReport']['role'] == 'teodor'


def test_operator_can_verify_actual_send_when_signer_forgets_report(chain):
    board_with(postConv='coins')
    u = roles()
    at = claim_now(u)
    assert api(u['operator'], 'propose').status_code == 200
    chain.rows.append(transfer(1, 5000, ts=at + 5000))
    assert api(u['operator'], 'mark-sent', hash=ref(1)).status_code == 200
    assert main_deal()['serverTransferComplete'] is True


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


def test_identical_orders_with_different_server_times_match_each_transfer(chain):
    identical_batch()
    state, version = board()
    ordered_at = int(time.time() * 1000) - 2 * 60 * 60 * 1000
    state['deals'][0]['outgoingOrderAt'] = datetime.fromtimestamp(
        ordered_at / 1000, timezone.utc).isoformat()
    state['deals'][1]['outgoingOrderAt'] = datetime.fromtimestamp(
        (ordered_at + 90 * 60 * 1000) / 1000, timezone.utc).isoformat()
    put_board(state, version)
    u = roles()
    at = claim_now(u)
    assert ordered_at + 90 * 60 * 1000 < at
    chain.rows.extend([transfer(1, 3000, ts=ordered_at + 30 * 60 * 1000),
                       transfer(2, 3000, ts=ordered_at + 100 * 60 * 1000)])
    m._stand_track_policy_outgoing(DEAL)
    assert main_deal(DEAL)['transfer']['sends'][0]['hash'] == ref(1)
    assert main_deal(9002)['transfer']['sends'][0]['hash'] == ref(2)
    assert 'transferAlarm' not in main_deal()


def test_identical_orders_cannot_credit_transfer_before_second_order(chain):
    identical_batch()
    state, version = board()
    ordered_at = int(time.time() * 1000) - 2 * 60 * 60 * 1000
    state['deals'][0]['outgoingOrderAt'] = datetime.fromtimestamp(
        ordered_at / 1000, timezone.utc).isoformat()
    state['deals'][1]['outgoingOrderAt'] = datetime.fromtimestamp(
        (ordered_at + 90 * 60 * 1000) / 1000, timezone.utc).isoformat()
    put_board(state, version)
    u = roles()
    claim_now(u)
    chain.rows.extend([transfer(1, 3000, ts=ordered_at + 30 * 60 * 1000),
                       transfer(2, 3000, ts=ordered_at + 40 * 60 * 1000)])
    m._stand_track_policy_outgoing(DEAL)
    assert main_deal(DEAL)['transfer']['sends'] == []
    assert main_deal(9002)['transfer']['sends'] == []
    assert main_deal()['transferAlarm']['hashes'] == [ref(1), ref(2)]


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


def test_former_executor_cannot_mark_sent_after_takeover(chain):
    u, at = exchange_claimed(chain)
    assert api(u['dispatcher'], 'handoff', toRole='teodor', takeover=True, claimAt=at).status_code == 200
    chain.rows.append(transfer(1, 5000, sender=EXCHANGE, ts=at + 1000))
    before = board()
    assert mark(u['operator'], ref(1)).status_code == 409           # прежний исполнитель
    assert board() == before
    assert mark(u['dispatcher'], ref(1)).status_code == 200         # другой операционист — можно


def early_review_setup(chain):
    ordered_at = int(time.time() * 1000) - 60_000
    order_iso = datetime.fromtimestamp(ordered_at / 1000, timezone.utc).isoformat()
    board_with(postConv='coins', outgoingOrderAt=order_iso)
    u = roles()
    claim_now(u)
    assert api(u['operator'], 'propose').status_code == 200
    assert api(u['teodor'], 'report-sent').status_code == 200
    chain.rows.append(transfer(87, 5000, ts=ordered_at - 120_000))
    return u, order_iso


def early_preview(u):
    response = api(u['operator'], 'mark-sent', hash=ref(87))
    assert response.status_code == 409, response.get_json()
    return response.get_json()['earlyReview']


def test_early_policy_requires_explicit_review_preserves_dates_and_survives_recheck(chain):
    u, order_iso = early_review_setup(chain)
    before = board()
    preview = early_preview(u)
    assert board() == before, 'preview must not write board or evidence'
    assert api(u['operator'], 'mark-sent', hash=ref(87), confirmBeforeOrder=True).status_code == 409
    m._stand_track_policy_outgoing(DEAL)
    assert not main_deal()['transfer']['sends'], 'poller must not attach unreviewed early tx'
    reply = api(u['operator'], 'mark-sent', hash=ref(87), confirmBeforeOrder=True,
                earlyReviewToken=preview['token'])
    assert reply.status_code == 200, reply.get_json()
    deal = main_deal()
    review = deal['transferEarlyReviews'][str(DEAL)]
    assert review['byId'] and review['role'] == 'operator' and review['at']
    assert review['evidence']['timestampMs'] == preview['timestampMs']
    assert deal['outgoingOrderAt'] == order_iso
    assert deal['transfer']['sends'][0]['timestampMs'] == preview['timestampMs']
    assert deal['serverTransferComplete'] is True
    settled = board()
    assert api(u['operator'], 'mark-sent', hash=ref(87), confirmBeforeOrder=True,
               earlyReviewToken=preview['token']).status_code == 200
    assert board() == settled, 'retry must not write a second audit or credit'
    m._stand_check_transfers(DEAL)
    assert len(main_deal()['transfer']['sends']) == 1
    assert main_deal()['transferEarlyReviews'] == deal['transferEarlyReviews']


@pytest.mark.parametrize('role', ['manager', 'findir', 'teodor'])
def test_early_policy_review_denies_other_roles(chain, role):
    u, _ = early_review_setup(chain)
    preview = early_preview(u)
    before = board()
    assert api(u[role], 'mark-sent', hash=ref(87), confirmBeforeOrder=True,
               earlyReviewToken=preview['token']).status_code == 403
    assert board() == before


@pytest.mark.parametrize('change', ['time', 'hash', 'amount', 'sender', 'recipient', 'order', 'network'])
def test_early_policy_review_rejects_stale_proof_or_order(chain, change):
    u, _ = early_review_setup(chain)
    preview = early_preview(u)
    tx = chain.rows[0]
    tx_hash = ref(87)
    if change == 'time': tx['block_ts'] -= 1000
    if change == 'hash': tx['transaction_id'] = tx_hash = ref(88)
    if change == 'amount': tx['quant'] = '5000001000'
    if change == 'sender': tx['from_address'] = OTHER
    if change == 'recipient': tx['to_address'] = DEST2
    if change in ('order', 'network'):
        state, version = board()
        if change == 'order': state['deals'][0]['outgoingOrderAt'] = '2020-01-01T00:00:00Z'
        else: state['deals'][0]['transfer']['net'] = 'ERC-20'
        put_board(state, version)
    before = board()
    reply = api(u['operator'], 'mark-sent', hash=tx_hash, confirmBeforeOrder=True,
                earlyReviewToken=preview['token'])
    # Сдвиг поручения в прошлое не превращает старое согласие в обычную отметку.
    assert reply.status_code == 409, reply.get_json()
    assert board() == before


@pytest.mark.parametrize('location', ['payin', 'conversion', 'sibling', 'registry'])
def test_early_policy_review_rejects_hash_reuse(chain, monkeypatch, location):
    u, _ = early_review_setup(chain)
    preview = early_preview(u)
    state, version = board()
    if location == 'payin': state['deals'][0]['payinHashes'] = [{'hash': ref(87)}]
    if location == 'conversion': state['convs'] = [{'id': 77, 'txs': [{'hash': ref(87)}]}]
    if location == 'sibling': state['deals'].append({'id': 9999, 'transfer': {'sends': [{'hash': ref(87)}]}})
    if location == 'registry': monkeypatch.setattr(m, 'get_used_transaction_hashes', lambda db: {ref(87)})
    put_board(state, version)
    before = board()
    reply = api(u['operator'], 'mark-sent', hash=ref(87), confirmBeforeOrder=True,
                earlyReviewToken=preview['token'])
    assert reply.status_code == 409 and 'уже использован' in reply.get_json()['error']
    assert board() == before


@pytest.mark.parametrize('change', ['inject', 'edit', 'delete'])
def test_early_policy_audit_is_server_owned_in_full_board_put(chain, change):
    from tests.qa_wallet_roles_helpers import checked_put
    u, _ = early_review_setup(chain)
    preview = early_preview(u)
    if change != 'inject':
        assert api(u['operator'], 'mark-sent', hash=ref(87), confirmBeforeOrder=True,
                   earlyReviewToken=preview['token']).status_code == 200
    state, version = board()
    before = board()
    if change == 'inject':
        state['deals'][0]['transferEarlyReviews'] = {str(DEAL): {'binding': preview, 'byId': 1,
                                                              'role': 'operator', 'at': 1}}
    elif change == 'edit':
        state['deals'][0]['transferEarlyReviews'][str(DEAL)]['binding']['hash'] = ref(88)
    else:
        state['deals'][0].pop('transferEarlyReviews')
    reply = checked_put(u['admin'], version, state)
    assert reply.status_code == 409 and 'только сервер' in reply.get_json()['error']
    assert board() == before


@pytest.mark.browser
@pytest.mark.parametrize('width', [375, 1280])
def test_early_policy_browser_operator_confirms_and_reload_keeps_audit(chain, pytestconfig, width):
    from pathlib import Path
    from urllib.parse import urlsplit
    from playwright.sync_api import sync_playwright, expect
    u, order_iso = early_review_setup(chain)
    with u['operator'].session_transaction() as session:
        uid = session['user_id']
    server, thread, base = serve()
    out = Path('/tmp/calccrm-early-policy-browser')
    out.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=pytestconfig.getoption('--chromium-executable'))
            context = browser.new_context(viewport={'width': width, 'height': 900}, bypass_csp=True)
            context.add_cookies([{'name': 'session', 'value': cookie_for(uid)['Cookie'].split('=', 1)[1], 'url': base}])
            def route(r):
                url = urlsplit(r.request.url)
                if url.hostname != '127.0.0.1': r.abort()
                elif url.path.startswith('/api/') and url.path not in (
                        '/api/auth/me', '/api/stand/state', '/api/wallets', '/api/stand/transfer/mark-sent'):
                    r.fulfill(json={'success': True, 'wallets': [], 'admins': [], 'data': {}, 'incomes': [], 'txs': []})
                else: r.continue_()
            context.route('**/*', route)
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(base+'/tasks')
            page.wait_for_function('() => typeof S!=="undefined" && S.deals.some(d=>d.id===9001) && CRM_WALLETS.length>0', timeout=8000)
            page.evaluate("S.open=9001;S.view='task';render()")
            page.screenshot(path=str(out/f'before-{width}.png'), full_page=True)
            assert page.locator('#ms_hash_9001').count(), (errors, page.locator('body').inner_text())
            page.locator('#ms_hash_9001').fill(ref(87))
            page.locator('[data-mark-sent-btn]').click()
            expect(page.locator('#ms_review_9001')).to_be_visible()
            page.screenshot(path=str(out/f'preview-{width}.png'), full_page=True)
            assert main_deal()['step'] == 's24' and not main_deal()['transfer']['sends']
            page.get_by_role('button', name='Засчитать ранний перевод', exact=True).click()
            assert not main_deal()['transfer']['sends']
            page.locator('#ms_before_9001').check()
            with page.expect_response(lambda r: r.url.endswith('/api/stand/transfer/mark-sent') and r.status == 200):
                page.get_by_role('button', name='Засчитать ранний перевод', exact=True).click()
            assert main_deal()['serverTransferComplete'] is True
            page.reload()
            page.wait_for_function('() => typeof S!=="undefined" && S.deals.some(d=>d.id===9001 && d.serverTransferComplete)')
            page.evaluate("S.open=9001;S.view='deal';render()")
            page.screenshot(path=str(out/f'accepted-{width}.png'), full_page=True)
            assert main_deal()['outgoingOrderAt'] == order_iso
            assert len(main_deal()['transfer']['sends']) == 1
            assert not errors, errors
            browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


@pytest.mark.parametrize('ledger', ['payin', 'wallet'])
def test_early_policy_sql_ledger_reuse_is_rejected(chain, ledger):
    u, _ = early_review_setup(chain)
    preview = early_preview(u)
    db = m.get_session()
    try:
        if ledger == 'payin':
            db.add(m.PayinTx(tx_hash=ref(87), amount_usdt=5000, source='manual'))
        else:
            db.add(m.WalletOperation(wallet_id=registry_id(REALTY), type='expense',
                                    amount=5000, tx_hash=ref(87)))
        db.commit()
    finally:
        db.close()
    before = board()
    reply = api(u['operator'], 'mark-sent', hash=ref(87), confirmBeforeOrder=True,
                earlyReviewToken=preview['token'])
    assert reply.status_code == 409 and 'уже использован' in reply.get_json()['error']
    assert board() == before


@pytest.mark.parametrize('action', ['mark', 'recheck'])
def test_early_policy_cached_review_rejects_changed_proof_in_partial_batch(chain, monkeypatch, action):
    # Регрессия независимой QA: согласован первый перевод, второе поручение ещё открыто.
    u, original = early_review_setup(chain)
    state, version = board()
    main = state['deals'][0]
    main.update(cnvId=1, conv=[9002])
    side, _ = send_deal(9002, REALTY, DEST2, 1000, cnvId=1, conv=[],
                        outgoingOrderAt=original, postConv='coins')
    state['deals'].append(side)
    state['convs'] = [{'id': 1, 'sources': [{'dealId': DEAL}, {'dealId': 9002}]}]
    for key in ('transferClaim', 'transferProposal', 'transferSentReport', 'transferConfirmation'):
        main.pop(key, None)
    main['step'] = 's23'
    put_board(state, version)
    claim_now(u)
    assert api(u['operator'], 'propose').status_code == 200
    assert api(u['teodor'], 'report-sent').status_code == 200
    preview = early_preview(u)
    reply = api(u['operator'], 'mark-sent', hash=ref(87), confirmBeforeOrder=True,
                earlyReviewToken=preview['token'])
    assert reply.status_code == 200, reply.get_json()
    assert not main_deal().get('serverTransferComplete')
    chain.rows[0]['quant'] = '5000001000'  # Допуск обычного verify не должен ослаблять ранний review.
    before = board()
    if action == 'mark':
        reply = api(u['operator'], 'mark-sent', hash=ref(87))
        assert reply.status_code == 409, reply.get_json()
        assert board() == before
    else:
        # Синтетическая пачка проверяет исходящий proof, рублёвые приходные документы здесь не моделируются.
        monkeypatch.setattr(m, '_stand_check_batch_funding', lambda *a, **kw: None)
        result = m._stand_check_transfers(DEAL)
        assert result['success'], result
        assert main_deal()['transfer']['sends'][0]['status'] == 'mismatch'
        assert not main_deal().get('serverTransferComplete')
