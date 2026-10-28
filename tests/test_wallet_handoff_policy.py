"""Политика кошельков: явные роли «Заводит»/«Подписывает», веса как проверка, сид из 6 адресов,
API кошелька (обязательные роли, только admin, журнал), миграция колонок.

Все данные синтетические, сеть закрыта фенсом.
"""
import itertools
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

import app as m
import wallet_policy as wp
from tests.qa_wallet_roles_helpers import make_user, client_for
from tests.test_wallet_roles_qa import LEGACY, seeded, stand, wallet_row  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]

REALTY = 'TDuDeRiwrLLN3hnnA57G5yM6ibg58A6wZk'
PROPERTY = 'TAGufCVNFBLh6NiEGL8iaQ4F9PPnftcgBk'
EXCHANGE = 'TA6S3RBEY57jq8fXEVVsU6H9JZ18inenG4'
MFSTR = 'TR68DHoj71Nz4FoTvqnBFQK2Fc6NkEK6nQ'
CLIENT99 = 'TQPv1GETKVjSWZymdMu5WbSSeS6JhL2KHt'
MARTRUST = 'TUXAF8TNuQ5FTduffBGjqz9RjfensGbYcJ'
SIX = [REALTY, PROPERTY, EXCHANGE, MFSTR, CLIENT99, MARTRUST]
NEW_ADDR = 'TQgQCBXkewuW4RoieDKFP9Ko2SopBh8jso'
NEW_ADDR2 = 'TA4Y62o6YC2Zsck9rZVGTvqW1AQ7X9zTnj'

# Ожидаемое из ТЗ: какие одиночки и пары ролей набирают порог (по весам).
EXPECTED_WEIGHTS = {
    REALTY: ({'operator': 1, 'findir': 1, 'teodor': 3}, 3, 'realty',
             {('teodor',), ('operator', 'teodor'), ('findir', 'teodor')}),
    PROPERTY: ({'operator': 1, 'findir': 1, 'teodor': 2}, 2, 'realty_small',
               {('teodor',), ('operator', 'findir'), ('operator', 'teodor'), ('findir', 'teodor')}),
    EXCHANGE: ({'operator': 1, 'findir': 1, 'teodor': 2}, 2, 'exchange',
               {('teodor',), ('operator', 'findir'), ('operator', 'teodor'), ('findir', 'teodor')}),
    # Роль без веса не участвует: пара с ней набирает порог только за счёт владельца.
    MFSTR: ({'findir': 1, 'teodor': 2}, 2, 'provider',
            {('teodor',), ('findir', 'teodor'), ('operator', 'teodor')}),
    CLIENT99: ({'operator': 1, 'teodor': 2}, 2, 'client_funds',
               {('teodor',), ('operator', 'teodor'), ('findir', 'teodor')}),
    MARTRUST: ({'operator': 1, 'teodor': 2}, 2, 'martrust',
               {('teodor',), ('operator', 'teodor'), ('findir', 'teodor')}),
}
EXPECTED_ROLES = {
    REALTY: (['operator', 'findir'], ['teodor']),
    PROPERTY: (['operator'], ['findir', 'teodor']),
    EXCHANGE: (['operator'], ['findir', 'teodor']),
    MFSTR: (['findir'], ['teodor']),
    CLIENT99: (['operator'], ['teodor']),
    MARTRUST: (['operator'], ['teodor']),
}
ROLES = ('operator', 'findir', 'teodor')


# --------------------------------------------------------------- чистые функции

@pytest.mark.parametrize('address', SIX)
def test_weights_table_singles_and_pairs_match_spec(address):
    weights, threshold, _, ok = EXPECTED_WEIGHTS[address]
    for size in (1, 2):
        for combo in itertools.combinations(ROLES, size):
            assert wp.can_complete(weights, threshold, combo) == (combo in ok), (address, combo)


def test_can_complete_counts_distinct_roles_and_ignores_zero_weights():
    assert wp.can_complete({'operator': 1, 'teodor': 2}, 2, ['operator', 'operator']) is False
    assert wp.can_complete({'operator': 1, 'teodor': 2}, 2, ['teodor', 'teodor']) is True
    assert wp.can_complete({'operator': 0, 'teodor': 2}, 3, ['operator', 'teodor']) is False
    assert wp.can_complete({'teodor': 2}, 2, ['findir']) is False
    assert wp.can_complete({'teodor': 2}, 0, ['teodor']) is False
    assert wp.can_complete({'teodor': True}, 1, ['teodor']) is False


@pytest.mark.parametrize('address', SIX)
def test_seed_policy_is_consistent_with_weights(address):
    policy = m.POLICY_WALLET_SEED[address]
    weights, threshold, purpose, _ = EXPECTED_WEIGHTS[address]
    initiators, signers = EXPECTED_ROLES[address]
    assert policy['signer_weights'] == weights and policy['threshold'] == threshold
    assert policy['purpose'] == purpose
    assert policy['initiator_roles'] == initiators and policy['confirmer_roles'] == signers
    assert policy['owner_can_alone'] is True
    for init, sign in itertools.product(initiators, signers):
        if init != sign:
            assert wp.can_complete(weights, threshold, [init, sign]), (address, init, sign)
    assert wp.can_complete(weights, threshold, ['teodor'])
    assert wp.consistency_problems(initiators, signers, True, weights, threshold) == []
    assert m._policy_seed_problems() == {}


def test_consistency_detects_pair_below_threshold_and_weak_owner():
    # Недвижимость: оператор + финансист = 2 < 3
    assert wp.consistency_problems(['operator'], ['findir'], False,
                                   {'operator': 1, 'findir': 1, 'teodor': 3}, 3)
    # владелец один при весе ниже порога
    assert wp.consistency_problems(['operator'], ['teodor'], True,
                                   {'operator': 1, 'teodor': 2}, 3)
    # весов нет (новый кошелёк админа) — проверка пропускается
    assert wp.consistency_problems(['operator'], ['findir'], True, None, None) == []
    assert wp.consistency_problems(['operator'], ['findir'], True, {}, None) == []


@pytest.mark.parametrize('value, ok', [
    (['operator'], True), (['operator', 'teodor'], True), ([], False),
    (['operator', 'findir', 'teodor'], False), (['operator', 'operator'], False),
    (['manager'], False), ('operator', False), (None, False), ([1], False), (['admin', 'teodor'], False),
])
def test_validate_roles(value, ok):
    result, error = wp.validate_roles(value, 'Заводит')
    assert (error is None) == ok
    assert (result == value) if ok else result is None


def test_role_chain_helpers():
    assert wp.initial_role(['findir', 'operator']) == 'findir'
    assert wp.initial_role([]) is None
    # передача «завести»: роли из «Заводит» + владелец, если может сам; без текущей
    assert wp.initiate_targets(['operator', 'findir'], True, 'operator') == ['findir', 'teodor']
    assert wp.initiate_targets(['operator'], True, 'operator') == ['teodor']
    assert wp.initiate_targets(['operator'], False, 'operator') == []
    assert wp.initiate_targets(['findir'], True, None) == ['findir', 'teodor']
    # подпись: первая из «Подписывает», не равная инициатору; переназначение — без инициатора и текущей
    assert wp.default_sign_role(['findir', 'teodor'], 'operator') == 'findir'
    assert wp.default_sign_role(['findir', 'teodor'], 'findir') == 'teodor'
    assert wp.default_sign_role(['findir'], 'findir') is None
    assert wp.sign_targets(['findir', 'teodor'], 'operator', 'findir') == ['teodor']
    assert wp.sign_targets(['findir', 'teodor'], 'findir', 'teodor') == []
    assert wp.can_claim(True, 'operator', 'teodor') and not wp.can_claim(False, 'operator', 'teodor')
    assert wp.can_claim(False, 'operator', 'operator') and not wp.can_claim(True, 'operator', 'findir')


# ------------------------------------------------------------------------- сид

POLICY_COLUMNS = ('purpose', 'limit_usd', 'initiator_roles', 'confirmer_roles', 'owner_can_alone',
                  'signer_addresses', 'not_for_new_deals', 'signer_weights', 'threshold',
                  'is_multisig', 'accepts_payin', 'owner', 'blockchain', 'active', 'label')


def rows_snapshot():
    s = m.get_session()
    try:
        return {w.address: {c: getattr(w, c) for c in POLICY_COLUMNS} for w in s.query(m.Wallet).all()}
    finally:
        s.close()


def test_seed_creates_six_policy_wallets_with_exact_fields(seeded):
    rows = rows_snapshot()
    labels = {REALTY: 'Груша Недвижимость', PROPERTY: 'Grusha Property < 10 000',
              EXCHANGE: 'Груша Обменник', MFSTR: 'Mfstr', CLIENT99: '99', MARTRUST: 'OTC Martrust'}
    for address in SIX:
        row, weights = rows[address], EXPECTED_WEIGHTS[address]
        initiators, signers = EXPECTED_ROLES[address]
        assert row['label'] == labels[address]
        assert row['purpose'] == weights[2]
        assert json.loads(row['initiator_roles']) == initiators
        assert json.loads(row['confirmer_roles']) == signers
        assert row['owner_can_alone'] is True
        assert json.loads(row['signer_weights']) == weights[0] and row['threshold'] == weights[1]
        assert row['limit_usd'] == (10000 if address == EXCHANGE else None)
        assert (row['not_for_new_deals'], row['owner'], row['is_multisig'], row['accepts_payin'],
                row['blockchain'], row['active']) == (False, 'компания', True, True, 'TRON', True)
        participants = set(initiators) | set(signers)
        assert set(json.loads(row['signer_addresses'])) == participants
        assert json.loads(row['signer_addresses']).items() <= m.POLICY_SIGNER_ADDRESSES.items()
    assert 'operator' not in json.loads(rows[MFSTR]['signer_addresses'])      # у Mfstr оператор не участвует
    assert not wp.can_complete(EXPECTED_WEIGHTS[MFSTR][0], 2, ['operator'])
    assert not wp.can_complete(EXPECTED_WEIGHTS[MFSTR][0], 2, ['operator', 'findir'])
    assert 'findir' not in json.loads(rows[CLIENT99]['signer_addresses'])
    assert m.POLICY_WALLET_ADDRESSES == frozenset(SIX)


def test_seed_is_idempotent(seeded):
    first = rows_snapshot()
    m._stand_seed_wallets()
    m._stand_seed_wallets()
    assert rows_snapshot() == first
    s = m.get_session()
    try:
        assert s.query(m.Wallet).filter(m.Wallet.address.in_(SIX)).count() == 6
    finally:
        s.close()


def test_seed_updates_existing_rows_by_policy_but_keeps_label_and_foreign_wallets(seeded):
    s = m.get_session()
    try:
        mfstr = s.query(m.Wallet).filter_by(address=MFSTR).one()
        mfstr.label = 'Моё имя Mfstr'
        mfstr.initiator_roles = json.dumps(['teodor'])
        mfstr.confirmer_roles = json.dumps(['operator'])
        mfstr.owner_can_alone = False
        mfstr.signer_weights = None
        mfstr.threshold = None
        mfstr.not_for_new_deals = True
        legacy = s.query(m.Wallet).filter_by(address=LEGACY).one()
        legacy.label = 'Старый кошелёк'
        legacy.not_for_new_deals = True
        s.commit()
    finally:
        s.close()
    before = rows_snapshot()
    m._stand_seed_wallets()
    after = rows_snapshot()
    assert after[LEGACY] == before[LEGACY]                       # посторонний старый кошелёк не тронут
    assert after[MFSTR]['label'] == 'Моё имя Mfstr'               # имя не перетирается
    assert json.loads(after[MFSTR]['initiator_roles']) == ['findir']
    assert json.loads(after[MFSTR]['confirmer_roles']) == ['teodor']
    assert after[MFSTR]['owner_can_alone'] is True and after[MFSTR]['not_for_new_deals'] is False
    assert after[MFSTR]['threshold'] == 2 and json.loads(after[MFSTR]['signer_weights']) == {'findir': 1, 'teodor': 2}
    for address in SIX:
        if address != MFSTR:
            assert after[address] == before[address]


def test_inconsistent_seed_is_not_applied_and_fails_loudly(seeded, monkeypatch, capsys, caplog):
    broken = json.loads(json.dumps(m.POLICY_WALLET_SEED))
    broken[REALTY]['initiator_roles'] = ['operator', 'findir']
    broken[REALTY]['confirmer_roles'] = ['findir']          # оператор + финансист = 2 < 3
    broken[REALTY]['label'] = 'Не должно примениться'
    monkeypatch.setattr(m, 'POLICY_WALLET_SEED', broken)
    assert REALTY in m._policy_seed_problems()
    s = m.get_session()
    try:
        s.query(m.Wallet).filter_by(address=REALTY).one().initiator_roles = json.dumps(['teodor'])
        s.commit()
    finally:
        s.close()
    with caplog.at_level('ERROR'):
        m._stand_seed_wallets()
    assert 'не согласована с весами' in capsys.readouterr().out
    assert any('не согласована' in r.getMessage() for r in caplog.records)
    assert wallet_row(REALTY)['initiator_roles'] == ['teodor']      # битая политика не записана


# ---------------------------------------------------------------- миграция колонок

def test_old_wallets_schema_gets_new_columns(tmp_path):
    """Старая таблица wallets (до реестра весов) получает колонки; повторный старт безопасен."""
    db = tmp_path / 'old.db'
    conn = sqlite3.connect(db)
    conn.execute("""CREATE TABLE wallets (id INTEGER PRIMARY KEY, address VARCHAR(100) UNIQUE NOT NULL,
        blockchain VARCHAR(20), label VARCHAR(100), created_at DATETIME, active BOOLEAN,
        is_monitored BOOLEAN, is_balance BOOLEAN, is_multisig BOOLEAN, accepts_payin BOOLEAN, owner VARCHAR(100),
        purpose VARCHAR(20), limit_usd FLOAT, initiator_roles TEXT, confirmer_roles TEXT,
        owner_can_alone BOOLEAN, signer_addresses TEXT, not_for_new_deals BOOLEAN)""")
    conn.execute("INSERT INTO wallets (address, active, not_for_new_deals) VALUES (?, 1, 0)", (LEGACY,))
    conn.commit()
    conn.close()
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('STAND_', 'TELEGRAM_', 'BITRIX_', 'SBER_', 'SERVICE_', 'TRON', 'ETHERSCAN_', 'GOOGLE_'))
           and k not in {'DATABASE_URL', 'SECRET_KEY', 'LOCAL_NO_AUTH'}}
    env.update(DATABASE_URL=f'sqlite:///{db}', SECRET_KEY='migration-test', LOCAL_NO_AUTH='0',
               REESTR_SYNC_ENABLED='0', PAYMENT_POLL_ENABLED='0', PAYIN_ADDR_BACKFILL='0',
               KYC_RETENTION_ENABLED='0', TRONSCAN_WARM_ENABLED='0', METRIKA_TOKEN='',
               STAND_SBER_MIRROR_ENABLED='0', STAND_TG_UPDATES_ENABLED='0',
               STAND_TRANSFER_POLL_ENABLED='0', STAND_MODE='0')
    for _ in range(2):
        result = subprocess.run([sys.executable, '-c', 'import app; app.engine.dispose()'],
                                cwd=ROOT, env=env, capture_output=True, text=True, timeout=180)
        assert result.returncode == 0, result.stdout + result.stderr
    conn = sqlite3.connect(db)
    columns = {r[1] for r in conn.execute('PRAGMA table_info(wallets)')}
    assert {'signer_weights', 'threshold', 'policy_log'} <= columns
    assert conn.execute('SELECT address FROM wallets').fetchall() == [(LEGACY,)]     # данные на месте
    assert 'wallet_policy_log' not in {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()


# ----------------------------------------------------------------- API кошелька

def admin_client():
    return client_for(make_user('admin'))


def policy_log(address):
    s = m.get_session()
    try:
        wallet = s.query(m.Wallet).filter_by(address=address).first()
        return [(r['by_name'], r['before'], r['after']) for r in json.loads(wallet.policy_log or '[]')]
    finally:
        s.close()


def add_wallet(client, **body):
    return client.post('/api/wallets', json={'address': NEW_ADDR, 'blockchain': 'TRON', 'owner': 'Тест',
                                              'accepts_payin': True, **body})


def test_admin_adds_wallet_with_roles_and_log_is_written(seeded):
    r = add_wallet(admin_client(), initiator_roles=['findir', 'operator'], confirmer_roles=['teodor'],
                   owner_can_alone=False)
    assert r.status_code == 200, r.get_json()
    row = wallet_row(NEW_ADDR)
    assert row['initiator_roles'] == ['findir', 'operator'] and row['confirmer_roles'] == ['teodor']
    assert row['owner_can_alone'] is False and row['not_for_new_deals'] is False
    assert row['purpose'] is None and row['signer_weights'] == {} and row['threshold'] is None
    log = policy_log(NEW_ADDR)
    assert len(log) == 1
    assert log[0][1] == {'initiator_roles': [], 'confirmer_roles': [], 'owner_can_alone': False}
    assert log[0][2] == {'initiator_roles': ['findir', 'operator'], 'confirmer_roles': ['teodor'],
                         'owner_can_alone': False}
    assert log[0][0]                                                          # кто изменил


def test_wallet_without_roles_is_saved_hidden_from_new_deals(seeded):
    for role in ('admin', 'operator', 'findir'):
        s = m.get_session()
        try:
            s.query(m.Wallet).filter_by(address=NEW_ADDR).delete()
            s.commit()
        finally:
            s.close()
        r = add_wallet(client_for(make_user(role)))
        assert r.status_code == 200, (role, r.get_json())
        row = wallet_row(NEW_ADDR)
        assert row['not_for_new_deals'] is True and row['initiator_roles'] == [] and row['confirmer_roles'] == []
        assert policy_log(NEW_ADDR) == []
    # в новой сделке такой кошелёк не выбрать
    s = m.get_session()
    try:
        with pytest.raises(ValueError):
            m._crm_payin_wallet_id(s, wallet_row(NEW_ADDR)['id'])
    finally:
        s.close()


@pytest.mark.parametrize('body', [
    {'initiator_roles': [], 'confirmer_roles': ['teodor'], 'owner_can_alone': True},
    {'initiator_roles': ['operator'], 'confirmer_roles': [], 'owner_can_alone': True},
    {'initiator_roles': ['operator', 'findir', 'teodor'], 'confirmer_roles': ['teodor'], 'owner_can_alone': True},
    {'initiator_roles': ['operator'], 'confirmer_roles': ['teodor', 'teodor'], 'owner_can_alone': True},
    {'initiator_roles': ['manager'], 'confirmer_roles': ['teodor'], 'owner_can_alone': True},
    {'initiator_roles': 'operator', 'confirmer_roles': ['teodor'], 'owner_can_alone': True},
    {'initiator_roles': ['operator'], 'confirmer_roles': ['teodor'], 'owner_can_alone': 'yes'},
    {'initiator_roles': ['operator'], 'confirmer_roles': ['teodor']},                      # нет флага
    {'initiator_roles': ['operator'], 'owner_can_alone': True},                            # нет «Подписывает»
])
def test_new_wallet_role_validation(seeded, body):
    r = add_wallet(admin_client(), **body)
    assert r.status_code == 400, r.get_json()
    assert wallet_row(NEW_ADDR) is None


@pytest.mark.parametrize('role', ['operator', 'findir', 'manager', 'teodor'])
def test_only_admin_changes_roles(seeded, role):
    assert add_wallet(admin_client(), initiator_roles=['operator'], confirmer_roles=['teodor'],
                      owner_can_alone=True).status_code == 200
    wid = wallet_row(NEW_ADDR)['id']
    before = wallet_row(NEW_ADDR)
    body = {'initiator_roles': ['findir'], 'confirmer_roles': ['teodor'], 'owner_can_alone': False}
    r = client_for(make_user(role)).patch(f'/api/wallets/{wid}', json=body)
    assert r.status_code == 403, r.get_json()
    assert wallet_row(NEW_ADDR) == before
    # роль может править остальное: подпись кошелька
    if role in ('operator', 'findir'):
        ok = client_for(make_user(role)).patch(f'/api/wallets/{wid}', json={'label': 'Подпись'})
        assert ok.status_code == 200
    # и создать кошелёк с ролями тоже не может
    denied = client_for(make_user(role)).post('/api/wallets', json={
        'address': NEW_ADDR2, 'blockchain': 'TRON', **body})
    assert denied.status_code == 403
    assert wallet_row(NEW_ADDR2) is None


def test_admin_patch_roles_is_logged_with_before_and_after(seeded):
    admin = admin_client()
    assert add_wallet(admin, initiator_roles=['operator'], confirmer_roles=['teodor'],
                      owner_can_alone=True).status_code == 200
    wid = wallet_row(NEW_ADDR)['id']
    r = admin.patch(f'/api/wallets/{wid}', json={'confirmer_roles': ['findir', 'teodor'], 'owner_can_alone': False})
    assert r.status_code == 200, r.get_json()
    again = admin.patch(f'/api/wallets/{wid}', json={'confirmer_roles': ['findir', 'teodor'], 'owner_can_alone': False})
    assert again.status_code == 200                                            # без изменений — без записи
    log = policy_log(NEW_ADDR)
    assert len(log) == 2
    assert log[1][1]['confirmer_roles'] == ['teodor'] and log[1][1]['owner_can_alone'] is True
    assert log[1][2]['confirmer_roles'] == ['findir', 'teodor'] and log[1][2]['owner_can_alone'] is False
    bad = admin.patch(f'/api/wallets/{wid}', json={'initiator_roles': ['operator', 'operator']})
    assert bad.status_code == 400 and len(policy_log(NEW_ADDR)) == 2


def test_admin_giving_roles_to_hidden_wallet_makes_it_selectable(seeded):
    assert add_wallet(admin_client()).status_code == 200
    wid = wallet_row(NEW_ADDR)['id']
    assert wallet_row(NEW_ADDR)['not_for_new_deals'] is True
    r = admin_client().patch(f'/api/wallets/{wid}', json={
        'initiator_roles': ['operator'], 'confirmer_roles': ['teodor'], 'owner_can_alone': True})
    assert r.status_code == 200
    assert wallet_row(NEW_ADDR)['not_for_new_deals'] is False


@pytest.mark.parametrize('address', SIX)
def test_seeded_policy_roles_cannot_be_changed_even_by_admin(seeded, address):
    wid = wallet_row(address)['id']
    before = wallet_row(address)
    r = admin_client().patch(f'/api/wallets/{wid}', json={'initiator_roles': ['teodor'], 'confirmer_roles': ['operator']})
    assert r.status_code == 403
    r = admin_client().post('/api/wallets', json={'address': address, 'initiator_roles': ['teodor'],
                                                  'confirmer_roles': ['operator'], 'owner_can_alone': False})
    assert r.status_code == 403
    assert wallet_row(address) == before
    assert policy_log(address) == []


@pytest.mark.parametrize('field, value', [
    ('purpose', 'realty'), ('limit_usd', 1), ('signer_addresses', {}), ('not_for_new_deals', False),
    ('signer_weights', {'teodor': 9}), ('threshold', 1),
])
def test_public_api_cannot_set_weights_or_service_fields(seeded, field, value):
    admin = admin_client()
    wid = wallet_row(EXCHANGE)['id']
    before = wallet_row(EXCHANGE)
    assert admin.patch(f'/api/wallets/{wid}', json={field: value}).status_code == 403
    assert add_wallet(admin, **{field: value}).status_code == 403
    assert wallet_row(EXCHANGE) == before
    assert wallet_row(NEW_ADDR) is None


def test_wallet_list_exposes_policy_fields(seeded):
    r = admin_client().get('/api/wallets?no_balances=true&all=true')
    rows = {w['address']: w for w in r.get_json()['wallets']}
    assert rows[MFSTR]['initiator_roles'] == ['findir'] and rows[MFSTR]['confirmer_roles'] == ['teodor']
    assert rows[MFSTR]['signer_weights'] == {'findir': 1, 'teodor': 2} and rows[MFSTR]['threshold'] == 2
    assert rows[LEGACY]['initiator_roles'] == [] and rows[LEGACY]['signer_weights'] == {}


# -------------------------------------------- политика действует для любого кошелька с ролями

def test_policy_applies_to_admin_created_wallet(seeded):
    from tests.qa_wallet_roles_helpers import put_board, send_deal, board
    assert add_wallet(admin_client(), initiator_roles=['findir'], confirmer_roles=['operator', 'teodor'],
                      owner_can_alone=False).status_code == 200
    deal, mirror = send_deal(9001, NEW_ADDR, 'TQgQCBXkewuW4RoieDKFP9Ko2SopBh8jso', 1000)
    put_board({'deals': [deal], 'convs': [], 'incomes': [], 'notes': [], 'wallets': [mirror]}, 3)
    # claim: первая роль «Заводит» — финансист; оператор не начинает; владелец не может один
    version = board()[1]
    body = {'dealId': 9001, 'version': version}
    assert client_for(make_user('operator')).post('/api/stand/transfer/claim', json=body).status_code == 403
    assert client_for(make_user('teodor')).post('/api/stand/transfer/claim', json=body).status_code == 403
    ok = client_for(make_user('findir')).post('/api/stand/transfer/claim', json=body)
    assert ok.status_code == 200, ok.get_json()
    state = board()[0]
    claim = state['deals'][0]['transferClaim']
    assert claim['role'] == 'findir' and 'transferConfirmation' not in state['deals'][0]


# ----------------------------- общая таблица для Python и JS (tests/test_wallet_handoff_ui.js)

def test_shared_policy_table_matches_python_functions():
    """JS-реализация сверяется с той же таблицей (tests/fixtures/wallet_policy_table.json),
    поэтому таблица обязана совпадать с тем, что считает wallet_policy.py."""
    table = json.loads((ROOT / 'tests' / 'fixtures' / 'wallet_policy_table.json').read_text(encoding='utf-8'))
    assert set(table) == set(SIX)
    for address, row in table.items():
        policy = m.POLICY_WALLET_SEED[address]
        ini, conf, alone = policy['initiator_roles'], policy['confirmer_roles'], policy['owner_can_alone']
        first = wp.initial_role(ini)
        assert row['initiator_roles'] == ini and row['confirmer_roles'] == conf and row['owner_can_alone'] == alone
        assert row['initial_role'] == first
        assert row['initiate_targets_from_start'] == wp.initiate_targets(ini, alone, first)
        for role in ROLES:
            assert row['initiate_targets'][role] == wp.initiate_targets(ini, alone, role)
            assert row['can_claim'][role] == wp.can_claim(alone, first, role)
            default = wp.default_sign_role(conf, role)
            assert row['sign'][role] == {'default': default, 'targets': wp.sign_targets(conf, role, default)}


# ------------------------------- кошелёк по умолчанию: без выбора по сумме, все шесть доступны вручную

@pytest.mark.parametrize('amount', [9999.99, 10000, 25000, None])
def test_default_payin_wallet_ignores_amount(seeded, amount):
    """Недвижимость -> Груша Недвижимость, обмен -> Груша Обменник при любой сумме; Property/Mfstr/99/Martrust
    автоматически не выбираются."""
    for deal_type, expected in (('Оплата недвижимости', REALTY), ('Обмен валюты', EXCHANGE)):
        deal = {'id': 1, 'type': deal_type, 'amountUsdt': amount}
        network, address = m._stand_payin_target({}, deal)
        assert (network, address) == ('trc20', expected), (deal_type, amount)


def test_all_six_wallets_are_selectable_by_hand_and_carry_purpose_notes(seeded):
    s = m.get_session()
    try:
        for address in SIX:
            assert m._crm_payin_wallet_id(s, wallet_row(address)['id']) == wallet_row(address)['id']
    finally:
        s.close()
    notes = {a: wallet_row(a)['purpose_note'] for a in SIX}
    assert notes[PROPERTY] == 'Приём оплаты за недвижимость до $10 000'
    assert notes[MFSTR] == 'Приём от провайдеров, расчёт с клиентом'
    assert notes[CLIENT99] == 'Только средства клиента: приём, хранение, оплата'
    assert notes[MARTRUST] == 'Только клиент Martrust: приём и выплата'
    assert notes[REALTY] is None and notes[EXCHANGE] is None and wallet_row(LEGACY)['purpose_note'] is None
