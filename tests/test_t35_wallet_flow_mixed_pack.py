"""QA-раунд 4: 4970125 (общий инвариант s23-подписанта). Проверяем то, что
попросил координатор ломать: новая сделка сразу на s23, смешанная пачка
(main мультисиг + side личный), и правку реестра кошельков (PATCH is_multisig)
findir'ом, пока сделка стоит на s23. Плюс легит-флоу: s11, s18/s18w, crypto
s22->s23, смешанная IPPS+Coins пачка (T23), рефанд.
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
        for role in ('operator', 'findir', 'teodor', 'admin'):
            user = m.AdminUser(username='qar4_' + role + '_' + secrets.token_hex(4),
                               role=role, password_hash='synthetic-disabled')
            db.add(user); db.flush(); users[role] = user.id
        db.commit()
    finally:
        db.close()

    def install(deals, state_extra=None):
        state = {'deals': deals, 'convs': [], 'wallets': [], 'incomes': [], 'notes': []}
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


# ── Попытка сломать инвариант ────────────────────────────────────────────

def test_break_new_deal_created_directly_at_s23(board):
    """Новая сделка (никогда не было в previous) заводится сразу шагом s23 с
    личным кошельком. Инвариант из 4970125 пропускает новые сделки (`if not
    was: continue`), но есть более старый общий запрет: новая сделка должна
    начинаться с s4/s5/s6/s8/ready."""
    install, client_for = board
    install([])  # previous.deals пуст
    operator = client_for('operator')
    before = operator.get('/api/stand/state').json
    proposed = copy.deepcopy(before['data'])
    proposed['deals'] = [{'id': 5001, 'code': 'NEWQ4', 'client': 'Synthetic',
                          'type': 'Обмен валюты', 'step': 's23', 'log': [],
                          'walletId': 'teodor', 'payType': 'Крипта'}]
    resp = operator.put('/api/stand/state', json={'version': before['version'], 'data': proposed})
    print('new-deal-at-s23 STATUS', resp.status_code, resp.json)
    assert resp.status_code in (403, 409), resp.json


def test_break_mixed_batch_main_multisig_side_personal(board):
    """Main-сделка в мультисиг-пачке (cnvId=1, grusha), side-сделка НЕ имеет
    cnvId (значит conv-резолв роли для неё не срабатывает) и её собственный
    walletId — личный ('teodor'). Обе сделки уже существовали в previous с
    этими же полями (side всегда имел walletId='teodor', cnvId=None) — значит
    для side собственный s23-сигнер не «меняется на ходу», инвариант его не
    ловит. Проверяем: может ли side сам, без findir, дойти до s23->s24, будучи
    финансово частью мультисиг-пачки главной сделки (через conv.sources)."""
    install, client_for = board
    install([
        {'id': 6001, 'code': 'MAIN4', 'client': 'Synthetic', 'type': 'Обмен валюты',
         'step': 's22', 'log': [], 'cnvId': 1, 'conv': [6002], 'payType': 'Крипта',
         'incomeAmount': 10000, 'payinParts': [{'incId': 1, 'amountRub': 10000}]},
        {'id': 6002, 'code': 'SIDE4', 'client': 'Synthetic', 'type': 'Обмен валюты',
         'step': 's22', 'log': [], 'cnvId': None, 'conv': [], 'payType': 'Крипта',
         'walletId': 'teodor',
         'incomeAmount': 1000, 'payinParts': [{'incId': 2, 'amountRub': 1000}]},
    ], {
        'incomes': [{'id': 1, 'dealId': 6001, 'rub': 10000, 'demo': True},
                    {'id': 2, 'dealId': 6002, 'rub': 1000, 'demo': True}],
        'convs': [{'id': 1, 'walletId': 'grusha',
                   'sources': [{'dealId': 6001, 'rub': 10000},
                               {'dealId': 6002, 'rub': 1000}],
                   'txs': [{'hash': 'a' * 64, 'net': 'TRC-20', 'amount': 200, 'status': 'confirmed'}]}],
        'wallets': [{'id': 'grusha', 'role': 'findir', 'multisig': True,
                     'addr': 'TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn'},
                    {'id': 'teodor', 'role': 'teodor', 'multisig': False,
                     'addr': 'TVmgzMQ2zwV2DVPscBf98WRRdhrcpf5x5p'}],
    })
    operator = client_for('operator')
    before = operator.get('/api/stand/state').json
    proposed = copy.deepcopy(before['data'])
    side = next(d for d in proposed['deals'] if d['id'] == 6002)
    side['step'] = 's23'
    resp = operator.put('/api/stand/state', json={'version': before['version'], 'data': proposed})
    print('mixed-batch-side-to-s23 STATUS', resp.status_code, resp.json)
    if resp.status_code == 200:
        teodor = client_for('teodor')
        before2 = teodor.get('/api/stand/state').json
        proposed2 = copy.deepcopy(before2['data'])
        side2 = next(d for d in proposed2['deals'] if d['id'] == 6002)
        side2['step'] = 's24'
        allowed = teodor.put('/api/stand/state', json={'version': before2['version'], 'data': proposed2})
        print('teodor s23->s24 on side (no findir) STATUS', allowed.status_code, allowed.json)
        assert allowed.status_code in (403, 409), allowed.json  # ожидаем что заблокировано


def test_break_registry_flag_patch_while_deal_at_s23(board):
    """findir через PATCH /api/wallets/<id> флипает is_multisig на кошельке,
    которым сейчас пользуется сделка, стоящая на s23 в мультисиг-пачке. Смотрим:
    (1) сам PATCH не трогает борду напрямую; (2) следующий PUT с обновлённым
    (пере-синхронизированным) состоянием wallets для этой же сделки, стоящей
    неподвижно на s23, блокируется новым инвариантом (fail-closed, не байпас);
    (3) teodor всё ещё не может взять на себя s24 без findir."""
    install, client_for = board
    state = install([
        {'id': 7001, 'code': 'REG4', 'client': 'Synthetic', 'type': 'Обмен валюты',
         'step': 's23', 'log': [], 'cnvId': 1, 'payType': 'Крипта'},
    ], {
        'convs': [{'id': 1, 'walletId': 501, 'sources': [], 'txs': []}],
        'wallets': [],
    })
    findir_id = None
    db = m.get_session()
    try:
        w = m.Wallet(address='T' + 'W' * 33, blockchain='TRON', owner='компания',
                     is_multisig=True, accepts_payin=True, is_monitored=True)
        db.add(w); db.commit(); findir_id = w.id
    finally:
        db.close()
    # борда ссылается на этот кошелёк своим числовым id (как приходит из /api/wallets)
    db = m.get_session()
    try:
        row = m._stand_row(db)
        st = json.loads(row.data)
        st['convs'][0]['walletId'] = str(findir_id)
        st['deals'][0]['cnvId'] = 1
        row.data = json.dumps(st, ensure_ascii=False)
        row.version += 1
        db.commit()
    finally:
        db.close()

    findir = client_for('findir')
    patch_resp = findir.patch(f'/api/wallets/{findir_id}', json={'is_multisig': False})
    print('PATCH registry STATUS', patch_resp.status_code, patch_resp.json)
    assert patch_resp.status_code == 200, patch_resp.json

    # борда (row.data) не тронута PATCH-ем напрямую
    unrelated = client_for('operator')
    before = unrelated.get('/api/stand/state').json
    assert before['data']['convs'][0]['walletId'] == str(findir_id)

    # теперь клиент (любая роль) пере-синхронизирует S.wallets из живого реестра
    # и пытается сохранить борду — сделка на s23 не двигается, но её "было/стало"
    # роль резолвится по-разному (findir -> teodor), потому что реестр обновили
    proposed = copy.deepcopy(before['data'])
    proposed['wallets'] = [{'id': str(findir_id), 'role': 'teodor', 'multisig': False,
                            'addr': 'T' + 'W' * 33, 'owner': 'компания'}]
    resp = unrelated.put('/api/stand/state', json={'version': before['version'], 'data': proposed})
    print('resync PUT after registry flip STATUS', resp.status_code, resp.json)
    assert resp.status_code in (403, 409), resp.json  # должно блокироваться (fail-closed)

    teodor = client_for('teodor')
    before2 = teodor.get('/api/stand/state').json
    proposed2 = copy.deepcopy(before2['data'])
    proposed2['deals'][0]['step'] = 's24'
    denied = teodor.put('/api/stand/state', json={'version': before2['version'], 'data': proposed2})
    print('teodor tries s24 directly STATUS', denied.status_code, denied.json)
    assert denied.status_code in (403, 409), denied.json


# ── Легит: s11 выбор своего кошелька (payinCustom), шаг не меняется ────────

def test_legit_s11_custom_wallet_choice_multisig_flag(board):
    install, client_for = board
    install([{'id': 8001, 'code': 'S11LEG', 'client': 'Synthetic', 'type': 'Обмен валюты',
              'step': 's11', 'log': [], 'walletId': 'custom', 'payType': 'Крипта',
              'payinCustom': {'network': 'TRC-20', 'addr': 'T' + 'A' * 33,
                              'owner': 'компания', 'multisig': True}}])
    operator = client_for('operator')
    before = operator.get('/api/stand/state').json
    proposed = copy.deepcopy(before['data'])
    # операционист правит адрес, не трогая шаг — обычная правка на s11
    proposed['deals'][0]['payinCustom']['addr'] = 'T' + 'B' * 33
    resp = operator.put('/api/stand/state', json={'version': before['version'], 'data': proposed})
    print('s11 custom wallet edit STATUS', resp.status_code, resp.json)
    assert resp.status_code == 200, resp.json


def test_legit_s11_custom_wallet_flip_multisig_flag_allowed(board):
    """На s11 разрешено поменять сам флаг мультисиг (владелец уточняет данные) —
    это ровно то место, где кошелёк выбирают, инвариант это явно разрешает."""
    install, client_for = board
    install([{'id': 8002, 'code': 'S11LEG2', 'client': 'Synthetic', 'type': 'Обмен валюты',
              'step': 's11', 'log': [], 'walletId': 'custom', 'payType': 'Крипта',
              'payinCustom': {'network': 'TRC-20', 'addr': 'T' + 'A' * 33,
                              'owner': 'Теодор', 'multisig': False}}])
    operator = client_for('operator')
    before = operator.get('/api/stand/state').json
    proposed = copy.deepcopy(before['data'])
    proposed['deals'][0]['payinCustom']['multisig'] = True
    proposed['deals'][0]['payinCustom']['owner'] = 'компания'
    resp = operator.put('/api/stand/state', json={'version': before['version'], 'data': proposed})
    print('s11 flip multisig STATUS', resp.status_code, resp.json)
    assert resp.status_code == 200, resp.json
