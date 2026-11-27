"""QA независимая проверка фикса 6442648 поверх 31dfecf (wallet-registry).
Повтор jump-атаки + новый вариант (walletId мультисиг-реестр -> личный реестр
вместе со сменой шага) + XSS-проверка экранирования owner в walletSends.
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
            user = m.AdminUser(username='qarv2_' + role + '_' + secrets.token_hex(4),
                               role=role, password_hash='synthetic-disabled')
            db.add(user); db.flush(); users[role] = user.id
        db.commit()
    finally:
        db.close()

    def install(step, extra=None, state_extra=None):
        state = {'deals': [{'id': 9735, 'code': 'QARV2-T35', 'client': 'Synthetic',
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


# 1. Повтор основной jump-атаки: custom-кошелёк, s11->s23 + multisig true->false
def test_qa_v2_jump_custom_wallet_multisig_flip_rejected(board):
    install, client_for = board
    install('s11', {
        'walletId': 'custom', 'payType': 'Крипта',
        'payinCustom': {'network': 'TRC-20', 'addr': 'T' + 'Z' * 33,
                        'owner': 'компания', 'multisig': True},
    })
    operator = client_for('operator')
    before = operator.get('/api/stand/state').json
    proposed = copy.deepcopy(before['data'])
    proposed['deals'][0]['step'] = 's23'
    proposed['deals'][0]['payinCustom']['multisig'] = False
    resp = operator.put('/api/stand/state', json={'version': before['version'], 'data': proposed})
    assert resp.status_code in (403, 409), resp.json
    # сделка должна остаться на s11 с прежним (мультисиг) payinCustom
    db = m.get_session()
    try:
        row = m._stand_row(db)
        state = json.loads(row.data)
    finally:
        db.close()
    deal = state['deals'][0]
    assert deal['step'] == 's11', deal
    assert deal['payinCustom']['multisig'] is True, deal


# 2. Новый вариант: walletId из реестра CRM, мультисиг ('9001', findir) ->
#    личный ('9002', teodor) вместе со сменой шага s11->s23 в одном PUT.
def test_qa_v2_jump_registry_wallet_multisig_to_personal_rejected(board):
    install, client_for = board
    install('s11', {'cnvId': None, 'walletId': '9001', 'payType': 'Крипта'}, {
        'wallets': [
            {'id': '9001', 'role': 'findir', 'multisig': True,
             'addr': 'T' + 'C' * 33, 'owner': 'компания'},
            {'id': '9002', 'role': 'teodor', 'multisig': False,
             'addr': 'T' + 'D' * 33, 'owner': 'Андрей'},
        ],
    })
    operator = client_for('operator')
    before = operator.get('/api/stand/state').json
    proposed = copy.deepcopy(before['data'])
    proposed['deals'][0]['step'] = 's23'
    proposed['deals'][0]['walletId'] = '9002'
    resp = operator.put('/api/stand/state', json={'version': before['version'], 'data': proposed})
    assert resp.status_code in (403, 409), resp.json
    db = m.get_session()
    try:
        row = m._stand_row(db)
        state = json.loads(row.data)
    finally:
        db.close()
    deal = state['deals'][0]
    assert deal['step'] == 's11', deal
    assert deal['walletId'] == '9001', deal


def test_qa_v2_walletsends_escapes_owner_xss():
    payload = '<img src=x onerror=alert(1)>'
    # мультисиг-ветка не подставляет owner вовсе
    out_multisig = m  # noop, проверяем только личную ветку ниже
    # эмулируем ровно то, что делает JS: прочитать функцию из файла и проверить
    # непосредственно наличие htmlText-обёртки вокруг w.owner в исходнике.
    with open('static/stand/tasks.html', encoding='utf-8') as f:
        src = f.read()
    import re
    m2 = re.search(r"function walletSends\(w\)\{return[^}]*\}", src)
    assert m2, 'walletSends не найдена'
    body = m2.group(0)
    assert 'htmlText(w.owner' in body, body


def test_conv_wallet_multisig_to_personal_with_step_jump_rejected(board):
    """conv.walletId grusha→teodor в одном PUT с прыжком s11→s23 — отказ, пачка и шаг
    не меняются, фин дир остаётся в цепочке (QA 30.09)."""
    install, client_for = board
    install('s11', {'cnvId': 1, 'walletId': 'grusha', 'payType': 'Крипта'}, {
        'convs': [{'id': 1, 'walletId': 'grusha', 'sources': [], 'txs': []}],
        'wallets': [],
    })
    operator = client_for('operator')
    before = operator.get('/api/stand/state').json
    proposed = copy.deepcopy(before['data'])
    proposed['deals'][0]['step'] = 's23'
    proposed['convs'][0]['walletId'] = 'teodor'
    resp = operator.put('/api/stand/state', json={'version': before['version'], 'data': proposed})
    assert resp.status_code in (403, 409), resp.json
    after = operator.get('/api/stand/state').json['data']
    assert after['deals'][0]['step'] == 's11'
    assert after['convs'][0]['walletId'] == 'grusha'


def test_conv_wallet_change_allowed_on_s18_without_step_change(board):
    """Штатный выбор кошелька пачки на s18 (куда брокер пришлёт USDT) по-прежнему работает."""
    install, client_for = board
    install('s18', {'cnvId': 1, 'walletId': 'grusha', 'payType': 'По реквизитам'}, {
        'convs': [{'id': 1, 'walletId': 'grusha', 'sources': [], 'txs': []}],
        'wallets': [],
    })
    operator = client_for('operator')
    before = operator.get('/api/stand/state').json
    proposed = copy.deepcopy(before['data'])
    proposed['convs'][0]['walletId'] = 'teodor'
    resp = operator.put('/api/stand/state', json={'version': before['version'], 'data': proposed})
    assert resp.status_code == 200, resp.json
