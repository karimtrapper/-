"""QA пункта 2: кошелёк прихода по типу сделки и неподтверждённое расхождение получателя.

Деньги не засчитываются молча: перевод на чужой кошелёк даёт постоянное
предупреждение, которое подтверждает аутентифицированный сотрудник, а засчитать
перевод можно только на кошелёк, который сделка ожидает.
"""
import copy

import pytest

import app as m
from tests.qa_wallet_roles_helpers import checked_put, make_user, client_for, put_board, board
from tests.test_wallet_roles_qa import REALTY, EXCHANGE, LEGACY, seeded, stand  # noqa: F401

CLIENT_WALLET = 'TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn'   # отправитель-клиент (синтетика)
HASH = 'a1' * 32
STARTED = 1700000000000


def crypto_deal(**extra):
    d = {'id': 7, 'payType': 'Крипта', 'step': 's14', 'type': 'Оплата недвижимости',
         'kind': 'Лизхолд', 'payinHashes': [], 'log': [{'at': STARTED, 'text': 'заведена'}]}
    d.update(extra)
    return d


def wallet_id(address):
    s = m.get_session()
    try:
        return s.query(m.Wallet).filter(m.Wallet.address == address).one().id
    finally:
        s.close()


@pytest.fixture
def chain(monkeypatch):
    """Подмена ТОЛЬКО ответа сети: получатель в хеше задаёт тест."""
    state = {'to': None, 'amount': 100.0, 'from': CLIENT_WALLET, 'calls': []}

    def fake(ref, network, sender, receiver, amount, **kw):
        state['calls'].append((sender, receiver, amount, kw))
        if receiver is not None:
            # строгая проверка получателя, как в настоящем verifier
            if state['to'] != receiver:
                return {'status': 'mismatch', 'checkError': 'адрес не совпал'}
        return {'status': 'confirmed', 'verifiedAmount': state['amount'], 'verifiedAt': 'now',
                'timestampMs': STARTED + 1000, 'from': state['from'], 'to': state['to']}
    monkeypatch.setattr(m, 'verify_transfer', fake)
    return state


# ------------------------------------------------ кошелёк по умолчанию по типу

@pytest.mark.parametrize('deal_type, expected', [
    ('Оплата недвижимости', REALTY), ('Обмен валюты', EXCHANGE)])
def test_default_payin_wallet_follows_deal_type(seeded, deal_type, expected):
    deal = crypto_deal(type=deal_type)
    network, receiver = m._stand_payin_target({'deals': [deal], 'wallets': []}, deal)
    assert (network, receiver) == ('trc20', expected)


@pytest.mark.parametrize('explicit', ['grusha', 'andrey'])
def test_explicit_in_flight_wallet_is_not_rerouted(seeded, explicit):
    for deal_type in ('Оплата недвижимости', 'Обмен валюты'):
        deal = crypto_deal(type=deal_type, walletId=explicit)
        before = copy.deepcopy(deal)
        _, receiver = m._stand_payin_target({'deals': [deal], 'wallets': []}, deal)
        assert receiver not in (REALTY, EXCHANGE)
        assert deal == before


def test_explicit_registry_wallet_id_is_honoured_over_type_default(seeded):
    deal = crypto_deal(type='Обмен валюты', walletId=wallet_id(REALTY))
    assert m._stand_payin_target({'deals': [deal], 'wallets': []}, deal)[1] == REALTY


def test_wallet_added_for_other_type_not_selected_when_inactive(seeded):
    s = m.get_session()
    try:
        w = s.query(m.Wallet).filter(m.Wallet.address == EXCHANGE).one()
        w.active = False
        s.commit()
    finally:
        s.close()
    deal = crypto_deal(type='Обмен валюты')
    _, receiver = m._stand_payin_target({'deals': [deal], 'wallets': []}, deal)
    assert receiver != EXCHANGE


# --------------------------------------------- расхождение получателя, s14 payin

def test_wrong_wallet_payin_is_persisted_warning_not_credit(seeded, chain):
    deal = crypto_deal(walletId=wallet_id(REALTY))
    put_board({'deals': [deal], 'convs': [], 'wallets': []})
    chain['to'] = EXCHANGE      # деньги ушли на соседний кошелёк компании
    operator = client_for(make_user('operator'))
    r = operator.post('/api/stand/payin/check', json={'dealId': 7, 'hash': HASH})
    assert r.status_code == 409, r.get_json()
    warning = r.get_json()['warning']
    assert warning['expected'] == REALTY and warning['actual'] == EXCHANGE
    assert warning['acknowledgedById'] is None
    state, version = board()
    d = state['deals'][0]
    assert d['payinHashes'] == [] and d['step'] == 's14' and 'payerWallet' not in d
    assert d['recipientWarnings'] == [{**warning}]
    # повтор не плодит дубликатов и тоже не засчитывает
    again = operator.post('/api/stand/payin/check', json={'dealId': 7, 'hash': HASH})
    assert again.status_code == 409
    assert len(board()[0]['deals'][0]['recipientWarnings']) == 1
    assert board()[0]['deals'][0]['payinHashes'] == []


def test_ack_requires_authenticated_checker_and_records_actor_id(seeded, chain):
    deal = crypto_deal(walletId=wallet_id(REALTY))
    put_board({'deals': [deal], 'convs': [], 'wallets': []})
    chain['to'] = EXCHANGE
    op_id = make_user('operator')
    operator = client_for(op_id)
    warning = operator.post('/api/stand/payin/check', json={'dealId': 7, 'hash': HASH}).get_json()['warning']
    version = board()[1]
    body = {'dealId': 7, 'hash': HASH, 'expected': REALTY, 'actual': EXCHANGE, 'version': version}
    # без входа и неподходящими ролями — нет
    assert m.app.test_client().post('/api/stand/incoming/ack-recipient', json=body).status_code in (401, 403)
    for role in ('teodor', 'buyer'):
        denied = client_for(make_user(role)).post('/api/stand/incoming/ack-recipient', json=body)
        assert denied.status_code == 403
    assert board()[0]['deals'][0]['recipientWarnings'][0]['acknowledgedById'] is None
    # актор берётся из сессии, а не из тела
    forged = dict(body, acknowledgedById=999999, actorId=999999)
    ok = operator.post('/api/stand/incoming/ack-recipient', json=forged)
    assert ok.status_code == 200, ok.get_json()
    saved = board()[0]['deals'][0]
    assert saved['recipientWarnings'][0]['acknowledgedById'] == op_id
    assert saved['payinHashes'] == [], 'подтверждение расхождения не засчитывает деньги'
    # несовпадающие параметры и устаревшая версия — отказ
    stale = operator.post('/api/stand/incoming/ack-recipient', json=dict(body, version=version))
    assert stale.status_code == 409
    wrong = operator.post('/api/stand/incoming/ack-recipient',
                          json=dict(body, version=board()[1], actual=LEGACY))
    assert wrong.status_code == 409


UNKNOWN = 'TA4Y62o6YC2Zsck9rZVGTvqW1AQ7X9zTnj'      # валидный адрес, которого нет в реестре


def warned_board(chain, actual, **deal_extra):
    deal = crypto_deal(walletId=wallet_id(REALTY), docs={'signed': [{'file': 'signed.pdf'}]},
                       docFields={'payTo': 'Flow Sole'}, docVersion=2, **deal_extra)
    put_board({'deals': [deal], 'convs': [], 'wallets': []})
    chain['to'] = actual
    op_id = make_user('operator')
    operator = client_for(op_id)
    assert operator.post('/api/stand/payin/check', json={'dealId': 7, 'hash': HASH}).status_code == 409
    return operator, op_id


def ack(operator, actual, expected=REALTY, hash_=HASH):
    return operator.post('/api/stand/incoming/ack-recipient', json={
        'dealId': 7, 'hash': hash_, 'expected': expected, 'actual': actual, 'version': board()[1]})


def reconcile(client, hash_=HASH, **extra):
    return client.post('/api/stand/payin/reconcile-recipient',
                       json={'dealId': 7, 'hash': hash_, 'version': board()[1], **extra})


def test_s14_wrong_wallet_full_reconciliation_happy_path(seeded, chain):
    """warning -> ack -> reconcile (кошелёк сделки = фактический) -> повторная проверка -> зачёт."""
    operator, op_id = warned_board(chain, EXCHANGE)
    before_docs = {k: board()[0]['deals'][0][k] for k in ('docs', 'docFields', 'docVersion')}
    assert reconcile(operator).status_code == 409, 'без подтверждения расхождения сверка закрыта'
    assert ack(operator, EXCHANGE).status_code == 200
    # до сверки повторная проверка не засчитывает
    assert operator.post('/api/stand/payin/check', json={'dealId': 7, 'hash': HASH}).status_code == 409
    assert board()[0]['deals'][0]['payinHashes'] == []
    r = reconcile(operator)
    assert r.status_code == 200, r.get_json()
    deal = board()[0]['deals'][0]
    assert str(deal['walletId']) == str(wallet_id(EXCHANGE))
    assert {k: deal[k] for k in before_docs} == before_docs, 'подписанный документ не меняется'
    assert deal['recipientWarnings'][0]['acknowledgedById'] == op_id, 'история расхождения сохранена'
    assert deal['payinHashes'] == [], 'сама сверка денег не засчитывает'
    credited = operator.post('/api/stand/payin/check', json={'dealId': 7, 'hash': HASH})
    assert credited.status_code == 200, credited.get_json()
    tx = board()[0]['deals'][0]['payinHashes'][0]
    assert tx['to'] == EXCHANGE and tx['verified'] is True and tx['amount'] == 100.0


def test_s14_reconciliation_blocks_unregistered_external_recipient(seeded, chain):
    operator, _ = warned_board(chain, UNKNOWN)
    assert ack(operator, UNKNOWN).status_code == 200
    before = board()[0]['deals'][0]['walletId']
    assert reconcile(operator).status_code in (400, 409)
    assert board()[0]['deals'][0]['walletId'] == before
    assert operator.post('/api/stand/payin/check', json={'dealId': 7, 'hash': HASH}).status_code == 409
    assert board()[0]['deals'][0]['payinHashes'] == []


def test_s14_reconciliation_is_role_limited_and_ignores_body_wallet(seeded, chain):
    operator, _ = warned_board(chain, EXCHANGE)
    assert ack(operator, EXCHANGE).status_code == 200
    for role in ('manager', 'teodor', 'findir', 'buyer'):
        r = reconcile(client_for(make_user(role)))
        assert r.status_code == 403, (role, r.get_json())
    assert str(board()[0]['deals'][0]['walletId']) == str(wallet_id(REALTY))
    # адрес из тела запроса не принимается: кошелёк определяет только сервер по хешу
    r = reconcile(operator, walletId='custom', addr=UNKNOWN, actual=UNKNOWN, to=UNKNOWN)
    assert r.status_code in (200, 400)
    assert str(board()[0]['deals'][0]['walletId']) == str(wallet_id(EXCHANGE))


def test_s14_reconciliation_refused_after_credit_or_for_other_hash(seeded, chain):
    operator, _ = warned_board(chain, EXCHANGE)
    assert ack(operator, EXCHANGE).status_code == 200
    assert reconcile(operator, hash_='b2' * 32).status_code == 409       # хеш без предупреждения
    stale = operator.post('/api/stand/payin/reconcile-recipient',
                          json={'dealId': 7, 'hash': HASH, 'version': board()[1] - 1})
    assert stale.status_code == 409
    assert str(board()[0]['deals'][0]['walletId']) == str(wallet_id(REALTY))
    # деньги уже зачтены на ожидаемый кошелёк -> менять кошелёк сделки нельзя
    state, _ = board()
    state['deals'][0]['payinHashes'] = [{'hash': 'c3' * 32, 'amount': 5, 'verified': True,
                                         'network': 'TRC20', 'to': REALTY}]
    put_board(state, version=board()[1])
    assert reconcile(operator).status_code == 409
    assert str(board()[0]['deals'][0]['walletId']) == str(wallet_id(REALTY))


def test_forged_state_put_cannot_add_remove_or_acknowledge_warning(seeded, chain):
    deal = crypto_deal(walletId=wallet_id(REALTY))
    put_board({'deals': [deal], 'convs': [], 'wallets': []})
    chain['to'] = EXCHANGE
    operator = client_for(make_user('operator'))
    operator.post('/api/stand/payin/check', json={'dealId': 7, 'hash': HASH})
    snap = operator.get('/api/stand/state').get_json()
    witness = 'фиксирует только сервер'
    for mutate, wit in (
            (lambda d: d['recipientWarnings'][0].update(acknowledgedById=1, acknowledgedAt=1), witness),
            (lambda d: d.update(recipientWarnings=[]), witness),
            (lambda d: d.pop('recipientWarnings'), witness),
            (lambda d: d['recipientWarnings'].append({'hash': 'f' * 64, 'expected': REALTY,
                                                      'actual': EXCHANGE, 'acknowledgedById': 1}), witness),
            (lambda d: d.update(payinHashes=[{'hash': HASH, 'amount': 100, 'verified': True,
                                              'network': 'TRC20', 'to': REALTY}]), None)):
        forged = copy.deepcopy(snap)
        mutate(forged['data']['deals'][0])
        r = checked_put(operator, snap['version'], forged['data'], witness=wit)
        stored = board()[0]['deals'][0]
        assert stored['recipientWarnings'][0]['acknowledgedById'] is None
        assert not any(h.get('verified') for h in stored['payinHashes'])
        assert r.status_code in (200, 400, 403, 409)


@pytest.mark.parametrize('legacy_wallet', ['grusha', 'andrey'])
def test_legacy_wallet_wrong_receiver_keeps_old_contract_and_changes_nothing(seeded, chain, legacy_wallet):
    """Выбор не-политического кошелька: прежнее поведение (422), никаких предупреждений/ack."""
    deal = crypto_deal(walletId=legacy_wallet)
    put_board({'deals': [deal], 'convs': [], 'wallets': []})
    chain['to'] = EXCHANGE
    before = board()
    r = client_for(make_user('operator')).post('/api/stand/payin/check',
                                                json={'dealId': 7, 'hash': HASH})
    assert r.status_code == 422, r.get_json()
    assert board() == before
    assert 'recipientWarnings' not in board()[0]['deals'][0]


def test_correct_wallet_payin_unchanged(seeded, chain):
    deal = crypto_deal(walletId=wallet_id(REALTY))
    put_board({'deals': [deal], 'convs': [], 'wallets': []})
    chain['to'] = REALTY
    r = client_for(make_user('operator')).post('/api/stand/payin/check',
                                                json={'dealId': 7, 'hash': HASH})
    assert r.status_code == 200, r.get_json()
    d = board()[0]['deals'][0]
    assert d['payinHashes'][0]['to'] == REALTY and d['payinHashes'][0]['verified'] is True
    assert not d.get('recipientWarnings')


def test_tron_receiver_compare_is_case_sensitive(seeded, chain):
    """Base58 регистрозависим: адрес, отличающийся только регистром допустимой буквы, — другой адрес.

    Вариант не достижим на реальной цепочке (контрольная сумма), поэтому тест фиксирует строгость
    сравнения как контракт: подменяется только ответ сети."""
    from stand_transfers import valid_address
    deal = crypto_deal(walletId=wallet_id(REALTY))
    put_board({'deals': [deal], 'convs': [], 'wallets': []})
    variant = REALTY[:1] + REALTY[1].swapcase() + REALTY[2:]      # 'D' -> 'd': остаётся в алфавите base58
    assert variant != REALTY and variant.lower() == REALTY.lower()
    assert valid_address(variant, 'trc20'), 'вариант должен проходить проверку алфавита, иначе тест пустой'
    chain['to'] = variant
    r = client_for(make_user('operator')).post('/api/stand/payin/check',
                                                json={'dealId': 7, 'hash': HASH})
    assert r.status_code == 409, r.get_json()
    assert r.get_json()['warning']['actual'] == variant and r.get_json()['warning']['expected'] == REALTY
    assert board()[0]['deals'][0]['payinHashes'] == []


def test_new_sender_flag_known_vs_unknown(seeded, chain):
    deal = crypto_deal(walletId=wallet_id(REALTY))
    put_board({'deals': [deal], 'convs': [], 'wallets': []})
    chain['to'] = REALTY
    chain['from'] = 'TA4Y62o6YC2Zsck9rZVGTvqW1AQ7X9zTnj'   # нигде не встречался
    operator = client_for(make_user('operator'))
    r = operator.post('/api/stand/payin/check', json={'dealId': 7, 'hash': HASH})
    assert r.status_code == 200, r.get_json()
    assert r.get_json()['tx']['sourceKnown'] is False
    chain['from'] = LEGACY       # адрес из реестра кошельков — знакомый
    r = operator.post('/api/stand/payin/check', json={'dealId': 7, 'hash': 'b2' * 32})
    assert r.status_code == 200, r.get_json()
    assert r.get_json()['tx']['sourceKnown'] is True


def test_payin_observation_does_not_loosen_outgoing_verification():
    """verify_transfer без получателя допустим только для наблюдения прихода."""
    from stand_transfers import verify_transfer
    for kw in ({}, {'observe_recipient': False}):
        r = verify_transfer('c3' * 32, 'trc20', None, None, None, **kw)
        assert r['status'] == 'mismatch'
    r = verify_transfer('c3' * 32, 'trc20', 'T' + 'A' * 33, None, 10, observe_recipient=True)
    assert r['status'] == 'mismatch'


@pytest.mark.parametrize('mutation', ['delete_deal', 'rekey_deal'])
def test_state_put_cannot_delete_or_rekey_s14_deal_with_warning(seeded, chain, mutation):
    deal = crypto_deal(walletId=wallet_id(REALTY))
    put_board({'deals': [deal], 'convs': [], 'wallets': []})
    chain['to'] = EXCHANGE
    operator = client_for(make_user('operator'))
    operator.post('/api/stand/payin/check', json={'dealId': 7, 'hash': HASH})
    real = board()[0]['deals'][0]['recipientWarnings']
    assert real and real[0]['acknowledgedById'] is None
    snap = operator.get('/api/stand/state').get_json()
    forged = copy.deepcopy(snap['data'])
    if mutation == 'delete_deal':
        forged['deals'] = []
    else:
        forged['deals'][0]['id'] = 999
        forged['deals'][0].pop('recipientWarnings')
    checked_put(operator, snap['version'], forged)
    stored = board()[0]['deals']
    assert [d['id'] for d in stored] == [7], 'сделку с предупреждением нельзя удалить или переименовать'
    assert stored[0]['recipientWarnings'] == real
    assert stored[0]['payinHashes'] == []
