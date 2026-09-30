"""Подтверждение реквизитов менеджером перед оплатой (T34 п.3, задача Карима).

Прямо перед тем, как операционист заплатит (s26 «Оплатить инвойс») или для
фрихолда отправит заявку в IPPS (s25), менеджер жмёт «Реквизиты верны — можно
платить» на актуальном снимке payTo. Сервер обязан отвергать invoicePaid/
ippsSent без такого подтверждения, даже если клиент обошёл disabled в разметке
(_stand_guard_transition — общий маршрут PUT /api/stand/state).

Fixture — тот же паттерн реального HTTP-клиента, что в test_t34_parallel_drafts.py.
"""
import copy
import json

import pytest

import app as appmod


@pytest.fixture
def board(monkeypatch):
    monkeypatch.setattr(appmod, 'STAND_MODE', True)
    monkeypatch.setenv('LOCAL_NO_AUTH', '1')
    role = {'value': 'manager'}
    monkeypatch.setattr(appmod, 'current_role', lambda: role['value'])
    monkeypatch.setattr(appmod, '_stand_deliver_notes', lambda: None)
    appmod._stand_migrate()

    def seed(deal):
        db = appmod.get_session()
        try:
            row = appmod._stand_row(db)
            state = (deal if 'deals' in deal else
                     {'deals': [deal], 'convs': [], 'wallets': [], 'notes': []})
            row.data = json.dumps(state)
            row.version = 1
            db.commit()
        finally:
            db.close()

    with appmod.app.test_client() as client:
        db = appmod.get_session()
        try:
            user = db.query(appmod.AdminUser).filter_by(username='t34pc_synthetic').first()
            if not user:
                user = appmod.AdminUser(username='t34pc_synthetic', role='manager',
                                        password_hash=appmod.AdminUser.hash_password('test'))
                db.add(user)
                db.commit()
            uid = user.id
        finally:
            db.close()
        with client.session_transaction() as session:
            session['user_id'] = uid
        yield client, role, seed


def _get(client):
    response = client.get('/api/stand/state')
    assert response.status_code == 200
    return response.json


def _put(client, current, deal, *, notes=None):
    data = copy.deepcopy(current['data'])
    data['deals'][0] = deal
    if notes is not None:
        data['notes'] = notes
    return client.put('/api/stand/state', json={'version': current['version'], 'data': data})


LEASEHOLD_PAYTO = {'dev': 'Developer', 'bank': 'Bank', 'acc': '123456',
                    'purpose': 'invoice INV-1', 'amount': 350000}
FREEHOLD_PAYTO = {'dev': 'Developer', 'bank': 'Bank', 'swift': 'TESTTHBK',
                   'acc': '123456', 'purpose': 'invoice INV-1', 'amount': 45000}


def _leasehold_deal(step='s26', **extra):
    deal = {'id': 3501, 'code': 'LH-1', 'client': 'T34 Pay Confirm',
            'type': 'Оплата недвижимости', 'kind': 'Лизхолд', 'step': step,
            'payType': 'По реквизитам', 'log': [], 'pay': {}, 'payout': {},
            'docs': {'receipt': True}, 'files': {}, 'docMeta': {},
            'payTo': dict(LEASEHOLD_PAYTO), 'reqTask': 'done'}
    deal.update(extra)
    return deal


def _freehold_deal(step='s25', **extra):
    deal = {'id': 3502, 'code': 'FH-1', 'client': 'T34 Pay Confirm Freehold',
            'type': 'Оплата недвижимости', 'kind': 'Фрихолд', 'step': step,
            'payType': 'Крипта', 'curBase': 'usdt', 'invoiceUsd': 45000,
            'ippsTariff': 'bank', 'postConv': 'ipps_swift',
            'serverTransferComplete': True,
            'transfer': {'addr': 'TQgQCBXkewuW4RoieDKFP9Ko2SopBh8jso',
                         'net': 'TRC-20', 'amount': 45410, 'sends': []},
            'log': [], 'pay': {}, 'payout': {}, 'docs': {}, 'files': {}, 'docMeta': {},
            'payTo': dict(FREEHOLD_PAYTO), 'reqTask': 'done'}
    deal.update(extra)
    return deal


def test_s26_pay_without_confirmation_rejected(board):
    client, role, seed = board
    seed(_leasehold_deal('s26'))
    role['value'] = 'operator'
    before = _get(client)
    pay = copy.deepcopy(before['data']['deals'][0])
    pay['pay']['invoicePaid'] = True
    denied = _put(client, before, pay)
    assert denied.status_code == 409
    assert 'подтверждени' in denied.json['error'].lower()
    assert _get(client) == before


def test_s26_pay_after_confirmation_allowed(board):
    client, role, seed = board
    seed(_leasehold_deal('s26'))
    role['value'] = 'manager'
    state = _get(client)
    confirm = copy.deepcopy(state['data']['deals'][0])
    confirm['payToConfirm'] = {'payTo': confirm['payTo'], 'at': 1}
    ok = _put(client, state, confirm)
    assert ok.status_code == 200, ok.json

    role['value'] = 'operator'
    ready = _get(client)
    pay = copy.deepcopy(ready['data']['deals'][0])
    pay['pay']['invoicePaid'] = True
    paid = _put(client, ready, pay)
    assert paid.status_code == 200, paid.json
    assert paid.json['data']['deals'][0]['pay']['invoicePaid'] is True


def test_editing_requisites_after_confirmation_resets_it(board):
    """Реквизиты — параллельная задача менеджера (Карим, 25.09): правка идёт через
    штатный reqReopen → reqSave (reqTask 'done'→'open'→'done'), а не прямой правкой
    payTo мимо задачи — так же, как делает клиент в tasks.html."""
    client, role, seed = board
    deal = _leasehold_deal('s26')
    deal['payToConfirm'] = {'payTo': dict(deal['payTo']), 'at': 1}
    seed(deal)

    role['value'] = 'manager'
    state = _get(client)
    reopened = copy.deepcopy(state['data']['deals'][0])
    reopened['reqTask'] = 'open'
    reopened['log'].append({'text': 'Реквизиты для оплаты открыты на правку'})
    reopen_saved = _put(client, state, reopened)
    assert reopen_saved.status_code == 200, reopen_saved.json

    state = _get(client)
    edited = copy.deepcopy(state['data']['deals'][0])
    edited['payTo']['acc'] = '999999'
    edited['reqTask'] = 'done'
    edited['log'].append({'text': 'менеджер поправил номер счёта'})
    saved = _put(client, state, edited)
    assert saved.status_code == 200, saved.json
    # Подтверждение не трогаем автоматически — просто оно больше не совпадает
    # с текущим payTo, поэтому его сила теряется сама (без отдельного флага сброса).
    assert saved.json['data']['deals'][0]['payToConfirm']['payTo']['acc'] == '123456'
    assert saved.json['data']['deals'][0]['payTo']['acc'] == '999999'

    role['value'] = 'operator'
    stale = _get(client)
    pay = copy.deepcopy(stale['data']['deals'][0])
    pay['pay']['invoicePaid'] = True
    still_denied = _put(client, stale, pay)
    assert still_denied.status_code == 409
    assert 'подтверждени' in still_denied.json['error'].lower()

    role['value'] = 'manager'
    reconfirm_state = _get(client)
    reconfirm = copy.deepcopy(reconfirm_state['data']['deals'][0])
    reconfirm['payToConfirm'] = {'payTo': reconfirm['payTo'], 'at': 2}
    assert _put(client, reconfirm_state, reconfirm).status_code == 200

    role['value'] = 'operator'
    ready = _get(client)
    pay = copy.deepcopy(ready['data']['deals'][0])
    pay['pay']['invoicePaid'] = True
    paid = _put(client, ready, pay)
    assert paid.status_code == 200, paid.json


def test_operator_cannot_forge_payto_confirm(board):
    client, role, seed = board
    seed(_leasehold_deal('s26'))
    role['value'] = 'operator'
    state = _get(client)
    forged = copy.deepcopy(state['data']['deals'][0])
    forged['payToConfirm'] = {'payTo': forged['payTo'], 'at': 1}
    denied = _put(client, state, forged)
    assert denied.status_code == 409
    assert 'менеджеру' in denied.json['error'].lower()

    forged_pay = copy.deepcopy(state['data']['deals'][0])
    forged_pay['payToConfirm'] = {'payTo': forged_pay['payTo'], 'at': 1}
    forged_pay['pay']['invoicePaid'] = True
    denied2 = _put(client, state, forged_pay)
    assert denied2.status_code == 409


def test_manager_confirms_while_operator_holds_s26_without_foreign_role_conflict(board):
    """Подтверждение — параллельная задача менеджера, а не шаг чужой роли: T29 не
    должен воспринимать её как попытку продвинуть чужой s26 (QA 30.09 blocking-fix)."""
    client, role, seed = board
    seed(_leasehold_deal('s26'))
    role['value'] = 'manager'
    state = _get(client)
    confirm = copy.deepcopy(state['data']['deals'][0])
    confirm['payToConfirm'] = {'payTo': confirm['payTo'], 'at': 1}
    ok = _put(client, state, confirm)
    assert ok.status_code == 200, ok.json
    assert ok.json['data']['deals'][0]['step'] == 's26'


def test_freehold_ipps_send_gated_same_as_s26(board):
    client, role, seed = board
    seed(_freehold_deal('s25'))
    role['value'] = 'operator'
    before = _get(client)
    send = copy.deepcopy(before['data']['deals'][0])
    send['pay']['ippsSent'] = True
    denied = _put(client, before, send)
    assert denied.status_code == 409
    assert 'подтверждени' in denied.json['error'].lower()

    role['value'] = 'manager'
    state = _get(client)
    confirm = copy.deepcopy(state['data']['deals'][0])
    confirm['payToConfirm'] = {'payTo': confirm['payTo'], 'at': 1}
    assert _put(client, state, confirm).status_code == 200

    role['value'] = 'operator'
    ready = _get(client)
    send = copy.deepcopy(ready['data']['deals'][0])
    send['pay']['ippsSent'] = True
    sent = _put(client, ready, send)
    assert sent.status_code == 200, sent.json
    assert sent.json['data']['deals'][0]['pay']['ippsSent'] is True
