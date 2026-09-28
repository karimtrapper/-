"""Серверная часть фрихолда без батов (спека 2026-09-28-freehold-no-baht.md).

Проверка QA от 28.09 (thr_brbpxp86sy):
- БЛОКЕР №9: подтверждённый перевод ipps_swift должен продвигать s24→s25,
  как Coins у лизхолда — иначе сделка застревает на s24 навсегда.
- ДЕНЬГИ №13: инвойс/тариф IPPS/наценка фиксируются с шага «Подготовить
  договор» (s11) — сервер обязан держать это сам, а не полагаться на readonly
  в браузере.

Тесты по образцу tests/test_stand_transfers.py: _stand_settle_verified()
и preserve_server_fields() вызываются напрямую на чистых фикстурах, без
поднятия отдельного процесса — так тестируется вся остальная логика стенда
в этом файле (`board()`/`_stand_guard_transition`), и это тот же код, который
исполняется в реальном STAND_MODE процессе.
"""

import json
import copy

import pytest

import app as appmod
from stand_transfers import preserve_server_fields, FREEHOLD_LOCKED_STEPS


FROM = 'TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn'
IPPS_WALLET = 'TQgQCBXkewuW4RoieDKFP9Ko2SopBh8jso'


def freehold_board(step='s24'):
    return {
        'wallets': [{'id': 'grusha', 'addr': FROM, 'multisig': True}],
        'convs': [],
        'deals': [{
            'id': 1, 'code': 'FH-1', 'client': 'Freehold QA',
            'type': 'Оплата недвижимости', 'kind': 'Фрихолд', 'step': step,
            'postConv': 'ipps_swift', 'invoiceUsd': 45000, 'ippsTariff': 'bank',
            'walletId': 'grusha', 'demoTransfers': True,
            'transfer': {'addr': IPPS_WALLET, 'amount': 45410, 'net': 'TRC-20', 'sends': [
                {'ref': 'demo:1:1', 'hash': None, 'net': 'TRC-20',
                 'amount': 45410, 'status': 'pending'}]},
            'pay': {}, 'payout': {}, 'payTo': {}, 'docs': {}, 'log': [],
        }],
        'notes': [],
    }


def test_freehold_transfer_confirmation_advances_s24_to_s25():
    state = freehold_board()
    members = state['deals']

    appmod._stand_settle_verified(state, members)
    assert members[0]['step'] == 's24', 'без подтверждения перевода шаг не двигается'
    assert not members[0].get('serverTransferComplete')

    members[0]['transfer']['sends'][0].update(status='confirmed', verifiedAmount=45410)
    appmod._stand_settle_verified(state, members)

    assert members[0]['step'] == 's25', 'подтверждённый IPPS-перевод продвигает s24→s25, как Coins у лизхолда'
    assert members[0]['serverTransferComplete'] is True
    assert members[0]['mfPayout'][0]['amount'] == 45410
    assert members[0]['mfPayout'][0]['hash'] == 'demo:1:1'
    assert members[0]['payout']['usdt'] == 45410

    # Уведомление про заявку в IPPS, а не «известите Coins» (QA №8/№9)
    texts = [n.get('text', '') for n in state['notes']]
    assert any('IPPS' in t for t in texts)
    assert not any('Coins' in t for t in texts)

    # Повторный вызов не плодит второе уведомление и не двигает шаг дальше
    notes_before = len(state['notes'])
    appmod._stand_settle_verified(state, members)
    assert len(state['notes']) == notes_before
    assert members[0]['step'] == 's25'


def test_freehold_transfer_confirmation_requires_full_amount():
    """Частичное подтверждение (меньше S) не продвигает шаг — как у Coins."""
    state = freehold_board()
    members = state['deals']
    members[0]['transfer']['sends'][0].update(status='confirmed', verifiedAmount=100)
    appmod._stand_settle_verified(state, members)
    assert members[0]['step'] == 's24'


def test_leasehold_coins_confirmation_still_advances_s24_to_s25():
    """Регресс: лизхолд Coins по-прежнему s24→s25 — тот же код путь для обоих."""
    state = {
        'wallets': [{'id': 'grusha', 'addr': FROM, 'multisig': True}],
        'convs': [{'id': 9, 'walletId': 'grusha', 'sources': [{'dealId': 2, 'rub': 350000}], 'txs': []}],
        'deals': [{
            'id': 2, 'code': 'LH-1', 'cnvId': 9, 'type': 'Оплата недвижимости', 'kind': 'Лизхолд',
            'step': 's24', 'postConv': 'coins', 'amountThb': 350000,
            'transfer': {'addr': 'x', 'amount': 11217.95, 'net': 'TRC-20', 'sends': [
                {'ref': 'demo:2:1', 'hash': None, 'net': 'TRC-20',
                 'amount': 11217.95, 'status': 'confirmed', 'verifiedAmount': 11217.95}]},
            'pay': {}, 'payout': {}, 'log': [],
        }],
        'notes': [],
    }
    appmod._stand_settle_verified(state, state['deals'])
    assert state['deals'][0]['step'] == 's25'
    assert any('известите Coins' in n.get('text', '') for n in state['notes'])


def test_freehold_fields_locked_from_s11_onward():
    """ДЕНЬГИ №13: инвойс/тариф/наценка после s11 — клиентская правка не проходит."""
    old = freehold_board(step='s12')
    old['deals'][0]['freeholdMarkupPct'] = None
    new = json.loads(json.dumps(old))
    new['deals'][0]['invoiceUsd'] = 99999
    new['deals'][0]['ippsTariff'] = 'soft'
    new['deals'][0]['freeholdMarkupPct'] = 5

    preserve_server_fields(old, new)

    assert new['deals'][0]['invoiceUsd'] == 45000, 'инвойс зафиксирован с s11'
    assert new['deals'][0]['ippsTariff'] == 'bank', 'тариф зафиксирован с s11'
    assert new['deals'][0]['freeholdMarkupPct'] is None, 'наценка зафиксирована (и её отсутствие тоже)'


@pytest.mark.parametrize('step', sorted(FREEHOLD_LOCKED_STEPS))
def test_freehold_fields_locked_on_every_locked_step(step):
    old = freehold_board(step=step)
    new = json.loads(json.dumps(old))
    new['deals'][0]['invoiceUsd'] = 1
    preserve_server_fields(old, new)
    assert new['deals'][0]['invoiceUsd'] == 45000, f'шаг {step} должен блокировать правку инвойса'


def test_freehold_fields_editable_before_s11():
    """До договора (s6/s8) правка инвойса/тарифа проходит — блокировки нет."""
    for step in ('s5', 's6', 's8'):
        old = freehold_board(step=step)
        new = json.loads(json.dumps(old))
        new['deals'][0]['invoiceUsd'] = 40000
        new['deals'][0]['ippsTariff'] = 'soft'
        preserve_server_fields(old, new)
        assert new['deals'][0]['invoiceUsd'] == 40000, f'до s11 (шаг {step}) правка должна проходить'
        assert new['deals'][0]['ippsTariff'] == 'soft'


def test_leasehold_untouched_by_freehold_field_lock():
    """Регресс: у лизхолда (не фрихолд) блокировка не применяется вообще."""
    old = {'deals': [{'id': 3, 'kind': 'Лизхолд', 'step': 's12', 'amountThb': 350000,
                      'transfer': {}, 'pay': {}}]}
    new = json.loads(json.dumps(old))
    new['deals'][0]['amountThb'] = 400000
    preserve_server_fields(old, new)
    assert new['deals'][0]['amountThb'] == 400000


def test_put_endpoint_silently_preserves_invoice_after_s11(monkeypatch):
    """Тест ДЕНЬГИ №13 буквально: PUT доски с изменённым invoiceUsd на s12/s27
    → сервер сохраняет прежнее значение, PUT не отклоняется целиком."""
    monkeypatch.setattr(appmod, 'STAND_MODE', True)
    monkeypatch.setattr(appmod, 'current_role', lambda: 'admin')
    monkeypatch.setenv('LOCAL_NO_AUTH', '1')
    appmod._stand_migrate()
    for step in ('s12', 's27'):
        state = freehold_board(step=step)
        db = appmod.get_session()
        try:
            row = appmod._stand_row(db)
            row.data = json.dumps(state)
            row.version = (row.version or 0) + 1
            db.commit()
        finally:
            db.close()
        with appmod.app.test_client() as client:
            db = appmod.get_session()
            try:
                user = db.query(appmod.AdminUser).filter_by(username='freehold_lock_test').first()
                if not user:
                    user = appmod.AdminUser(username='freehold_lock_test', role='admin',
                                            password_hash=appmod.AdminUser.hash_password('test'))
                    db.add(user); db.commit()
                uid = user.id
            finally:
                db.close()
            with client.session_transaction() as sess:
                sess['user_id'] = uid
            before = client.get('/api/stand/state')
            payload = before.json['data']
            payload['deals'][0]['invoiceUsd'] = 12345
            payload['deals'][0]['ippsTariff'] = 'soft'
            put = client.put('/api/stand/state',
                             json={'version': before.json['version'], 'data': payload})
            assert put.status_code == 200, f'шаг {step}: PUT не должен отклоняться целиком'
            after = client.get('/api/stand/state')
        assert after.json['data']['deals'][0]['invoiceUsd'] == 45000, (
            f'шаг {step}: сервер должен сохранить прежний инвойс')
        assert after.json['data']['deals'][0]['ippsTariff'] == 'bank', (
            f'шаг {step}: сервер должен сохранить прежний тариф')


def freehold_doc_deal(invoice_currency='usd', invoice_thb=None):
    """Рублёвый фрихолд на s11 — минимальный набор F для _stand_doc_request().

    X=45000 $ (invoiceUsd) ведёт всю сделку независимо от валюты инвойса
    застройщика; курс rate=82,4531 подобран так, что pay=X*rate точно сходится
    с проверкой курса в _stand_doc_request (иначе rate_mismatch).
    """
    deal = {
        'id': 1, 'code': 'FH-1', 'client': 'Freehold Doc QA',
        'type': 'Оплата недвижимости', 'kind': 'Фрихолд', 'step': 's11',
        'payType': 'По реквизитам', 'curBase': 'fhusd',
        'invoiceUsd': 45000, 'ippsTariff': 'bank',
        'invoiceCurrency': invoice_currency, 'invoiceThb': invoice_thb,
        'rates': {'client': '82,4531'},
        'docFields': {}, 'docParse': {}, 'pay': {}, 'payout': {}, 'payTo': {}, 'docs': {}, 'log': [],
    }
    state = {'wallets': [], 'convs': [], 'deals': [deal], 'notes': []}
    F = {
        'fio': 'Тестов Тест Тестович', 'passNo': '1234 567890',
        'purpose': 'Оплата по инвойсу застройщика', 'invNo': 'INV-1',
        'dev': 'ACME Developer Co Ltd', 'object': 'Villa 1',
        'amountThb': '45000', 'amountPay': '3710389.50', 'rate': '82.4531',
        'payTo': 'Bank · 1234567890',
    }
    return state, deal, F


def test_doc_request_usd_invoice_marks_thb_block_not_applicable():
    """Инвойс в USD: rate_source/usd_equivalent/thb_credit_status/developer_confirmation
    получают «Н/П» (пакет годен для выдачи — поправка автора спеки, 28.09),
    а «Обязательство по инвойсу застройщика» показывает саму сумму в USD."""
    state, deal, F = freehold_doc_deal(invoice_currency='usd')
    req = appmod._stand_doc_request(state, deal, F)
    assert 'error' not in req, req
    assert req['fields']['invoice_currency'] == 'USD'
    assert req['fields']['invoice_amount'] == '45000'
    assert req['money']['rate_source'].startswith('Н/П')
    assert req['money']['usd_equivalent'] == '45000'
    assert req['money']['thb_credit_status'].startswith('Н/П')
    assert req['money']['developer_confirmation']


def test_doc_request_thb_invoice_leaves_conversion_block_untouched():
    """Инвойс в THB: «Обязательство по инвойсу застройщика» — реальная сумма
    в ฿, а конверсионный блок (курс/срок, USD-эквивалент, статус зачёта,
    письмо застройщика) НЕ заполняется — остаётся [●] в шаблоне для ручного
    заполнения (чтобы документ не врал, решение Карима 28.09: «больше ничего»)."""
    state, deal, F = freehold_doc_deal(invoice_currency='thb', invoice_thb='1500000')
    req = appmod._stand_doc_request(state, deal, F)
    assert 'error' not in req, req
    assert req['fields']['invoice_currency'] == 'THB'
    assert req['fields']['invoice_amount'] == '1500000'
    for key in ('rate_source', 'usd_equivalent', 'thb_credit_status', 'developer_confirmation'):
        assert key not in req['money'], f'{key} не должен заполняться при THB-инвойсе'


def test_doc_request_thb_invoice_still_driven_by_usd_x():
    """X (invoiceUsd) продолжает вести всю сделку в THB-режиме — курс/сумма
    клиенту считаются от X, батовая сумма нигде в money() не участвует."""
    state, deal, F = freehold_doc_deal(invoice_currency='thb', invoice_thb='1500000')
    req = appmod._stand_doc_request(state, deal, F)
    assert 'error' not in req, req
    assert req['money']['transfer_amount'] == '45000'
    assert req['money']['rate'] == '82.4531'
    assert '1500000' not in json.dumps(req['money']), 'батовая сумма не должна попадать в money()'


@pytest.mark.parametrize('change', [
    lambda s: s['deals'][0].update(step='s22'),
    lambda s: s['deals'][0].update(closed=False),
    lambda s: s['deals'].clear(),
    lambda s: s['deals'][0].update(postConv='coins'),
    lambda s: s['deals'][0].update(cnvId=10),
    lambda s: s['deals'][0]['transfer'].update(addr=FROM),
    lambda s: s['deals'][0]['transfer'].update(amount=1),
    lambda s: s['deals'][0].update(payout={}),
    lambda s: s['deals'][0].update(crmDealId=None),
    lambda s: s['deals'][0].update(closeReason='Не обращение'),
    lambda s: s['deals'][0]['pay'].update(invoicePaid=False),
    lambda s: s['convs'][0]['sources'][0].update(usdt=0, usdtFact=0),
    lambda s: s['convs'][0]['sources'].clear(),
    lambda s: s['convs'][0]['sources'].append(copy.deepcopy(s['convs'][0]['sources'][0])),
    lambda s: s['convs'].clear(),
    lambda s: s['convs'][0].update(walletId='other'),
])
def test_confirmed_freehold_put_rejected_atomically(monkeypatch, change):
    monkeypatch.setattr(appmod, 'STAND_MODE', True)
    monkeypatch.setattr(appmod, 'current_role', lambda: 'admin')
    monkeypatch.setenv('LOCAL_NO_AUTH', '1')
    appmod._stand_migrate()
    state = freehold_board(step='done')
    deal = state['deals'][0]
    deal.update(cnvId=9, closed=True, crmDealId=123, serverTransferComplete=True)
    deal['transfer']['sends'][0].update(hash='demo:send:1', status='confirmed', verifiedAmount=45410)
    deal['payout'] = {'hash': 'demo:send:1', 'usdt': 45410}
    state['convs'] = [{'id': 9, 'walletId': 'grusha', 'sources': [
        {'dealId': 1, 'rub': 3710389.5, 'usdt': 45410, 'usdtFact': 45410}],
        'txs': [{'hash': 'demo:incoming:9:one', 'net': 'TRC-20',
                 'status': 'confirmed', 'amount': 45410, 'demo': True}]}]
    db = appmod.get_session()
    try:
        row = appmod._stand_row(db)
        row.data = json.dumps(state)
        row.version = (row.version or 0) + 1
        user = db.query(appmod.AdminUser).filter_by(username='freehold_guard_test').first()
        if not user:
            user = appmod.AdminUser(username='freehold_guard_test', role='admin',
                                    password_hash=appmod.AdminUser.hash_password('test'))
            db.add(user)
        db.commit()
        uid = user.id
        crm_count = db.query(appmod.Deal).count()
    finally:
        db.close()
    with appmod.app.test_client() as client:
        with client.session_transaction() as sess:
            sess['user_id'] = uid
        before = client.get('/api/stand/state').json
        proposed = copy.deepcopy(before['data'])
        change(proposed)
        response = client.put('/api/stand/state', json={'version': before['version'], 'data': proposed})
        after = client.get('/api/stand/state').json
    assert response.status_code == 409, response.json
    assert after['version'] == before['version']
    assert after['data'] == before['data']
    db = appmod.get_session()
    try:
        assert db.query(appmod.Deal).count() == crm_count
    finally:
        db.close()


def test_confirmed_freehold_forward_steps_and_invoice_payout():
    old = freehold_board(step='s25')
    deal = old['deals'][0]
    deal['serverTransferComplete'] = True
    deal['transfer']['sends'][0].update(hash='demo:send:1', status='confirmed', verifiedAmount=45410)
    deal['payout'] = {'hash': 'demo:send:1', 'usdt': 45410}
    deal['pay']['outHash'] = 'demo:send:1'
    for step in ('s26', 's27', 'done'):
        new = copy.deepcopy(old)
        next_deal = new['deals'][0]
        next_deal['step'] = step
        if step == 's27':
            next_deal['payout']['invoice'] = {'source': 'IPPS (SWIFT)', 'usd': 45000}
            next_deal['pay']['invoicePaid'] = True
        if step == 'done':
            next_deal['closed'] = True
            next_deal['crmDealId'] = 123
        assert appmod._stand_guard_transition(old, new, 'admin',
                 allow_crm_close=(step == 'done')) is None
        old = new
    assert appmod._stand_guard_transition(old, copy.deepcopy(old), 'admin') is None


@pytest.mark.parametrize('stage', ['s11', 'closed', 'confirmed'])
@pytest.mark.parametrize('field,value', [
    ('invoiceUsd', 0), ('invoiceUsd', '46000'),
    ('ippsTariff', 'soft'), ('ippsTariff', ''),
    ('invoiceCurrency', 'thb'), ('invoiceCurrency', ''),
    ('invoiceThb', 1500000), ('invoiceThb', '1500000'),
])
def test_t17_freehold_invoice_basis_rejected_before_preserve(stage, field, value):
    """T11 preserve_server_fields restores s11 edits, while the stand_state
    guard must reject each attempted money edit atomically before that restore.
    The stage set comes from stand_transfers.FREEHOLD_LOCKED_STEPS, shared by
    the server guard and T11 preservation; UI disabling is only a convenience.
    """
    old = freehold_board(step='s11' if stage == 's11' else 's8')
    deal = old['deals'][0]
    deal.update(invoiceCurrency='usd', invoiceThb=None)
    if stage == 'closed':
        deal['closed'] = True
    elif stage == 'confirmed':
        deal['transfer']['sends'][0]['status'] = 'confirmed'
    new = copy.deepcopy(old)
    new['deals'][0][field] = value
    assert appmod._stand_guard_transition(old, new, 'admin')
    assert appmod._stand_guard_transition(old, copy.deepcopy(old), 'admin') is None
    notes_only = copy.deepcopy(old)
    notes_only['deals'][0]['notes'] = 'allowed'
    assert appmod._stand_guard_transition(old, notes_only, 'admin') is None


def test_t17_legacy_freehold_missing_invoice_fields_identity_and_note():
    """Old issued documents may not contain the later THB/currency fields."""
    old = freehold_board(step='s11')
    old['deals'][0].pop('ippsTariff')
    old['deals'][0].pop('invoiceCurrency', None)
    old['deals'][0].pop('invoiceThb', None)
    unchanged = copy.deepcopy(old)
    unchanged['deals'][0]['notes'] = 'only a note'
    assert appmod._stand_guard_transition(old, unchanged, 'admin') is None
    preserve_server_fields(old, unchanged)
    for key in ('ippsTariff', 'invoiceCurrency', 'invoiceThb'):
        assert key not in unchanged['deals'][0]
    introduced = copy.deepcopy(old)
    introduced['deals'][0]['invoiceCurrency'] = 'usd'
    assert appmod._stand_guard_transition(old, introduced, 'admin')


def test_closed_freehold_accepts_only_empty_hashes_normalization():
    """Загрузка доски добавляет hashes=[], но подтверждённые деньги не меняет."""
    state = freehold_board(step='s24')
    deal = state['deals'][0]
    deal['transfer']['sends'][0].update(hash='demo:send:1', status='confirmed',
                                         verifiedAmount=45410)
    appmod._stand_settle_verified(state, state['deals'])
    assert deal['step'] == 's25'
    assert deal['serverTransferComplete'] is True
    assert deal['payout']['hashes'] == [
        {'hash': 'demo:send:1', 'amount': 45410, 'network': 'TRC20'}]

    # Legacy payout без hashes: текущий автопуть выше создаёт hashes, но
    # старое состояние могло сохраниться без необязательного поля.
    del deal['payout']['hashes']
    # Закрытие здесь — фикстура guard: денежный payout выше создал сервер.
    deal.update(step='done', closed=True, crmDealId=123)
    normalized = copy.deepcopy(state)
    normalized['deals'][0]['payout']['hashes'] = []
    normalized['notes'].append({'id': 3, 'text': 'Новая заметка'})
    normalized['deals'].append({'id': 2, 'step': 's4', 'kind': 'Обмен'})
    assert appmod._stand_guard_transition(state, normalized, 'admin') is None
    assert appmod._stand_guard_transition(normalized, copy.deepcopy(state), 'admin') is None

    for change in (
            lambda p: p['hashes'].append({'hash': 'fake', 'amount': 45410}),
            lambda p: p.update(usdt=1),
            lambda p: p.update(hash='fake'),
            lambda p: p.update(route='fake')):
        attack = copy.deepcopy(normalized)
        change(attack['deals'][0]['payout'])
        assert appmod._stand_guard_transition(state, attack, 'admin')

    with_hash = copy.deepcopy(state)
    with_hash['deals'][0]['payout']['hashes'] = [{'hash': 'confirmed', 'amount': 45410}]
    for hashes in ([], [{'hash': 'fake', 'amount': 45410}]):
        attack = copy.deepcopy(with_hash)
        attack['deals'][0]['payout']['hashes'] = hashes
        assert appmod._stand_guard_transition(with_hash, attack, 'admin')
    attack = copy.deepcopy(with_hash)
    del attack['deals'][0]['payout']['hashes']
    assert appmod._stand_guard_transition(with_hash, attack, 'admin')


def test_legacy_closed_freehold_board_put_and_rejection_are_atomic(monkeypatch):
    """Штатный PUT всей доски проходит, денежный PUT отклоняется без записи."""
    monkeypatch.setattr(appmod, 'STAND_MODE', True)
    monkeypatch.setenv('LOCAL_NO_AUTH', '1')
    state = freehold_board(step='done')
    deal = state['deals'][0]
    deal.update(closed=True, crmDealId=123, serverTransferComplete=True)
    deal['payout'] = {'hash': 'demo:send:1', 'usdt': 45410}
    deal['mfPayout'] = [{'hash': 'demo:send:1', 'amount': 45410}]
    deal['pay']['outHash'] = 'demo:send:1'
    deal['transfer']['sends'][0].update(hash='demo:send:1', status='confirmed',
                                         verifiedAmount=45410)
    state['convs'] = [{'id': 9, 'walletId': 'grusha', 'sources': [
        {'dealId': 1, 'rub': 3710389.5, 'usdt': 45410, 'usdtFact': 45410}], 'txs': []}]
    deal['cnvId'] = 9
    appmod._stand_migrate()
    db = appmod.get_session()
    try:
        row = appmod._stand_row(db)
        row.data = json.dumps(state)
        row.version = (row.version or 0) + 1
        user = db.query(appmod.AdminUser).filter_by(username='t11c_guard_test').first()
        if not user:
            user = appmod.AdminUser(username='t11c_guard_test', role='admin',
                                    password_hash=appmod.AdminUser.hash_password('test'))
            db.add(user)
        db.commit()
        uid = user.id
        crm_count = db.query(appmod.Deal).count()
    finally:
        db.close()
    with appmod.app.test_client() as client:
        with client.session_transaction() as sess:
            sess['user_id'] = uid
        before = client.get('/api/stand/state').json
        data = copy.deepcopy(before['data'])
        data['deals'][0]['payout']['hashes'] = []  # tasks.html:migrate()
        data['deals'].append({'id': 2, 'kind': 'Обмен', 'step': 's4'})
        data['notes'].append({'id': 3, 'text': 'Несвязанная заметка'})
        ok = client.put('/api/stand/state', json={'version': before['version'], 'data': data})
        assert ok.status_code == 200, ok.json
        after = client.get('/api/stand/state').json
        assert after['data']['notes'][-1]['text'] == 'Несвязанная заметка'
        assert after['data']['deals'][-1]['id'] == 2
        assert after['data']['deals'][0]['payout']['usdt'] == 45410
        assert after['data']['deals'][0]['crmDealId'] == 123
        assert after['data']['deals'][0]['closed'] is True
        assert client.put('/api/stand/state', json={
            'version': after['version'], 'data': after['data']}).status_code == 200
        after = client.get('/api/stand/state').json
        for change in (
                lambda s: s['deals'][0]['payout'].update(hashes=[{'hash': 'fake'}]),
                lambda s: s['deals'][0]['payout'].update(usdt=1),
                lambda s: s['deals'][0]['payout'].update(hash='fake'),
                lambda s: s['deals'][0].update(step='s25'),
                lambda s: s['deals'][0].update(closed=False),
                lambda s: s['deals'][0].update(crmDealId=999),
                lambda s: s['deals'][0]['transfer'].update(addr='fake'),
                lambda s: s['deals'][0]['transfer'].update(net='ERC-20'),
                lambda s: s['deals'][0].update(walletId='fake'),
                lambda s: s['deals'][0].update(postConv='coins'),
                lambda s: s['convs'][0]['sources'][0].update(usdt=1),
                lambda s: s['convs'][0]['sources'][0].update(usdtFact=1)):
            attack = copy.deepcopy(after['data'])
            change(attack)
            denied = client.put('/api/stand/state', json={
                'version': after['version'], 'data': attack})
            assert denied.status_code == 409, denied.json
            assert client.get('/api/stand/state').json == after
    db = appmod.get_session()
    try:
        assert db.query(appmod.Deal).count() == crm_count
    finally:
        db.close()


def test_mixed_accepted_batch_protects_exchange_member_route():
    old = freehold_board(step='s23')
    old['deals'][0].update(cnvId=9)
    old['deals'].append({'id': 2, 'code': 'EX-2', 'kind': 'Обмен', 'step': 'pack',
                         'cnvId': 9, 'postConv': 'coins', 'transfer': {'amount': 100},
                         'pay': {}, 'payout': {}})
    old['convs'] = [{'id': 9, 'walletId': 'grusha', 'sources': [
        {'dealId': 1, 'rub': 3710389.5, 'usdt': 45410},
        {'dealId': 2, 'rub': 8000, 'usdt': 100}], 'txs': []}]
    for change in (lambda s: s['deals'].pop(),
                   lambda s: s['deals'][1].update(postConv='keep'),
                   lambda s: s['convs'][0]['sources'][1].update(usdt=0)):
        new = copy.deepcopy(old)
        change(new)
        assert appmod._stand_guard_transition(old, new, 'admin')
