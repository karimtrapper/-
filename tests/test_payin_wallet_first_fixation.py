"""Крипто-сделка не виснет на «Ждём приход», если кошелёк прихода не выбирали вручную (QA 29.10, БАГ 1).

Раньше walletId писался впервые на s14 одним PUT с переходом s14→s22 — сервер отвечал 409,
а хеш уже был привязан, и повторная проверка тоже давала 409. Теперь: кошелёк фиксируется на s11,
первичная фиксация дефолтного кошелька на s14 разрешена, любая другая смена — нет, а повтор
хеша на той же сделке идемпотентен. Сеть замокана, данные синтетические.
"""
import copy

import pytest

import app as m
from tests.qa_wallet_roles_helpers import make_user, client_for, put_board, board, registry_id
from tests.test_wallet_roles_qa import REALTY, EXCHANGE, seeded, stand  # noqa: F401

CLIENT_WALLET = 'TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn'
HASH = 'a1' * 32
OTHER_HASH = 'b2' * 32
STARTED = 1700000000000


def deal_of(kind='realty', **extra):
    d = {'id': 7, 'code': 'СД-7', 'client': 'Синтетика', 'payType': 'Крипта', 'step': 's14',
         'type': 'Оплата недвижимости' if kind == 'realty' else 'Обмен валюты',
         'kind': 'Лизхолд', 'payinHashes': [], 'log': [{'at': STARTED, 'text': 'заведена'}]}
    d.update(extra)
    return d


def paid(hash_=HASH, amount=100.0, to=REALTY):
    return {'hash': hash_, 'network': 'TRC20', 'amount': amount, 'from': CLIENT_WALLET, 'to': to,
            'verified': True, 'verifiedAt': 'now', 'timestampMs': STARTED + 1000, 'sourceKnown': False}


@pytest.fixture
def chain(monkeypatch):
    """Подмена ТОЛЬКО ответа сети."""
    state = {'to': REALTY, 'amount': 100.0}

    def fake(ref, network, sender, receiver, amount, **kw):
        if receiver is not None and state['to'] != receiver:
            return {'status': 'mismatch', 'checkError': 'адрес не совпал'}
        return {'status': 'confirmed', 'verifiedAmount': state['amount'], 'verifiedAt': 'now',
                'timestampMs': STARTED + 1000, 'from': CLIENT_WALLET, 'to': state['to']}
    monkeypatch.setattr(m, 'verify_transfer', fake)
    return state


def operator_client():
    return client_for(make_user('operator'))


def put(client, mutate):
    """PUT доски, как делает клиент: текущее состояние + правка сделки 7."""
    state, version = board()
    state = copy.deepcopy(state)
    mutate(next(d for d in state['deals'] if d['id'] == 7))
    return client.put('/api/stand/state', json={'version': version, 'data': state})


def deal7():
    return next(d for d in board()[0]['deals'] if d['id'] == 7)


def seed(*deals):
    put_board({'deals': list(deals), 'convs': [], 'wallets': []})


# ------------------------------------------------ 1. фиксация на s11

@pytest.mark.parametrize('kind, address', [('realty', REALTY), ('exchange', EXCHANGE)])
def test_s11_saves_default_wallet_explicitly(seeded, kind, address):
    """Оператор не трогал select: клиент отправляет дефолт явно — сервер на s11 его сохраняет."""
    seed(deal_of(kind, step='s11'))
    default_id = registry_id(address)
    r = put(operator_client(), lambda d: d.update(walletId=str(default_id)))
    assert r.status_code == 200, r.get_json()
    assert deal7()['walletId'] == str(default_id)


# ------------------------------------------------ QA-сценарий целиком

@pytest.mark.parametrize('kind, address', [('realty', REALTY), ('exchange', EXCHANGE)])
def test_full_qa_scenario_untouched_select(seeded, chain, kind, address):
    """s11 (select не трогали) → walletId записан → приход по сети → s22, без 409 на переходе."""
    operator = operator_client()
    chain['to'] = address
    seed(deal_of(kind, step='s11'))
    default_id = str(registry_id(address))
    assert put(operator, lambda d: d.update(walletId=default_id)).status_code == 200
    # договор выпущен, менеджер отправил — сделка ждёт приход (шаги между s11 и s14 не про кошелёк)
    state, _ = board()
    state['deals'][0].update(step='s14', docVersion=1, docPack={'agreementId': 1})
    put_board(state, version=board()[1] + 1)
    r = operator.post('/api/stand/payin/check', json={'dealId': 7, 'hash': HASH})
    assert r.status_code == 200, r.get_json()
    # payinSettle: walletId уже записан, в PUT идёт только переход шага
    moved = put(operator, lambda d: d.update(step='s22', incomeAmount=100.0))
    assert moved.status_code == 200, moved.get_json()
    saved = deal7()
    assert saved['step'] == 's22' and saved['walletId'] == default_id
    assert saved['payinHashes'][0]['hash'] == HASH


# ------------------------------------------------ 3. зависшая сделка

@pytest.mark.parametrize('kind, address', [('realty', REALTY), ('exchange', EXCHANGE)])
def test_stuck_deal_unblocks_with_first_fixation(seeded, chain, kind, address):
    """s14, walletId=null, хеш на полную сумму: s14→s22 с записью дефолтного кошелька проходит,
    а повторная проверка того же хеша на этой сделке не даёт 409."""
    operator = operator_client()
    chain['to'] = address
    seed(deal_of(kind, payinHashes=[paid(to=address)], docVersion=1, docPack={'agreementId': 1}))
    again = operator.post('/api/stand/payin/check', json={'dealId': 7, 'hash': HASH})
    assert again.status_code == 200, again.get_json()
    assert again.get_json()['idempotent'] is True
    assert len(deal7()['payinHashes']) == 1, 'повтор не плодит дубликатов прихода'
    default_id = str(registry_id(address))
    moved = put(operator, lambda d: d.update(step='s22', incomeAmount=100.0, walletId=default_id))
    assert moved.status_code == 200, moved.get_json()
    saved = deal7()
    assert saved['step'] == 's22' and saved['walletId'] == default_id


def test_stuck_deal_first_fixation_legacy_default(seeded):
    """Тип без purpose: дефолт сервера — легаси 'grusha' (его и показывал payinWallet)."""
    seed(deal_of(type='Прочее', payinHashes=[paid()]))
    r = put(operator_client(), lambda d: d.update(step='s22', walletId='grusha'))
    assert r.status_code == 200, r.get_json()
    assert deal7()['walletId'] == 'grusha'


# ------------------------------------------------ подмена кошелька на s14 — по-прежнему 409

def test_swap_to_non_default_wallet_when_null_is_rejected(seeded):
    seed(deal_of(payinHashes=[paid()]))
    other = str(registry_id(EXCHANGE))   # у сделки недвижимости дефолт — REALTY
    r = put(operator_client(), lambda d: d.update(step='s22', walletId=other))
    assert r.status_code == 409, r.get_json()
    assert 'ошелёк' in r.get_json()['error']
    saved = deal7()
    assert saved['step'] == 's14' and 'walletId' not in saved


def test_swap_to_non_default_wallet_without_step_move_is_rejected(seeded):
    seed(deal_of(payinHashes=[paid()]))
    r = put(operator_client(), lambda d: d.update(walletId=str(registry_id(EXCHANGE))))
    assert r.status_code == 409, r.get_json()


def test_swap_when_wallet_already_set_is_rejected(seeded):
    seed(deal_of(walletId=str(registry_id(REALTY)), payinHashes=[paid()]))
    other = str(registry_id(EXCHANGE))
    r = put(operator_client(), lambda d: d.update(step='s22', walletId=other))
    assert r.status_code == 409, r.get_json()
    assert deal7()['walletId'] == str(registry_id(REALTY))


def test_custom_wallet_on_s14_is_rejected(seeded):
    seed(deal_of(payinHashes=[paid()]))
    r = put(operator_client(), lambda d: d.update(
        step='s22', walletId='custom',
        payinCustom={'network': 'TRC-20', 'addr': CLIENT_WALLET, 'owner': 'x', 'multisig': False}))
    assert r.status_code == 409, r.get_json()


def test_first_fixation_only_on_s14(seeded):
    """На других шагах после выпуска договора первичная запись по-прежнему закрыта."""
    seed(deal_of(step='s12', docVersion=1, docPack={'agreementId': 1}))
    r = put(operator_client(), lambda d: d.update(walletId=str(registry_id(REALTY))))
    assert r.status_code == 409, r.get_json()


# ------------------------------------------------ 4. хеш другой сделки

def test_hash_bound_to_another_deal_still_conflicts(seeded, chain):
    other = deal_of(id=8, code='СД-8', walletId=str(registry_id(REALTY)), payinHashes=[paid()])
    mine = deal_of()
    seed(mine, other)
    r = operator_client().post('/api/stand/payin/check', json={'dealId': 7, 'hash': HASH})
    assert r.status_code == 409 and 'уже привязан' in r.get_json()['error']
    assert next(d for d in board()[0]['deals'] if d['id'] == 7)['payinHashes'] == []


def test_hash_present_in_own_and_other_deal_conflicts(seeded, chain):
    """Если хеш записан ещё и в чужую сделку, идемпотентность не применяется."""
    seed(deal_of(payinHashes=[paid()]),
         deal_of(id=8, code='СД-8', payinHashes=[paid()]))
    r = operator_client().post('/api/stand/payin/check', json={'dealId': 7, 'hash': HASH})
    assert r.status_code == 409 and 'уже привязан' in r.get_json()['error']


def test_new_hash_still_recorded_normally(seeded, chain):
    seed(deal_of(payinHashes=[paid()]))
    chain['amount'] = 5.0
    r = operator_client().post('/api/stand/payin/check', json={'dealId': 7, 'hash': OTHER_HASH})
    assert r.status_code == 200 and not r.get_json().get('idempotent')
    assert [h['hash'] for h in deal7()['payinHashes']] == [HASH, OTHER_HASH]
