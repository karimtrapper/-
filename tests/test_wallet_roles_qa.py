"""Независимая QA-проверка реестра кошельков с ролями подписи (пункт 1 и далее).

Проверяет контракт ТЗ, а не реализацию: роли берутся из БД, а не из тела запроса,
политика кошельков не правится через публичный API, старые кошельки остаются.
Все данные синтетические, сеть закрыта фенсом.
"""
import json
import secrets

import pytest

import app as m


REALTY = 'TDuDeRiwrLLN3hnnA57G5yM6ibg58A6wZk'
EXCHANGE = 'TA6S3RBEY57jq8fXEVVsU6H9JZ18inenG4'
LEGACY = 'TKkeEVf2zySaWTLyX2qPwvi6kcdHRuPxkJ'
SIGNERS = {
    'operator': 'TAXgSzqBJzcstEkTBu4FJvEBH8SdxfV3QC',
    'findir': 'TDsLTB3uHKhTcB3hWRaKByg3pLtrMAHcgd',
    'teodor': 'TUzvaUjzRN5XLqDqbWB2VRKWQRtukXFYrN',
}
POLICY_FIELDS = ('purpose', 'limit_usd', 'initiator_roles', 'confirmer_roles',
                 'owner_can_alone', 'signer_addresses', 'not_for_new_deals')


@pytest.fixture
def stand(monkeypatch):
    monkeypatch.setattr(m, 'STAND_MODE', True)
    monkeypatch.setattr(m, '_stand_deliver_notes', lambda: [])
    # Нижний сетевой транспорт стенда в QA-тестах всегда «канал недоступен»: ни один
    # тест этого файла не должен даже пытаться достучаться наружу (POST /api/wallets
    # подтягивает баланс через stand_egress).
    import stand_egress
    monkeypatch.setattr(stand_egress, 'read_get', lambda *a, **k: (None, None, 'qa: сеть закрыта'))
    m._stand_migrate()
    return m


@pytest.fixture
def seeded(stand):
    from tests.qa_wallet_roles_helpers import db_snapshot, db_restore
    snap = db_snapshot()
    s = m.get_session()
    try:
        s.query(m.Wallet).delete()
        s.commit()
    finally:
        s.close()
    m._stand_seed_wallets()
    yield
    db_restore(snap)


def make_user(role):
    s = m.get_session()
    try:
        u = m.AdminUser(username=f'qa-{role}-{secrets.token_hex(4)}', role=role,
                        password_hash='unused', display_name=f'QA {role}')
        s.add(u)
        s.commit()
        return u.id
    finally:
        s.close()


def client_for(user_id):
    m.app.config['TESTING'] = True
    c = m.app.test_client()
    with c.session_transaction() as sess:
        sess['user_id'] = user_id
    return c


def wallet_row(address):
    s = m.get_session()
    try:
        w = s.query(m.Wallet).filter(m.Wallet.address == address).first()
        return w.to_dict() if w else None
    finally:
        s.close()


# ---------------------------------------------------------------- пункт 1

def test_seed_policy_wallets_exact_contract(seeded):
    realty, exchange = wallet_row(REALTY), wallet_row(EXCHANGE)
    assert realty['purpose'] == 'realty' and exchange['purpose'] == 'exchange'
    assert realty['limit_usd'] is None
    assert exchange['limit_usd'] == 10000
    assert realty['initiator_roles'] == ['operator', 'findir']
    assert realty['confirmer_roles'] == ['teodor']
    assert realty['owner_can_alone'] is True
    assert exchange['initiator_roles'] == ['operator']
    assert sorted(exchange['confirmer_roles']) == ['findir', 'teodor']
    # Изменено по новому ТЗ (wallet-handoff): владелец может отправить с обменника сам,
    # лимит $10 000 и согласование владельца выше лимита сохранены.
    assert exchange['owner_can_alone'] is True
    for w in (realty, exchange):
        assert w['signer_addresses'] == SIGNERS
        assert w['not_for_new_deals'] is False


def test_signer_cards_never_use_provider_tr68_addresses(seeded):
    s = m.get_session()
    try:
        for w in s.query(m.Wallet).all():
            signers = json.loads(w.signer_addresses or '{}')
            for role, addr in signers.items():
                assert not addr.startswith('TR68'), (w.address, role, addr)
                assert len(addr) == 34 and addr.startswith('T')
        # Изменено по новому ТЗ (wallet-handoff): Mfstr (TR68…) теперь сам кошелёк с политикой и
        # имеет карточки подписантов; его адрес по-прежнему не используется как адрес подписанта
        # (проверено в цикле выше), а оператор в его политике не участвует.
        mfstr = s.query(m.Wallet).filter(m.Wallet.address.startswith('TR68')).one()
        assert set(json.loads(mfstr.signer_addresses)) == {'findir', 'teodor'}
    finally:
        s.close()


def test_legacy_wallets_marked_not_for_new_deals_but_retained_and_unblocked(seeded):
    s = m.get_session()
    try:
        legacy = s.query(m.Wallet).filter(m.Wallet.address == LEGACY).one().to_dict()
        assert legacy['not_for_new_deals'] is True
        # не удалён и не заблокирован: активен, принимает оплату и мультисиг, как раньше
        assert legacy['active'] is True and legacy['accepts_payin'] is True
        assert legacy['is_multisig'] is True
        # политика подписи у старого кошелька не появляется: старый путь не меняется
        assert legacy['purpose'] is None and legacy['limit_usd'] is None
        assert legacy['initiator_roles'] == [] and legacy['confirmer_roles'] == []
        assert legacy['owner_can_alone'] is False and legacy['signer_addresses'] == {}
        others = [w for w in s.query(m.Wallet).all() if w.address not in m.POLICY_WALLET_ADDRESSES]
        assert others and all(w.not_for_new_deals and w.active for w in others)
    finally:
        s.close()


def test_seed_is_idempotent_for_policy_rows(seeded):
    before = wallet_row(REALTY), wallet_row(EXCHANGE)
    m._stand_seed_wallets()
    m._stand_seed_wallets()
    assert (wallet_row(REALTY), wallet_row(EXCHANGE)) == before
    s = m.get_session()
    try:
        assert s.query(m.Wallet).filter(m.Wallet.address.in_((REALTY, EXCHANGE))).count() == 2
    finally:
        s.close()


def test_wallet_added_after_first_seed_is_not_flagged_by_next_restart(seeded):
    """Пометка «не для новых сделок» — разовая миграция существующих кошельков.
    Кошелёк, заведённый админом после неё, не должен выпасть из выбора при рестарте."""
    new_addr = 'TA4Y62o6YC2Zsck9rZVGTvqW1AQ7X9zTnj'  # синтетический, не из сида
    db = m.get_session()
    try:
        db.add(m.Wallet(address=new_addr, blockchain='TRON', label='Новый после миграции',
                        accepts_payin=True, active=True))
        db.commit()
    finally:
        db.close()
    m._stand_seed_wallets()  # рестарт приложения
    assert wallet_row(new_addr)['not_for_new_deals'] is False


@pytest.mark.parametrize('role', ['admin', 'operator', 'findir'])
@pytest.mark.parametrize('field,value', [
    ('limit_usd', 1_000_000), ('limit_usd', None), ('purpose', 'realty'),
    ('initiator_roles', ['operator', 'manager']), ('confirmer_roles', []),
    ('owner_can_alone', True), ('signer_addresses', {'operator': 'T' + 'X' * 33}),
    ('not_for_new_deals', True),
])
def test_policy_cannot_be_rewritten_through_wallet_api(seeded, role, field, value):
    c = client_for(make_user(role))
    before = wallet_row(EXCHANGE)
    wid = before['id']
    r = c.patch(f'/api/wallets/{wid}', json={field: value})
    assert r.status_code in (400, 403), (field, r.status_code, r.get_json())
    assert wallet_row(EXCHANGE) == before
    r = c.post('/api/wallets', json={'address': EXCHANGE, field: value})
    assert r.status_code in (400, 403)
    assert wallet_row(EXCHANGE) == before


def test_policy_wallets_cannot_be_deleted_or_disabled(seeded):
    c = client_for(make_user('admin'))
    for address in (REALTY, EXCHANGE):
        before = wallet_row(address)
        assert c.delete(f'/api/wallets/{before["id"]}').status_code in (400, 403)
        r = c.patch(f'/api/wallets/{before["id"]}', json={'active': False})
        assert r.status_code in (400, 403)
        assert wallet_row(address) == before


@pytest.mark.parametrize('role', ['manager', 'teodor', 'buyer'])
def test_non_editing_roles_cannot_touch_wallet_registry(seeded, role):
    c = client_for(make_user(role))
    before = wallet_row(EXCHANGE)
    r = c.patch(f'/api/wallets/{before["id"]}', json={'label': 'hack'})
    assert r.status_code == 403
    assert wallet_row(EXCHANGE) == before
