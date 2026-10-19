"""QA пункта 6: CRM выплата с кошелька «Груша Обменник» — лимит 10 000 USDT.

Сервер сам решает, нужно ли владельческое одобрение: по кошельку реестра и сумме.
Одобрение — строгий bool от аутентифицированного finдира/владельца, привязанное к сумме
и ордеру. Роли берутся из БД; тело запроса и сессия их не задают.
"""
import json
import secrets

import pytest

import app as m
from tests.qa_wallet_roles_helpers import make_user, client_for
from tests.test_wallet_roles_qa import REALTY, EXCHANGE, LEGACY

MSG = 'Для отправки свыше 10 000 USDT требуется подтверждение владельца'


@pytest.fixture
def world(monkeypatch):
    from tests.qa_wallet_roles_helpers import db_snapshot, db_restore
    monkeypatch.setattr(m, 'STAND_MODE', False)
    snap = db_snapshot()
    db = m.get_session()
    try:
        db.query(m.Wallet).delete()
        db.commit()
    finally:
        db.close()
    m._stand_seed_wallets()
    yield
    db_restore(snap)


def wid(address):
    db = m.get_session()
    try:
        return db.query(m.Wallet).filter_by(address=address).one().id
    finally:
        db.close()


def body(name=None, amount=5000, wallet=EXCHANGE, **extra):
    data = {'client_name': name or f'QA-{secrets.token_hex(4)}', 'status': 'pending',
            'payin_method': 'sber_reqs', 'payin_amount_rub': 500000.0, 'payin_amount_usdt': 5200.0,
            'payout_method': 'transfer', 'payout_source': 'binance', 'payout_amount_thb': 170000.0,
            'payout_amount_usdt': amount, 'skip_sync': True}
    if wallet is not None:
        data['payout_wallet_id'] = wid(wallet)
    data.update(extra)
    return data


def deal_row(name):
    db = m.get_session()
    try:
        d = db.query(m.Deal).filter_by(client_name=name).first()
        return d.to_dict() if d else None
    finally:
        db.close()


def count(name):
    db = m.get_session()
    try:
        return db.query(m.Deal).filter_by(client_name=name).count()
    finally:
        db.close()


def create(role, **kw):
    uid = make_user(role)
    data = body(**kw)
    r = client_for(uid).post('/api/deals', json=data)
    return r, data['client_name'], uid


# -------------------------------------------------------------- порог на создании

@pytest.mark.parametrize('amount', [1, 5000, 9999.99, 10000, 10000.0])
def test_up_to_limit_inclusive_needs_no_approval(world, amount):
    r, name, _ = create('operator', amount=amount)
    assert r.status_code in (200, 201), r.get_json()
    d = deal_row(name)
    assert d['payout_wallet_id'] == wid(EXCHANGE) and d['payout_owner_approved'] is False


@pytest.mark.parametrize('amount', [10000.01, 10000.5, 15000, 1_000_000])
@pytest.mark.parametrize('role', ['operator', 'manager', 'admin', 'findir', 'teodor'])
def test_over_limit_without_flag_is_400_and_nothing_is_saved(world, amount, role):
    r, name, _ = create(role, amount=amount)
    assert r.status_code == 400, r.get_json()
    assert MSG in r.get_json()['error']
    assert count(name) == 0


@pytest.mark.parametrize('role', ['findir', 'teodor'])
def test_over_limit_with_flag_from_owner_or_financier_passes_and_is_stamped(world, role):
    r, name, uid = create(role, amount=15000, payout_owner_approved=True)
    assert r.status_code in (200, 201), r.get_json()
    d = deal_row(name)
    assert d['payout_owner_approved'] is True
    marker = d['payout_owner_approval']
    assert marker['byId'] == uid and marker['role'] == role
    assert marker['walletId'] == wid(EXCHANGE) and marker['amount'] == '15000'


@pytest.mark.parametrize('role', ['operator', 'manager', 'admin', 'buyer'])
def test_over_limit_flag_from_other_roles_is_rejected(world, role):
    r, name, _ = create(role, amount=15000, payout_owner_approved=True)
    assert r.status_code == 403, r.get_json()
    assert count(name) == 0


def test_unauthenticated_cannot_create(world):
    r = m.app.test_client().post('/api/deals', json=body(amount=15000, payout_owner_approved=True))
    assert r.status_code in (401, 403)


@pytest.mark.parametrize('bad', ['true', 'True', 'false', 'yes', '1', 1, 0, 2, [], {}, [True], None])
@pytest.mark.parametrize('role', ['findir', 'teodor'])
def test_approval_flag_must_be_strict_boolean(world, role, bad):
    r, name, _ = create(role, amount=15000, payout_owner_approved=bad)
    assert r.status_code == 400, (bad, r.get_json())
    assert count(name) == 0


def test_approval_marker_in_body_is_not_trusted(world):
    forged = {'byId': 1, 'byName': 'x', 'role': 'teodor', 'at': 1, 'walletId': wid(EXCHANGE),
              'amount': '15000', 'fingerprint': 'f'}
    r, name, _ = create('operator', amount=15000, payout_owner_approval=forged,
                        payout_owner_approved=False)
    assert r.status_code == 400 and count(name) == 0


# ------------------------------------------------- суммы: закрытый отказ

@pytest.mark.parametrize('amount', [None, '', 'NaN', 'nan', 'inf', '-inf', 'Infinity', -5, 0, 'abc', '1e999'])
def test_invalid_or_missing_amount_on_exchange_wallet_fails_closed(world, amount):
    r, name, _ = create('operator', amount=amount)
    assert r.status_code in (400, 422), (amount, r.get_json())
    assert count(name) == 0


def test_missing_amount_key_on_exchange_wallet_fails_closed(world):
    uid = make_user('operator')
    data = body()
    data.pop('payout_amount_usdt')
    r = client_for(uid).post('/api/deals', json=data)
    assert r.status_code in (400, 422) and count(data['client_name']) == 0


# ----------------------------------------------------- кошелёк по умолчанию

def test_new_exchange_deal_without_wallet_defaults_to_exchange_wallet_and_limit(world):
    r, name, _ = create('operator', amount=15000, wallet=None)
    assert r.status_code == 400 and count(name) == 0, 'лимит применяется и к умолчанию'
    r, name, _ = create('operator', amount=5000, wallet=None)
    assert r.status_code in (200, 201)
    assert deal_row(name)['payout_wallet_id'] == wid(EXCHANGE)


def test_public_skip_sync_flag_cannot_suppress_default_wallet_gate(world):
    for flag in (True, 'true', 1):
        r, name, _ = create('operator', amount=15000, wallet=None, skip_sync=flag)
        assert r.status_code == 400, (flag, r.get_json())
        assert count(name) == 0


# ------------------------------------------------------- кошелёк-идентификатор

@pytest.mark.parametrize('wallet_id', ['abc', '1; DROP', {'a': 1}, [1], 99999999, -3, 1.5, True])
def test_invalid_wallet_id_never_bypasses_gate(world, wallet_id):
    uid = make_user('operator')
    data = body(amount=15000, wallet=None, payout_wallet_id=wallet_id)
    r = client_for(uid).post('/api/deals', json=data)
    assert r.status_code in (400, 404, 409, 422), (wallet_id, r.status_code, r.get_json())
    assert count(data['client_name']) == 0


# ------------------------------------------------------ легаси остаётся прежним

def test_legacy_wallet_is_refused_for_new_deals_but_existing_deals_keep_old_rules(world):
    r, name, _ = create('operator', amount=5000, wallet=LEGACY)
    assert r.status_code == 400 and 'существующих сделок' in r.get_json()['error']
    assert count(name) == 0
    db = m.get_session()
    try:
        d = m.Deal(client_name='legacy-old', deal_type=m.DealType.PAY_IN,
                   payout_source=m.PayOutSource.BINANCE, payout_wallet_id=wid(LEGACY),
                   payout_amount_usdt=5000.0)
        db.add(d)
        db.commit()
        did = d.id
    finally:
        db.close()
    op = client_for(make_user('operator'))
    r = op.put(f'/api/deals/{did}', json={'payout_amount_usdt': 50000.0})
    assert r.status_code == 200, r.get_json()          # у легаси-кошелька нового лимита нет
    assert deal_row('legacy-old')['payout_owner_approved'] is False


def test_realty_wallet_has_no_crm_amount_limit(world):
    r, name, _ = create('operator', amount=50000, wallet=REALTY)
    assert r.status_code in (200, 201), r.get_json()


def test_legacy_deal_with_null_amount_serialises_and_lists(world):
    db = m.get_session()
    try:
        d = m.Deal(client_name='legacy-null', deal_type=m.DealType.PAY_IN,
                   payout_source=m.PayOutSource.BINANCE, payout_wallet_id=wid(EXCHANGE),
                   payout_amount_usdt=None)
        db.add(d)
        db.commit()
        did = d.id
    finally:
        db.close()
    admin = client_for(make_user('admin'))
    assert deal_row('legacy-null')['payout_owner_approved'] is False
    assert admin.get(f'/api/deals/{did}').status_code == 200
    assert admin.get('/api/deals').status_code == 200


def test_legacy_deal_over_limit_is_readable_and_other_fields_editable(world):
    """Старая запись с суммой >10000 не ломается чтением; редактирование несвязанных полей
    не требует новой подписи, а изменение суммы/кошелька требует."""
    db = m.get_session()
    try:
        d = m.Deal(client_name='legacy-big', deal_type=m.DealType.PAY_IN,
                   payout_source=m.PayOutSource.BINANCE, payout_wallet_id=wid(EXCHANGE),
                   payout_amount_usdt=20000.0)
        db.add(d)
        db.commit()
        did = d.id
    finally:
        db.close()
    op = client_for(make_user('operator'))
    assert op.get(f'/api/deals/{did}').status_code == 200
    r = op.put(f'/api/deals/{did}', json={'payout_amount_usdt': 21000.0})
    assert r.status_code == 400 and MSG in r.get_json()['error']
    assert deal_row('legacy-big')['payout_amount_usdt'] == 20000.0


# ------------------------------------------------------- обновление и выплата

def make_deal(role='operator', **kw):
    r, name, uid = create(role, **kw)
    assert r.status_code in (200, 201), r.get_json()
    return r.get_json()['deal']['id'] if 'deal' in r.get_json() else deal_row(name)['id'], name


def test_update_cannot_raise_amount_over_limit_without_flag(world):
    did, name = make_deal(amount=5000)
    op = client_for(make_user('operator'))
    r = op.put(f'/api/deals/{did}', json={'payout_amount_usdt': 15000})
    assert r.status_code == 400 and MSG in r.get_json()['error']
    assert deal_row(name)['payout_amount_usdt'] == 5000
    r = op.put(f'/api/deals/{did}', json={'payout_amount_usdt': 15000, 'payout_owner_approved': True})
    assert r.status_code == 403
    assert deal_row(name)['payout_amount_usdt'] == 5000


def test_update_with_owner_flag_passes_then_changes_invalidate_it(world):
    did, name = make_deal(amount=5000)
    findir = client_for(make_user('findir'))
    r = findir.put(f'/api/deals/{did}', json={'payout_amount_usdt': 15000, 'payout_owner_approved': True})
    assert r.status_code in (200, 201), r.get_json()
    assert deal_row(name)['payout_owner_approved'] is True
    op = client_for(make_user('operator'))
    # одобренная сумма меняется оператором -> одобрение теряет силу, нужен новый флаг
    r = op.put(f'/api/deals/{did}', json={'payout_amount_usdt': 16000})
    assert r.status_code == 400 and MSG in r.get_json()['error']
    assert deal_row(name)['payout_amount_usdt'] == 15000 and deal_row(name)['payout_owner_approved'] is True
    # другой ордер (хеш выплаты) тоже не наследует одобрение
    r = op.put(f'/api/deals/{did}', json={'payout_tx_hash': 'ab' * 32})
    assert r.status_code == 400 or deal_row(name)['payout_owner_approved'] is False
    # неизменённые поля с тем же ордером не ломают одобрение
    assert op.put(f'/api/deals/{did}', json={'notes': 'просто заметка'}).status_code in (200, 400)


@pytest.mark.parametrize('junk', ['false', 'False', 'true', 0, 1, None, [], {}])
def test_existing_approved_record_edit_with_non_bool_flag_keeps_state(world, junk):
    did, name = make_deal('findir', amount=15000, payout_owner_approved=True)
    before = deal_row(name)
    op = client_for(make_user('operator'))
    r = op.put(f'/api/deals/{did}', json={'payout_owner_approved': junk, 'notes': 'edit'})
    assert r.status_code in (200, 400), r.get_json()
    after = deal_row(name)
    assert after['payout_amount_usdt'] == before['payout_amount_usdt']
    assert after['payout_wallet_id'] == before['payout_wallet_id']
    assert after['payout_owner_approved'] is True, 'нестрогое значение не снимает и не меняет одобрение'


def test_explicit_false_revokes_approval(world):
    did, name = make_deal('findir', amount=15000, payout_owner_approved=True)
    op = client_for(make_user('operator'))
    r = op.put(f'/api/deals/{did}', json={'payout_owner_approved': False})
    assert r.status_code == 400, 'после отзыва сумма >10000 снова без одобрения'
    assert deal_row(name)['payout_owner_approved'] is True or r.status_code == 400


def test_cannot_escape_limit_by_moving_deal_to_other_wallet_or_back(world):
    uid = make_user('findir')
    d = body(amount=15000, payout_owner_approved=True)
    r = client_for(uid).post('/api/deals', json=d)
    assert r.status_code in (200, 201), r.get_json()
    did = deal_row(d['client_name'])['id']
    op = client_for(make_user('operator'))
    r = op.put(f'/api/deals/{did}', json={'payout_wallet_id': wid(LEGACY)})
    assert r.status_code in (400, 403, 409)
    assert deal_row(d['client_name'])['payout_wallet_id'] == wid(EXCHANGE)
    # обратный путь: старая выплата >10000 с легаси-кошелька не уходит на обменный без одобрения
    db = m.get_session()
    try:
        old = m.Deal(client_name='legacy-move', deal_type=m.DealType.PAY_IN,
                     payout_source=m.PayOutSource.BINANCE, payout_wallet_id=wid(LEGACY),
                     payout_amount_usdt=15000.0)
        db.add(old)
        db.commit()
        did2 = old.id
    finally:
        db.close()
    r = op.put(f'/api/deals/{did2}', json={'payout_wallet_id': wid(EXCHANGE)})
    assert r.status_code == 400 and MSG in r.get_json()['error']
    assert deal_row('legacy-move')['payout_wallet_id'] == wid(LEGACY)


def test_user_cannot_set_approval_through_generic_fields(world):
    did, name = make_deal(amount=5000)
    op = client_for(make_user('operator'))
    op.put(f'/api/deals/{did}', json={'payout_amount_usdt': 15000, 'payout_owner_approval': json.dumps({
        'byId': 1, 'walletId': wid(EXCHANGE), 'amount': '15000', 'fingerprint': 'x'})})
    assert deal_row(name)['payout_amount_usdt'] == 5000
    assert deal_row(name)['payout_owner_approved'] is False


# ------------------- обходы через payout_tx_hashes и подтверждение Доверки

DEST_ADDR = 'TQgQCBXkewuW4RoieDKFP9Ko2SopBh8jso'


def part(amount, from_address, tx='cd' * 32):
    return {'hash': tx, 'amount_usdt': amount, 'from_address': from_address,
            'to_address': DEST_ADDR, 'network': 'TRC-20'}


def test_update_with_transfer_parts_cannot_move_policy_deal_to_legacy_wallet(world):
    did, name = make_deal(amount=5000)
    op = client_for(make_user('operator'))
    r = op.put(f'/api/deals/{did}', json={'payout_tx_hashes': [part(15000, LEGACY)]})
    after = deal_row(name)
    assert after['payout_wallet_id'] == wid(EXCHANGE), 'адрес отправителя не должен подменять кошелёк'
    assert r.status_code == 400 and 'источник выплаты менять нельзя' in r.get_json()['error']
    assert after['payout_amount_usdt'] == 5000


def test_update_with_transfer_parts_over_limit_needs_approval(world):
    did, name = make_deal(amount=5000)
    op = client_for(make_user('operator'))
    r = op.put(f'/api/deals/{did}', json={'payout_tx_hashes': [part(15000, EXCHANGE)]})
    after = deal_row(name)
    assert r.status_code == 400 and MSG in r.get_json()['error']
    assert after['payout_amount_usdt'] == 5000, 'сумма из переводов > лимита без одобрения не записана'


def test_new_deal_with_parts_only_cannot_bypass_wallet_gates(world):
    uid = make_user('operator')
    # получатель — обменный кошелёк, сумма > лимита, кошелёк явно не указан
    d = body(amount=None, wallet=None, payout_tx_hashes=[part(15000, EXCHANGE)])
    d.pop('payout_amount_usdt')
    r = client_for(uid).post('/api/deals', json=d)
    row = deal_row(d['client_name'])
    assert r.status_code == 400 and row is None, r.get_json()
    # отправитель — легаси-кошелёк «не для новых сделок»
    d = body(amount=5000, wallet=None, payout_tx_hashes=[part(5000, LEGACY)])
    r = client_for(uid).post('/api/deals', json=d)
    assert r.status_code == 400
    assert any(t in json.dumps(r.get_json(), ensure_ascii=False)
               for t in ('существующих сделок', 'источник выплаты менять нельзя')), r.get_json()
    assert deal_row(d['client_name']) is None


def make_pending(wallet, amount, name):
    db = m.get_session()
    try:
        d = m.Deal(client_name=name, deal_type=m.DealType.PAY_IN, status=m.DealStatus.PENDING,
                   payout_source=m.PayOutSource.BINANCE, payout_wallet_id=wid(wallet),
                   payout_amount_usdt=amount)
        db.add(d)
        db.commit()
        return d.id
    finally:
        db.close()


def expense_ops(did):
    db = m.get_session()
    try:
        return db.query(m.WalletOperation).filter_by(deal_id=did, type='expense').count()
    finally:
        db.close()


def test_doverka_confirm_cannot_finalize_over_limit_policy_deal_without_approval(world):
    did = make_pending(EXCHANGE, 15000.0, 'dov-over')
    r = client_for(make_user('operator')).post(f'/api/doverka/confirm/{did}',
                                               json={'payout_hash': 'ef' * 32})
    assert r.status_code == 400 and MSG in r.get_json()['error']
    assert deal_row('dov-over')['status'] == 'pending' and expense_ops(did) == 0


def test_doverka_confirm_works_for_approved_under_limit_and_legacy(world):
    # одобренная сделка > лимита
    r, name, _ = create('findir', amount=15000, payout_owner_approved=True)
    assert r.status_code in (200, 201)
    did = deal_row(name)['id']
    ok = client_for(make_user('operator')).post(f'/api/doverka/confirm/{did}',
                                                json={'payout_hash': '01' * 32})
    assert ok.status_code == 200, ok.get_json()
    assert deal_row(name)['status'] == 'completed' and expense_ops(did) == 1
    # до лимита — как раньше
    under = make_pending(EXCHANGE, 9000.0, 'dov-under')
    assert client_for(make_user('operator')).post(
        f'/api/doverka/confirm/{under}', json={'payout_hash': '02' * 32}).status_code == 200
    assert expense_ops(under) == 1
    # легаси-кошелёк: старое поведение без нового лимита
    legacy = make_pending(LEGACY, 50000.0, 'dov-legacy')
    assert client_for(make_user('operator')).post(
        f'/api/doverka/confirm/{legacy}', json={'payout_hash': '03' * 32}).status_code == 200
    assert deal_row('dov-legacy')['status'] == 'completed' and expense_ops(legacy) == 1


def test_doverka_confirm_refuses_when_approved_amount_changed_underneath(world):
    r, name, _ = create('findir', amount=15000, payout_owner_approved=True)
    did = deal_row(name)['id']
    ops_before = expense_ops(did)          # расход создан при создании одобренной сделки
    db = m.get_session()
    try:
        db.query(m.Deal).filter_by(id=did).one().payout_amount_usdt = 16000.0
        db.commit()
    finally:
        db.close()
    r = client_for(make_user('operator')).post(f'/api/doverka/confirm/{did}',
                                               json={'payout_hash': '04' * 32})
    assert r.status_code == 400 and MSG in r.get_json()['error']
    assert deal_row(name)['status'] == 'pending' and expense_ops(did) == ops_before


# ---------------------------------------- кошелёк получения USDT (payin_wallet_id)

def crypto_body(**extra):
    d = body(amount=5000)
    d.update(payin_method='crypto_direct', payin_amount_usdt=5200.0)
    d.pop('payin_amount_rub', None)
    d.update(extra)
    return d


def test_crypto_payin_defaults_to_exchange_wallet_for_exchange_deal(world):
    d = crypto_body()
    r = client_for(make_user('operator')).post('/api/deals', json=d)
    assert r.status_code in (200, 201), r.get_json()
    assert deal_row(d['client_name'])['payin_wallet_id'] == wid(EXCHANGE)


def test_crypto_payin_explicit_registry_wallet_is_kept(world):
    d = crypto_body(payin_wallet_id=wid(REALTY))
    r = client_for(make_user('operator')).post('/api/deals', json=d)
    assert r.status_code in (200, 201), r.get_json()
    assert deal_row(d['client_name'])['payin_wallet_id'] == wid(REALTY)


@pytest.mark.parametrize('bad', ['abc', 99999999, {'a': 1}, [1], -1, 1.5, True])
def test_crypto_payin_invalid_wallet_is_rejected(world, bad):
    d = crypto_body(payin_wallet_id=bad)
    r = client_for(make_user('operator')).post('/api/deals', json=d)
    assert r.status_code == 400, (bad, r.get_json())
    assert count(d['client_name']) == 0


def test_crypto_payin_legacy_wallet_refused_for_new_deal(world):
    d = crypto_body(payin_wallet_id=wid(LEGACY))
    r = client_for(make_user('operator')).post('/api/deals', json=d)
    assert r.status_code == 400 and 'существующих сделок' in r.get_json()['error']


def test_crypto_payin_inactive_wallet_refused(world):
    db = m.get_session()
    try:
        db.query(m.Wallet).filter_by(id=wid(REALTY)).one().active = False
        db.commit()
    finally:
        db.close()
    d = crypto_body(payin_wallet_id=wid(REALTY))
    assert client_for(make_user('operator')).post('/api/deals', json=d).status_code == 400


def test_non_crypto_payin_never_keeps_a_wallet(world):
    d = body(amount=5000, payin_wallet_id=wid(REALTY))          # sber_reqs
    r = client_for(make_user('operator')).post('/api/deals', json=d)
    assert r.status_code in (200, 201), r.get_json()
    assert deal_row(d['client_name'])['payin_wallet_id'] is None


def test_existing_legacy_payin_wallet_stays_and_cannot_be_swapped_to_another_legacy(world):
    db = m.get_session()
    try:
        old = m.Deal(client_name='legacy-payin', deal_type=m.DealType.PAY_IN,
                     payin_method=m.PayInMethod.CRYPTO_DIRECT, payin_wallet_id=wid(LEGACY))
        db.add(old)
        db.commit()
        did = old.id
    finally:
        db.close()
    op = client_for(make_user('operator'))
    assert op.put(f'/api/deals/{did}', json={'payin_wallet_id': wid(LEGACY), 'notes': 'x'}).status_code == 200
    assert deal_row('legacy-payin')['payin_wallet_id'] == wid(LEGACY)
    other_legacy = wid('TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn')
    r = op.put(f'/api/deals/{did}', json={'payin_wallet_id': other_legacy})
    assert r.status_code == 400
    assert op.put(f'/api/deals/{did}', json={'payin_wallet_id': wid(EXCHANGE)}).status_code == 200
    assert deal_row('legacy-payin')['payin_wallet_id'] == wid(EXCHANGE)


def test_verified_payin_wallet_cannot_be_changed(world):
    db = m.get_session()
    try:
        old = m.Deal(client_name='verified-payin', deal_type=m.DealType.PAY_IN,
                     payin_method=m.PayInMethod.CRYPTO_DIRECT, payin_wallet_id=wid(EXCHANGE),
                     payin_tx_verified=True)
        db.add(old)
        db.commit()
        did = old.id
    finally:
        db.close()
    r = client_for(make_user('operator')).put(f'/api/deals/{did}', json={'payin_wallet_id': wid(REALTY)})
    assert r.status_code == 409
    assert deal_row('verified-payin')['payin_wallet_id'] == wid(EXCHANGE)


# ------ входящий хеш в CRM: ожидаемый кошелёк получения против фактического получателя

TXH = '7a' * 32


@pytest.fixture
def chain_to(monkeypatch):
    """Нижний транспорт: только ответ verify_transfer. Сначала проверка с ожидаемым получателем,
    при расхождении — наблюдение фактического получателя (как в приложении). Сети нет."""
    box = {'to': None, 'amount': 5200.0, 'calls': []}

    def fake(ref, network, sender, receiver, amount, **kw):
        box['calls'].append((receiver, kw.get('observe_recipient', False)))
        if receiver is not None:
            if box['to'] == receiver:
                return {'status': 'confirmed', 'verifiedAmount': box['amount'], 'verifiedAt': 'now',
                        'timestampMs': 1700000001000, 'from': None, 'to': receiver}
            return {'status': 'mismatch', 'checkError': 'адрес не совпал'}
        if kw.get('observe_recipient') and box['to']:
            return {'status': 'confirmed', 'verifiedAmount': box['amount'], 'verifiedAt': 'now',
                    'timestampMs': 1700000001000, 'from': None, 'to': box['to']}
        return {'status': 'mismatch', 'checkError': 'получатель не установлен'}
    monkeypatch.setattr(m, 'verify_transfer', fake)
    monkeypatch.setattr(m, '_tron_tx_usdt_amount', lambda h: box['amount'])
    return box


def payin_uses():
    db = m.get_session()
    try:
        return db.query(m.PayinTxUse).join(m.PayinTx).filter(m.PayinTx.tx_hash == TXH).count()
    finally:
        db.close()


def test_incoming_hash_to_expected_wallet_is_accepted(world, chain_to):
    chain_to['to'] = EXCHANGE
    d = crypto_body(payin_wallet_id=wid(EXCHANGE),
                    payin_tx_hashes=[{'hash': TXH, 'network': 'TRC-20', 'amount_usdt': 5200.0}])
    r = client_for(make_user('operator')).post('/api/deals', json=d)
    assert r.status_code in (200, 201), r.get_json()
    assert payin_uses() == 1


def test_incoming_hash_to_other_wallet_is_not_silently_credited(world, chain_to):
    chain_to['to'] = REALTY       # деньги пришли на соседний кошелёк компании
    d = crypto_body(payin_wallet_id=wid(EXCHANGE),
                    payin_tx_hashes=[{'hash': TXH, 'network': 'TRC-20', 'amount_usdt': 5200.0}])
    r = client_for(make_user('operator')).post('/api/deals', json=d)
    body_ = r.get_json()
    assert r.status_code == 409 and body_['requires_confirmation'] is True, body_
    assert body_['expected_recipient'] == EXCHANGE and body_['actual_recipient'] == REALTY
    assert count(d['client_name']) == 0 and payin_uses() == 0
    # завершение: оператор выбирает фактический зарегистрированный кошелёк и повторяет
    d['payin_wallet_id'] = wid(REALTY)
    ok = client_for(make_user('operator')).post('/api/deals', json=d)
    assert ok.status_code in (200, 201), ok.get_json()
    assert payin_uses() == 1 and deal_row(d['client_name'])['payin_wallet_id'] == wid(REALTY)


def test_incoming_hash_with_unconfirmed_or_foreign_recipient_is_refused(world, chain_to, monkeypatch):
    chain_to['to'] = 'TA4Y62o6YC2Zsck9rZVGTvqW1AQ7X9zTnj'     # получатель не из реестра
    d = crypto_body(payin_wallet_id=wid(EXCHANGE),
                    payin_tx_hashes=[{'hash': TXH, 'network': 'TRC-20', 'amount_usdt': 5200.0}])
    r = client_for(make_user('operator')).post('/api/deals', json=d)
    assert r.status_code in (409, 422), r.get_json()
    assert count(d['client_name']) == 0 and payin_uses() == 0


def test_legacy_deal_without_expected_wallet_keeps_old_hash_behaviour(world, chain_to):
    chain_to['to'] = REALTY
    db = m.get_session()
    try:
        old = m.Deal(client_name='legacy-nowallet', deal_type=m.DealType.PAY_IN,
                     payin_method=m.PayInMethod.CRYPTO_DIRECT, payin_wallet_id=None)
        db.add(old)
        db.commit()
        did = old.id
    finally:
        db.close()
    r = client_for(make_user('operator')).put(f'/api/deals/{did}', json={
        'payin_tx_hashes': [{'hash': TXH, 'network': 'TRC-20', 'amount_usdt': 5200.0}]})
    assert r.status_code == 200, r.get_json()
    assert payin_uses() == 1
