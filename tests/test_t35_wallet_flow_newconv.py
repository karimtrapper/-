"""Точная проверка варианта (a): новая пачка (conv), которой не было в previous,
не попадает под гейт da674e1 (тот итерирует только previous.convs). Строим
валидный с точки зрения check_batch/check_state источник RUB (реальный
подтверждённый приход), чтобы не упасть на несвязанной funding-проверке.
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
            user = m.AdminUser(username='qarv3b_' + role + '_' + secrets.token_hex(4),
                               role=role, password_hash='synthetic-disabled')
            db.add(user); db.flush(); users[role] = user.id
        db.commit()
    finally:
        db.close()

    def install(step, extra=None, state_extra=None, deal_id=9935):
        state = {'deals': [{'id': deal_id, 'code': 'QARV3B-T35', 'client': 'Synthetic',
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


def test_qa_v3b_new_conv_with_valid_funding_bypasses_s18_lock(board):
    """Деал уже имеет подтверждённый RUB-приход (demo=True, как в реальном флоу
    test_t29_step_role._broker_state). Одним PUT: создаём НОВУЮ пачку (id=888,
    которой не было в previous.convs) с личным кошельком 'teodor', привязываем
    к ней сделку и одновременно двигаем шаг s11 -> s23, минуя s18/s18w/s22.
    Гейт da674e1 итерирует только previous.get('convs') — новой пачки там нет,
    поэтому её walletId никак не проверяется."""
    install, client_for = board
    install('s11', {
        'incomeAmount': 10000, 'payinParts': [{'incId': 1, 'amountRub': 10000}],
        'rates': {}, 'payType': 'Крипта',
    }, {
        'incomes': [{'id': 1, 'dealId': 9935, 'rub': 10000, 'demo': True}],
    })
    operator = client_for('operator')
    before = operator.get('/api/stand/state').json
    proposed = copy.deepcopy(before['data'])
    proposed['deals'][0]['step'] = 's23'
    proposed['deals'][0]['cnvId'] = 888
    proposed['convs'] = [{'id': 888, 'walletId': 'teodor', 'sources': [
        {'dealId': 9935, 'rub': 10000}], 'txs': []}]
    resp = operator.put('/api/stand/state', json={'version': before['version'], 'data': proposed})
    print('STATUS', resp.status_code, resp.json)
    if resp.status_code == 200:
        deal = resp.json['data']['deals'][0]
        assert deal['step'] == 's23'
        assert resp.json['data']['convs'][0]['walletId'] == 'teodor'
        # findir не должен иметь возможности вообще коснуться этой сделки на s24
        findir = client_for('findir')
        before2 = findir.get('/api/stand/state').json
        denied = findir.put('/api/stand/state', json={
            'version': before2['version'],
            'data': {**before2['data'], 'deals': [{**before2['data']['deals'][0], 'step': 's24'}]}})
        teodor = client_for('teodor')
        before3 = teodor.get('/api/stand/state').json
        allowed = teodor.put('/api/stand/state', json={
            'version': before3['version'],
            'data': {**before3['data'], 'deals': [{**before3['data']['deals'][0], 'step': 's24'}]}})
        print('findir denied?', denied.status_code, 'teodor allowed?', allowed.status_code)
    assert resp.status_code in (403, 409), resp.json  # ФИКСИРУЕМ ФАКТ (может упасть, если атака проходит)


def test_qa_v3b_reassign_to_existing_personal_conv_at_s22(board):
    """Деал уже в мультисиг-пачке (conv1='grusha', findir), с реальным
    подтверждённым RUB-приходом. Есть вторая, УЖЕ существующая личная пачка
    conv2='teodor' (пустая, ни у одной из двух walletId не меняется — гейт
    da674e1 проверяет именно смену walletId конкретной пачки). Одним PUT
    переносим сделку из conv1 в conv2 (меняем cnvId + sources), одновременно
    двигая шаг s22 -> s23."""
    install, client_for = board
    install('s22', {
        'cnvId': 1, 'incomeAmount': 10000,
        'payinParts': [{'incId': 1, 'amountRub': 10000}],
        'rates': {}, 'payType': 'Крипта',
    }, {
        'incomes': [{'id': 1, 'dealId': 9935, 'rub': 10000, 'demo': True}],
        'convs': [
            {'id': 1, 'walletId': 'grusha', 'sources': [{'dealId': 9935, 'rub': 10000}], 'txs': []},
            {'id': 2, 'walletId': 'teodor', 'sources': [], 'txs': []},
        ],
    })
    operator = client_for('operator')
    before = operator.get('/api/stand/state').json
    proposed = copy.deepcopy(before['data'])
    proposed['deals'][0]['cnvId'] = 2
    proposed['deals'][0]['step'] = 's23'
    proposed['convs'][0]['sources'] = []
    proposed['convs'][1]['sources'] = [{'dealId': 9935, 'rub': 10000}]
    resp = operator.put('/api/stand/state', json={'version': before['version'], 'data': proposed})
    print('STATUS', resp.status_code, resp.json)
    assert resp.status_code in (403, 409), resp.json
