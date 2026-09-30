"""Единый реестр кошельков на весь флоу задачника (Карим, wallet-registry).

Кто отправляет с кошелька — фин дир (мультисиг) или сам владелец (личный) —
решают флаги CRM-реестра (`wallets.is_multisig`/`owner`), а не хардкод. То же
самое для кошелька, «Указанного» на s11 без «Запомнить» (owner/multisig лежат
в deal.payinCustom). Покрывает: создание кошелька с флагами через реестр,
роль s23 по мультисигу/личному владельцу (Теодор, Андрей, custom), легаси-id,
и что сервер не пускает не ту роль дальше без корректно заданного подписанта.
"""
import copy
import json
import secrets

import pytest

import app as m


@pytest.fixture
def board(monkeypatch):
    monkeypatch.setattr(m, 'STAND_MODE', True)
    monkeypatch.setattr(m, '_stand_deliver_notes', lambda: None)
    m._stand_migrate()
    users = {}
    db = m.get_session()
    try:
        for role in ('manager', 'operator', 'findir', 'teodor', 'admin'):
            user = m.AdminUser(username='t35_' + role + '_' + secrets.token_hex(4),
                               role=role, password_hash='synthetic-disabled')
            db.add(user)
            db.flush()
            users[role] = user.id
        db.commit()
    finally:
        db.close()

    def install(step, extra=None, state_extra=None):
        state = {'deals': [{'id': 1535, 'code': 'SYNTH-T35', 'client': 'Synthetic',
                            'type': 'Обмен валюты', 'step': step, 'log': [],
                            **(extra or {})}],
                 'convs': [], 'wallets': [], 'incomes': [], 'notes': []}
        state.update(state_extra or {})
        db = m.get_session()
        try:
            row = m._stand_row(db)
            row.data = json.dumps(state, ensure_ascii=False)
            row.version = (row.version or 0) + 1
            db.commit()
        finally:
            db.close()
        return copy.deepcopy(state)

    def client(role):
        test_client = m.app.test_client()
        with test_client.session_transaction() as sess:
            sess['user_id'] = users[role]
            sess['role'] = 'operator' if role == 'manager' else 'manager'
        return test_client

    return install, client


def _only_step(state, destination):
    proposed = copy.deepcopy(state)
    proposed['deals'][0]['step'] = destination
    return proposed


# ── Кошелёк «Запомнить» уходит в единый реестр CRM с owner/is_multisig ──────

def test_remember_creates_crm_wallet_with_owner_and_multisig(board, monkeypatch):
    install, client_for = board
    # POST /api/wallets тянет начальный баланс из TronScan (add_wallet) — на
    # стенде это единственный сетевой вызов маршрута; в изолированном pytest
    # сеть недоступна, поэтому канал глушим, как советует QA-регламент.
    monkeypatch.setattr(m, '_stand_tronscan_get', lambda op, params: None)
    operator = client_for('operator')
    addr = 'TWcZZ5nDBkaKuG4izShcnAFBui51NA4NnD'
    resp = operator.post('/api/wallets', json={
        'address': addr, 'blockchain': 'TRON', 'accepts_payin': True,
        'is_monitored': True, 'owner': 'Виталий', 'is_multisig': True})
    assert resp.status_code == 200, resp.json
    wallet = resp.json['wallet']
    assert wallet['owner'] == 'Виталий'
    assert wallet['is_multisig'] is True
    assert wallet['accepts_payin'] is True
    db = m.get_session()
    try:
        row = db.query(m.Wallet).filter_by(address=addr).first()
        assert row is not None and row.owner == 'Виталий' and row.is_multisig is True
    finally:
        db.close()


def test_wallet_registry_write_denied_for_manager(board):
    install, client_for = board
    manager = client_for('manager')
    resp = manager.post('/api/wallets', json={'address': 'T' + 'B' * 33, 'owner': 'кто-то'})
    assert resp.status_code == 403, resp.json


# ── Кошелёк из реестра CRM: мультисиг → findir, личный → сам владелец ──────

def test_registry_multisig_wallet_owns_s23_findir(board):
    install, client_for = board
    install('s23', {'cnvId': 1}, {
        'convs': [{'id': 1, 'walletId': '9001', 'sources': [], 'txs': []}],
        # То, что сервер видит в общем состоянии, — зеркало реестра CRM
        # (role/multisig производятся из is_multisig клиентом, см. crmWalletToLegacy).
        'wallets': [{'id': '9001', 'role': 'findir', 'multisig': True,
                     'addr': 'T' + 'C' * 33, 'owner': 'компания'}],
    })
    wrong = client_for('teodor')
    before = wrong.get('/api/stand/state').json
    denied = wrong.put('/api/stand/state', json={
        'version': before['version'], 'data': _only_step(before['data'], 's24')})
    assert denied.status_code in (403, 409), denied.json
    signer = client_for('findir')
    allowed = signer.put('/api/stand/state', json={
        'version': before['version'], 'data': _only_step(before['data'], 's24')})
    assert allowed.status_code == 200, allowed.json


def test_registry_personal_wallet_owns_s23_owner_role(board):
    install, client_for = board
    install('s23', {'cnvId': 1}, {
        'convs': [{'id': 1, 'walletId': '9002', 'sources': [], 'txs': []}],
        'wallets': [{'id': '9002', 'role': 'teodor', 'multisig': False,
                     'addr': 'T' + 'D' * 33, 'owner': 'Андрей'}],
    })
    wrong = client_for('findir')
    before = wrong.get('/api/stand/state').json
    denied = wrong.put('/api/stand/state', json={
        'version': before['version'], 'data': _only_step(before['data'], 's24')})
    assert denied.status_code in (403, 409), denied.json
    signer = client_for('teodor')
    allowed = signer.put('/api/stand/state', json={
        'version': before['version'], 'data': _only_step(before['data'], 's24')})
    assert allowed.status_code == 200, allowed.json


# ── «Указать кошелёк…» без «Запомнить»: owner/multisig из payinCustom ──────

def test_custom_wallet_multisig_true_owns_s23_findir(board):
    install, client_for = board
    install('s23', {
        'walletId': 'custom', 'payType': 'Крипта',
        'payinCustom': {'network': 'TRC-20', 'addr': 'T' + 'E' * 33,
                        'owner': 'компания', 'multisig': True},
    })
    wrong = client_for('teodor')
    before = wrong.get('/api/stand/state').json
    denied = wrong.put('/api/stand/state', json={
        'version': before['version'], 'data': _only_step(before['data'], 's24')})
    assert denied.status_code in (403, 409), denied.json
    signer = client_for('findir')
    allowed = signer.put('/api/stand/state', json={
        'version': before['version'], 'data': _only_step(before['data'], 's24')})
    assert allowed.status_code == 200, allowed.json


@pytest.mark.parametrize('owner', ['Теодор', 'Андрей'])
def test_custom_wallet_personal_owns_s23_teodor_role(board, owner):
    install, client_for = board
    install('s23', {
        'walletId': 'custom', 'payType': 'Крипта',
        'payinCustom': {'network': 'TRC-20', 'addr': 'T' + 'F' * 33,
                        'owner': owner, 'multisig': False},
    })
    wrong = client_for('findir')
    before = wrong.get('/api/stand/state').json
    denied = wrong.put('/api/stand/state', json={
        'version': before['version'], 'data': _only_step(before['data'], 's24')})
    assert denied.status_code in (403, 409), denied.json
    signer = client_for('teodor')
    allowed = signer.put('/api/stand/state', json={
        'version': before['version'], 'data': _only_step(before['data'], 's24')})
    assert allowed.status_code == 200, allowed.json


def test_custom_wallet_without_multisig_flag_blocks_s23(board):
    """Старые/некорректные данные без явного multisig — подписант неизвестен,
    сервер держит сделку на s22 (guard в _stand_guard_transition)."""
    install, client_for = board
    install('s22', {
        'walletId': 'custom', 'payType': 'Крипта',
        'payinCustom': {'network': 'TRC-20', 'addr': 'T' + 'G' * 33, 'owner': 'компания'},
    })
    operator = client_for('operator')
    before = operator.get('/api/stand/state').json
    denied = operator.put('/api/stand/state', json={
        'version': before['version'], 'data': _only_step(before['data'], 's23')})
    assert denied.status_code in (403, 409), denied.json
    assert 'подписант' in denied.json.get('error', '')


def test_custom_wallet_with_multisig_flag_allows_s23(board):
    install, client_for = board
    install('s22', {
        'walletId': 'custom', 'payType': 'Крипта',
        'payinCustom': {'network': 'TRC-20', 'addr': 'T' + 'H' * 33,
                        'owner': 'Теодор', 'multisig': False},
    })
    operator = client_for('operator')
    before = operator.get('/api/stand/state').json
    allowed = operator.put('/api/stand/state', json={
        'version': before['version'], 'data': _only_step(before['data'], 's23')})
    assert allowed.status_code == 200, allowed.json


# ── Легаси id продолжают резолвиться: через реестр CRM, если он знает адрес,
#    иначе — через старый фолбэк-адрес ────────────────────────────────────

def test_legacy_wallet_id_resolves_via_crm_registry_row(board):
    install, client_for = board
    addr = 'TVmgzMQ2zwV2DVPscBf98WRRdhrcpf5x5p'  # легаси-адрес 'teodor'
    db = m.get_session()
    try:
        existing = db.query(m.Wallet).filter_by(address=addr).first()
        if not existing:
            db.add(m.Wallet(address=addr, blockchain='TRON', owner='Теодор',
                            is_multisig=False, accepts_payin=True, is_monitored=True))
            db.commit()
    finally:
        db.close()
    state = {'deals': [], 'convs': [], 'wallets': [], 'incomes': [], 'notes': []}
    deal = {'id': 1, 'walletId': 'teodor', 'payType': 'Крипта'}
    network, receiver = m._stand_payin_target(state, deal)
    assert network == 'trc20'
    assert receiver == addr


def test_legacy_wallet_id_resolves_without_crm_row(board):
    """Реестр ещё не знает адрес Андрея — легаси-фолбэк по-прежнему работает."""
    state = {'deals': [], 'convs': [], 'wallets': [], 'incomes': [], 'notes': []}
    deal = {'id': 2, 'walletId': 'andrey', 'payType': 'Крипта'}
    network, receiver = m._stand_payin_target(state, deal)
    assert network == 'trc20'
    assert receiver == 'TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn'
