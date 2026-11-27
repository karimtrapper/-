"""Независимая QA-проверка stand/t34-release (dae8473) поверх готовых фикстур
test_t34_pay_confirm.py / test_t34_parallel_drafts.py. Не редактирует их — только
добавляет сценарии из чек-листа ревью, которых там не было дословно:
(d) обход s26 другим полем, (f) ранняя правка менеджера чужих/денежных полей,
(g) 409 на реальную правку чужой сделки (без изменений), (h) быстрый повтор t35."""
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
            user = db.query(appmod.AdminUser).filter_by(username='t34qa_synthetic').first()
            if not user:
                user = appmod.AdminUser(username='t34qa_synthetic', role='manager',
                                        password_hash=appmod.AdminUser.hash_password('test'))
                db.add(user)
                db.commit()
            uid = user.id
        finally:
            db.close()
        with client.session_transaction() as session:
            session['user_id'] = uid
        yield client, role, seed


LEASEHOLD_PAYTO = {'dev': 'Developer', 'bank': 'Bank', 'acc': '123456',
                    'purpose': 'invoice INV-1', 'amount': 350000}


def _leasehold_deal(step='s26', **extra):
    deal = {'id': 9001, 'code': 'QA-LH-1', 'client': 'QA Release Review',
            'type': 'Оплата недвижимости', 'kind': 'Лизхолд', 'step': step,
            'payType': 'По реквизитам', 'log': [], 'pay': {}, 'payout': {},
            'docs': {'receipt': True}, 'files': {}, 'docMeta': {},
            'payTo': dict(LEASEHOLD_PAYTO), 'reqTask': 'done'}
    deal.update(extra)
    return deal


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


# (d) обход s26->done другим полем без invoicePaid/подтверждения: пытаемся
# продвинуть шаг напрямую, минуя pay.invoicePaid.
def test_step_jump_past_s26_without_paid_flag_is_blocked(board):
    client, role, seed = board
    seed(_leasehold_deal('s26'))
    role['value'] = 'operator'
    before = _get(client)
    jump = copy.deepcopy(before['data']['deals'][0])
    jump['step'] = 's27'  # шаг меняем, invoicePaid не ставим и payToConfirm нет
    denied = _put(client, before, jump)
    assert denied.status_code == 409, denied.json
    assert _get(client) == before


# (d) операционист подделывает payout/closed напрямую, не проходя s26.
def test_operator_cannot_close_via_closed_flag_bypassing_gate(board):
    client, role, seed = board
    seed(_leasehold_deal('s26'))
    role['value'] = 'operator'
    before = _get(client)
    sneaky = copy.deepcopy(before['data']['deals'][0])
    sneaky['closed'] = True
    sneaky['closeReason'] = 'Успешно завершена'
    denied = _put(client, before, sneaky)
    assert denied.status_code == 409, denied.json


# (f) менеджер на раннем черновике (s5) пытается одним PUT поменять денежное
# поле чужого шага (invoiceUsd) вместе с черновиком — должно блокироваться,
# т.к. invoiceUsd не входит в набор разрешённых draft-полей и owner на s5 — operator.
def test_manager_early_put_cannot_touch_money_field(board):
    client, role, seed = board
    deal = {'id': 9002, 'code': 'QA-MONEY', 'client': 'QA Money',
            'type': 'Оплата недвижимости', 'kind': 'Лизхолд', 'step': 's5',
            'payType': 'По реквизитам', 'log': [], 'pay': {}, 'docs': {},
            'files': {}, 'docMeta': {}, 'invoiceUsd': 1000}
    seed(deal)
    role['value'] = 'manager'
    before = _get(client)
    sneaky = copy.deepcopy(before['data']['deals'][0])
    sneaky['invoiceUsd'] = 999999
    sneaky['_managerDraft'] = {'comment': 'легитимный черновик'}
    denied = _put(client, before, sneaky)
    assert denied.status_code == 409, denied.json


# (f) менеджер на раннем черновике не может продвинуть чужой шаг (step) в том
# же PUT, что и черновик.
def test_manager_early_put_cannot_advance_foreign_step(board):
    client, role, seed = board
    deal = {'id': 9003, 'code': 'QA-STEP', 'client': 'QA Step',
            'type': 'Оплата недвижимости', 'kind': 'Лизхолд', 'step': 's5',
            'payType': 'По реквизитам', 'log': [], 'pay': {}, 'docs': {},
            'files': {}, 'docMeta': {}}
    seed(deal)
    role['value'] = 'manager'
    before = _get(client)
    sneaky = copy.deepcopy(before['data']['deals'][0])
    sneaky['step'] = 's6'
    sneaky['_managerDraft'] = {'comment': 'черновик'}
    denied = _put(client, before, sneaky)
    assert denied.status_code == 409, denied.json


# (f) менеджер не может редактировать чужие документы клиента до s8 напрямую
# (мимо _managerDraft) — документы клиента правит менеджер, но при этом до s8
# публикация должна идти через draft, а прямая правка d.docs на чужом шаге
# запрещена смешиванием owner-правила и client-docs-правила.
def test_manager_cannot_publish_client_docs_directly_before_s8(board):
    client, role, seed = board
    deal = {'id': 9004, 'code': 'QA-DOCS', 'client': 'QA Docs',
            'type': 'Оплата недвижимости', 'kind': 'Лизхолд', 'step': 's5',
            'payType': 'По реквизитам', 'log': [], 'pay': {}, 'docs': {},
            'files': {}, 'docMeta': {}}
    seed(deal)
    role['value'] = 'manager'
    before = _get(client)
    sneaky = copy.deepcopy(before['data']['deals'][0])
    sneaky['docs'] = {'pass': True}
    sneaky['files'] = {'pass': [{'file': 'p.pdf', 'data': 'AAAA', 'bytes': 4, 'at': 1}]}
    denied = _put(client, before, sneaky)
    assert denied.status_code == 409, denied.json


# (g) foreign deal с реальным изменением поля из другой роли -> 409, но пустой
# no-op PUT (весь board resend без изменений) -> 200.
def test_full_board_noop_put_with_multiple_foreign_deals_ok(board):
    client, role, seed = board
    op_deal = _leasehold_deal('s26')
    mgr_deal_1 = dict(_leasehold_deal('s15'), id=9005, reqTask='open')
    mgr_deal_2 = dict(_leasehold_deal('s6'), id=9006, reqTask='done')
    seed({'deals': [op_deal, mgr_deal_1, mgr_deal_2], 'convs': [], 'wallets': [], 'notes': []})
    role['value'] = 'operator'
    before = _get(client)
    same = copy.deepcopy(before['data'])
    saved = client.put('/api/stand/state', json={'version': before['version'], 'data': same})
    assert saved.status_code == 200, saved.json


def test_full_board_real_edit_of_one_foreign_deal_still_409(board):
    client, role, seed = board
    op_deal = _leasehold_deal('s26')
    mgr_deal = dict(_leasehold_deal('s6'), id=9007, reqTask='done')
    seed({'deals': [op_deal, mgr_deal], 'convs': [], 'wallets': [], 'notes': []})
    role['value'] = 'operator'
    before = _get(client)
    edited = copy.deepcopy(before['data'])
    edited['deals'][1]['client'] = 'изменено оператором нелегально'
    denied = client.put('/api/stand/state', json={'version': before['version'], 'data': edited})
    assert denied.status_code == 409, denied.json


def _freehold_deal(step='s25', **extra):
    deal = {'id': 9010, 'code': 'QA-FH-1', 'client': 'QA Freehold Review',
            'type': 'Оплата недвижимости', 'kind': 'Фрихолд', 'step': step,
            'payType': 'Крипта', 'curBase': 'usdt', 'invoiceUsd': 45000,
            'ippsTariff': 'bank', 'postConv': 'ipps_swift',
            'serverTransferComplete': True,
            'transfer': {'addr': 'TQgQCBXkewuW4RoieDKFP9Ko2SopBh8jso',
                         'net': 'TRC-20', 'amount': 45410, 'sends': []},
            'log': [], 'pay': {}, 'payout': {}, 'docs': {}, 'files': {}, 'docMeta': {},
            'payTo': {'dev': 'Developer', 'bank': 'Bank', 'swift': 'TESTTHBK',
                      'acc': '123456', 'purpose': 'invoice INV-1', 'amount': 45000},
            'reqTask': 'done'}
    deal.update(extra)
    return deal


def test_freehold_step_jump_past_s25_without_ipps_sent_flag(board):
    client, role, seed = board
    seed(_freehold_deal('s25', amountUsdt=45410))
    role['value'] = 'operator'
    before = _get(client)
    jump = copy.deepcopy(before['data']['deals'][0])
    jump['step'] = 's26'  # ippsSent никогда не выставляем
    result = _put(client, before, jump)
    print('FREEHOLD JUMP RESULT', result.status_code, result.json)


def test_jump_to_s27_without_confirmation_is_rejected(board):
    """Прыжок s26→s27 без подтверждения реквизитов отклоняется: закрыть сделку, минуя
    оплату и менеджера, этим путём нельзя (QA 30.09)."""
    client, role, seed = board
    seed(_leasehold_deal('s26'))
    role['value'] = 'operator'
    before = _get(client)
    jump = copy.deepcopy(before['data']['deals'][0])
    jump['step'] = 's27'
    jumped = _put(client, before, jump)
    assert jumped.status_code in (403, 409), jumped.json
    assert _get(client)['data']['deals'][0]['step'] == 's26'
