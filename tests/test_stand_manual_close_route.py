"""HTTP-маршрут stand_crm_close с manualOverride (СД-1489): Task 2 даёт чистую
функцию _stand_manual_close_apply_override, этот файл проверяет её проводку
через реальный роут — права доступа, маппинг коды ошибки -> HTTP статус, и что
штатный путь (s27, originMode=='manual') и /crm-close-lose не затронуты.

Паттерн HTTP-вызова — как в tests/test_stand_crm_close_atomic.py; проверка
идемпотентности пост-эффектов — как в tests/test_stand_crm_close_notifications.py.

Запуск: python3 scripts/run_fenced_pytest.py tests/test_stand_manual_close_route.py -v
"""
import json
import secrets

import app as m
import pytest

pytestmark = pytest.mark.usefixtures('stand_demo_environment')

REASON = 'Клиент на связи, перевёл через кассу — проверено вручную менеджером'


def confirmed_echo(ref, network, sender, receiver, amount, **kwargs):
    """Фейковый verify: подтверждает перевод суммой, которую ему передали —
    без обращения к сети (как в tests/test_stand_manual_close_override.py)."""
    return {'status': 'confirmed', 'verifiedAmount': float(100 if amount is None else amount),
            'verifiedAt': '2026-01-01T00:00:00Z', 'from': sender or 'TSenderWallet11111111111111'}


def _early_board(**overrides):
    """Сделка на раннем шаге (как СД-1489) — без чека, без sentToClient."""
    deal = {
        'id': 1489, 'code': 'СД-1489', 'client': 'Synthetic T31',
        'type': 'Обмен валюты', 'step': 's14', 'closed': False,
        'crmDealId': None, 'sentToClient': False, 'pay': {},
        'files': {'receipt': [{'file': 'receipt.pdf', 'mime': 'application/pdf',
                               'data': 'data:application/pdf;base64,JVBERi0='}]},
        'payinHashes': [], 'log': [],
    }
    deal.update(overrides)
    return {'deals': [deal], 'notes': [], 'convs': []}


def _s27_board(**overrides):
    """Сделка на s27 с уже известными фактами (крипто-приход уже верифицирован
    и лежит в payinHashes этой же сделки, расход по кассе с чеком) — не хватает
    только причины ручного переноса. Override переподтверждает тот же, уже
    записанный на эту сделку хеш: это не повторное использование (дедуп
    исключает собственную сделку), а именно «почти всё уже известно»."""
    deal = {
        'id': 1489, 'code': 'СД-1489', 'client': 'Synthetic T31',
        'type': 'Обмен валюты', 'step': 's27', 'closed': False,
        'crmDealId': None, 'sentToClient': True, 'pay': {},
        'payType': 'Крипта', 'amountUsdt': 100,
        'payinHashes': [{'hash': 'a' * 64, 'network': 'TRC20', 'amount': 100,
                         'from': 'TSenderWallet11111111111111', 'to': 'TReceiverWallet111111111111',
                         'verified': True, 'verifiedAt': '2026-01-01T00:00:00Z'}],
        'paySrc': 'cash', 'payout': {'usdt': 90},
        'files': {'receipt': [{'file': 'receipt.pdf', 'mime': 'application/pdf',
                               'data': 'data:application/pdf;base64,JVBERi0='}]},
        'log': [],
    }
    deal.update(overrides)
    return {'deals': [deal], 'notes': [], 'convs': []}


def _override(**overrides):
    override = {
        'reason': REASON,
        'payin': {'method': 'Крипта', 'amountUsdt': 100, 'hashes': [
            {'hash': 'a' * 64, 'network': 'trc20',
             'sender': 'TSenderWallet11111111111111', 'receiver': 'TReceiverWallet111111111111', 'amount': 100}]},
        'payout': {'source': 'cash', 'amountUsdt': 90},
    }
    override.update(overrides)
    return override


def _crm(**overrides):
    crm = {
        'deal_kind': 'exchange', 'client_name': 'Synthetic T31', 'manager_name': 'Елизавета',
        'payin_method': 'crypto_direct', 'payin_amount_usdt': 100,
        'payin_tx_hashes': [{'hash': 'a' * 64, 'network': 'TRC20', 'amount_usdt': 100}],
        'payout_method': 'transfer', 'payout_source': 'cash_batch', 'payout_amount_usdt': 90,
    }
    crm.update(overrides)
    return crm


def _setup(board_factory=_early_board, role='manager'):
    m._stand_migrate()
    from tests.payin_registry import ensure_payin_wallet
    ensure_payin_wallet()  # получатель прихода — наш кошелёк из реестра
    db = m.get_session()
    try:
        user = m.AdminUser(username='t3-' + secrets.token_hex(6), display_name='T3 ' + role,
                           role=role, password_hash='unused')
        db.add(user)
        db.flush()
        uid = user.id
        row = db.query(m.StandState).filter_by(id=1).first()
        if row is None:
            row = m.StandState(id=1)
            db.add(row)
        row.data = json.dumps(board_factory())
        row.version = 1
        row.generation = secrets.token_hex(16)
        db.commit()
        return uid
    finally:
        db.close()


def _client(uid):
    client = m.app.test_client()
    with client.session_transaction() as sess:
        sess['user_id'] = uid
    return client


def _post(client, version=1, crm=None, override=None):
    body = {'version': version, 'crm': _crm() if crm is None else crm}
    if override is not None:
        body['manualOverride'] = override
    return client.post('/api/stand/deals/1489/crm-close', json=body)


def _counts():
    db = m.get_session()
    try:
        return db.query(m.Deal).count(), db.query(m.StandCrmLink).count()
    finally:
        db.close()


def test_override_requires_manager_or_admin_role(monkeypatch):
    monkeypatch.setattr(m, 'STAND_MODE', True)
    uid = _setup(role='operator')
    response = _post(_client(uid), override=_override())
    assert response.status_code == 403
    assert response.json['success'] is False


def test_override_rejects_missing_verified_hash(monkeypatch):
    monkeypatch.setattr(m, 'STAND_MODE', True)
    uid = _setup()
    baseline = _counts()
    override = _override(payin={'method': 'Крипта', 'amountUsdt': 100})
    response = _post(_client(uid), override=override)
    assert response.status_code == 400
    assert response.json == {'success': False, 'error': 'payin_hash_required'}
    assert _counts() == baseline
    state = _client(uid).get('/api/stand/state').json
    assert state['data']['deals'][0]['closed'] is False


def test_override_empty_dict_still_goes_through_override_branch(monkeypatch):
    """manualOverride присутствует, но пустой словарь — falsy в Python, не
    должен тихо провалиться в штатную s27-ветку (stage_or_receipt_missing):
    ключ присутствует, значит это заявка на ручной перенос, с её собственной
    ошибкой reason_required."""
    monkeypatch.setattr(m, 'STAND_MODE', True)
    uid = _setup()
    response = _post(_client(uid), override={})
    assert response.status_code == 400
    assert response.json == {'success': False, 'error': 'manual_override_reason_required'}


def test_override_closes_deal_from_early_step_as_manager(monkeypatch):
    monkeypatch.setattr(m, 'STAND_MODE', True)
    monkeypatch.setattr(m, 'verify_transfer', confirmed_echo)
    uid = _setup(role='manager')
    response = _post(_client(uid), override=_override())
    assert response.status_code == 201, response.json
    assert response.json['deal']['status'] == 'completed'
    state = _client(uid).get('/api/stand/state').json
    deal = state['data']['deals'][0]
    assert deal['step'] == 'done'
    assert deal['closed'] is True
    assert deal['closeReason'] == 'Успешно завершена'
    assert 'closeConfirmation' not in deal  # Override has its own audited reason, not s27 review.
    log_entries = [e for e in deal['log'] if isinstance(e, dict)]
    assert any(e.get('role') == 'manager' and REASON in e.get('text', '') for e in log_entries)


def test_override_closes_deal_from_early_step_as_admin(monkeypatch):
    monkeypatch.setattr(m, 'STAND_MODE', True)
    monkeypatch.setattr(m, 'verify_transfer', confirmed_echo)
    uid = _setup(role='admin')
    response = _post(_client(uid), override=_override())
    assert response.status_code == 201, response.json
    assert response.json['deal']['status'] == 'completed'
    state = _client(uid).get('/api/stand/state').json
    deal = state['data']['deals'][0]
    assert deal['step'] == 'done'
    assert deal['closed'] is True
    assert deal['closeReason'] == 'Успешно завершена'
    assert 'closeConfirmation' not in deal  # Override has its own audited reason, not s27 review.
    log_entries = [e for e in deal['log'] if isinstance(e, dict)]
    assert any(e.get('role') == 'admin' and REASON in e.get('text', '') for e in log_entries)


def test_override_closes_deal_already_at_s27(monkeypatch):
    """«Почти всё уже известно»: payin-хеш уже верифицирован и лежит в
    payinHashes этой же сделки (нормальным флоу до s27). Override
    переподтверждает ТОТ ЖЕ хеш — не новый — только причины не хватало.
    Дедуп должен исключить собственную сделку из «уже использован», иначе
    это задача не решается в принципе: форма неизбежно предзаполняет уже
    известные факты, а не просит менеджера придумать новый хеш."""
    monkeypatch.setattr(m, 'STAND_MODE', True)
    monkeypatch.setattr(m, 'verify_transfer', confirmed_echo)
    uid = _setup(board_factory=_s27_board)
    response = _post(_client(uid), override=_override())
    assert response.status_code == 201, response.json
    state = _client(uid).get('/api/stand/state').json
    deal = state['data']['deals'][0]
    assert deal['step'] == 'done'
    assert deal['closed'] is True
    # Переподтверждение собственного хеша не задваивает запись на доске.
    assert [h['hash'] for h in deal['payinHashes']].count('a' * 64) == 1


def test_override_double_submit_is_idempotent(monkeypatch):
    monkeypatch.setattr(m, 'STAND_MODE', True)
    monkeypatch.setattr(m, 'verify_transfer', confirmed_echo)
    calls = []
    real_effects = m._stand_fire_close_post_effects

    def spy(session, deal, stand_deal_id):
        calls.append(1)
        return real_effects(session, deal, stand_deal_id)

    monkeypatch.setattr(m, '_stand_fire_close_post_effects', spy)
    uid = _setup()
    baseline = _counts()
    client = _client(uid)
    first = _post(client, override=_override())
    assert first.status_code == 201, first.json
    crm_id = first.json['deal']['id']
    assert _counts() == (baseline[0] + 1, baseline[1] + 1)

    second = _post(_client(uid), version=1, override=_override())
    assert second.status_code == 200, second.json
    assert second.json['duplicate'] is True
    assert second.json['deal']['id'] == crm_id
    assert _counts() == (baseline[0] + 1, baseline[1] + 1)
    assert len(calls) == 1
    db = m.get_session()
    try:
        assert db.query(m.Deal).filter_by(id=crm_id).one().close_notified_at is not None
    finally:
        db.close()


def test_normal_s27_close_still_works_without_override(monkeypatch):
    monkeypatch.setattr(m, 'STAND_MODE', True)
    from tests.test_stand_crm_close_atomic import _setup as atomic_setup, _crm as atomic_crm
    uid = atomic_setup(monkeypatch)
    client = m.app.test_client()
    with client.session_transaction() as sess:
        sess['user_id'] = uid
    response = client.post('/api/stand/deals/1474/crm-close', json={
        'version': 1,
        'crm': atomic_crm()})
    assert response.status_code == 201, response.json
    assert response.json['deal']['status'] == 'completed'


def _manual_origin_client(monkeypatch, payin_hashes):
    monkeypatch.setattr(m, 'STAND_MODE', True)
    from tests.payin_registry import ensure_payin_wallet
    ensure_payin_wallet()  # получатель прихода — наш кошелёк реестра
    m._stand_migrate()
    db = m.get_session()
    try:
        user = m.AdminUser(username='t3manual-' + secrets.token_hex(6),
                           display_name='T3 Manual', role='manager', password_hash='unused')
        db.add(user)
        db.flush()
        uid = user.id
        deal = {
            'id': 1490, 'code': 'СД-1490', 'client': 'Synthetic Manual',
            'type': 'Обмен валюты', 'step': 'manual', 'closed': False, 'crmDealId': None,
            'sentToClient': False, 'pay': {}, 'amountUsdt': 100, 'payout': {'usdt': 90},
            'payType': 'Крипта', 'payinHashes': payin_hashes,
            'files': {}, 'log': [], 'manual': True, 'manualNew': False, 'isTask': False,
            'originMode': 'manual',
        }
        row = db.query(m.StandState).filter_by(id=1).first()
        if row is None:
            row = m.StandState(id=1)
            db.add(row)
        row.data = json.dumps({'deals': [deal], 'notes': [], 'convs': []})
        row.version = 1
        row.generation = secrets.token_hex(16)
        db.commit()
    finally:
        db.close()
    return _client(uid)


def _manual_origin_crm(tx_hash):
    return {'deal_kind': 'exchange', 'client_name': 'Synthetic Manual',
            'manager_name': 'Елизавета', 'payin_method': 'crypto_direct',
            'payin_amount_usdt': 100, 'payout_method': 'transfer',
            'payout_source': 'cash_batch', 'payout_amount_usdt': 90,
            'payin_tx_hashes': [{'hash': tx_hash, 'network': 'trc20', 'amount_usdt': 100}] if tx_hash else []}


def test_manual_origin_close_works_with_network_verified_payin_hash(monkeypatch):
    tx = secrets.token_hex(32)
    client = _manual_origin_client(monkeypatch, [
        {'hash': tx, 'net': 'TRC20', 'amount': 100, 'from': 'TSenderWallet11111111111111',
         'to': 'TReceiverWallet111111111111'}])
    seen = []
    def verify(ref, network, sender, receiver, amount, **kw):
        seen.append((ref, sender, receiver))
        return confirmed_echo(ref, network, sender, receiver, amount)
    monkeypatch.setattr(m, 'verify_transfer', verify)
    response = client.post('/api/stand/deals/1490/crm-close', json={
        'version': 1, 'crm': _manual_origin_crm(tx)})
    assert response.status_code == 201, response.json
    assert response.json['deal']['status'] == 'completed'
    # адрес получателя и отправителя не теряются при проверке сетью
    assert seen == [(tx, 'TSenderWallet11111111111111', 'TReceiverWallet111111111111')]
    # результат сети записан на доску как серверный факт прихода
    board = json.loads(m.get_session().get(m.StandState, 1).data)['deals'][0]['payinHashes'][0]
    assert board['verified'] is True and board['verifiedAt'] and board['from'] == 'TSenderWallet11111111111111'


def test_manual_origin_network_sender_is_recorded_and_payer_wallet_still_blocks(monkeypatch):
    tx = secrets.token_hex(32)
    client = _manual_origin_client(monkeypatch, [{'hash': tx, 'net': 'TRC20', 'amount': 100}])
    monkeypatch.setattr(m, 'verify_transfer', lambda ref, network, sender, receiver, amount, **kw: {
        'status': 'confirmed', 'verifiedAmount': 100.0, 'verifiedAt': '2026-10-18T12:00:00Z',
        'from': 'TNetworkSender1111111111111', 'to': 'TReceiverWallet111111111111'})
    assert client.post('/api/stand/deals/1490/crm-close', json={
        'version': 1, 'crm': _manual_origin_crm(tx)}).status_code == 201
    board = json.loads(m.get_session().get(m.StandState, 1).data)['deals'][0]['payinHashes'][0]
    assert board['from'] == 'TNetworkSender1111111111111'  # адрес отправителя — результат сети
    # Фрихолд: проверка плательщика не обходится — адрес сети против payerWallet.
    deal = {'kind': 'Фрихолд', 'payType': 'Крипта', 'payerWallet': 'TPayer111111111111111111111',
            'invoiceUsd': 100, 'ippsTariff': 'bank', 'payinHashes': [board]}
    crm = {'deal_kind': 'mf_freehold', 'payin_method': 'crypto_direct', 'payin_amount_usdt': 100}
    assert m._stand_crm_fact_problem(deal, crm, 'mf_freehold') == 'payin_basis_unverified'


def test_manual_origin_close_without_payin_hash_is_rejected(monkeypatch):
    client = _manual_origin_client(monkeypatch, [])
    monkeypatch.setattr(m, 'verify_transfer', confirmed_echo)
    response = client.post('/api/stand/deals/1490/crm-close', json={
        'version': 1, 'crm': _manual_origin_crm(None)})
    assert response.status_code == 400 and response.json['error'] == 'payin_hash_required'


def test_manual_origin_close_with_malformed_payin_hash_is_rejected(monkeypatch):
    client = _manual_origin_client(monkeypatch, [{'hash': 'not-a-hash', 'net': 'TRC20', 'amount': 100}])
    monkeypatch.setattr(m, 'verify_transfer', confirmed_echo)
    response = client.post('/api/stand/deals/1490/crm-close', json={
        'version': 1, 'crm': _manual_origin_crm(None)})
    assert response.status_code == 400 and response.json['error'] == 'payin_hash_invalid'


def test_manual_origin_close_with_unconfirmed_payin_hash_is_rejected(monkeypatch):
    tx = secrets.token_hex(32)
    client = _manual_origin_client(monkeypatch, [{'hash': tx, 'net': 'TRC20', 'amount': 100}])
    monkeypatch.setattr(m, 'verify_transfer', lambda *args, **kw: {'status': 'pending'})
    response = client.post('/api/stand/deals/1490/crm-close', json={
        'version': 1, 'crm': _manual_origin_crm(tx)})
    assert response.status_code == 422 and response.json['error'] == 'payin_hash_unverified'


def test_crm_close_lose_route_unaffected(monkeypatch):
    monkeypatch.setattr(m, 'STAND_MODE', True)
    uid = _setup()
    client = _client(uid)
    response = client.post('/api/stand/deals/1489/crm-close-lose',
                           json={'version': 1, 'reason': 'Ушёл к конкуренту'})
    assert response.status_code in (200, 201, 409)
    assert 'error' not in response.json or response.status_code != 500


# ---- контракт настоящего verify_transfer: UI хранит у хеша только сумму/сеть/хеш ----------

_B58 = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
REAL_SENDER = 'T' + ''.join(secrets.choice(_B58) for _ in range(33))
REAL_RECEIVER = 'T' + ''.join(secrets.choice(_B58) for _ in range(33))  # наш кошелёк, регистрируется в тестах


def _real_verifier(monkeypatch, tx, outputs, confirmed=True):
    from tests.payin_registry import ensure_payin_wallet
    ensure_payin_wallet(REAL_RECEIVER)
    """Настоящий stand_transfers.verify_transfer; подменён только транспорт get (без сети)."""
    from stand_transfers import verify_transfer as real, TRON_USDT

    class Response:
        status_code = 200

        def __init__(self, data):
            self._data = data

        def json(self):
            return self._data

    data = {'hash': tx, 'confirmed': confirmed, 'contractRet': 'SUCCESS', 'revert': False,
            'timestamp': 1700000001000, 'trc20TransferInfo': [
                dict({'contract_address': TRON_USDT, 'to_address': to,
                      'amount_str': str(int(amount * 1_000_000)), 'decimals': 6},
                     **({'from_address': frm} if frm else {}))
                for frm, to, amount in outputs]}
    monkeypatch.setattr(m, 'verify_transfer', lambda *a, **k: real(
        *a, get=lambda *x, **y: Response(data), **k))


def test_manual_origin_raw_ui_hash_is_verified_by_real_verifier_with_observed_addresses(monkeypatch):
    tx = secrets.token_hex(32)
    client = _manual_origin_client(monkeypatch, [{'hash': tx, 'network': 'trc20', 'amount': 100}])
    _real_verifier(monkeypatch, tx, [(REAL_SENDER, REAL_RECEIVER, 100)])
    response = client.post('/api/stand/deals/1490/crm-close', json={
        'version': 1, 'crm': _manual_origin_crm(tx)})
    assert response.status_code == 201, response.json
    saved = json.loads(m.get_session().get(m.StandState, 1).data)['deals'][0]['payinHashes'][0]
    assert saved['verified'] is True and saved['from'] == REAL_SENDER
    assert 'unknownSender' not in saved


def test_manual_origin_real_verifier_rejects_wrong_amount_and_pending(monkeypatch):
    tx = secrets.token_hex(32)
    client = _manual_origin_client(monkeypatch, [{'hash': tx, 'network': 'trc20', 'amount': 100}])
    _real_verifier(monkeypatch, tx, [(REAL_SENDER, REAL_RECEIVER, 50)])
    wrong = client.post('/api/stand/deals/1490/crm-close', json={
        'version': 1, 'crm': _manual_origin_crm(tx)})
    assert wrong.status_code == 422 and wrong.json['error'] == 'payin_amount_mismatch'
    _real_verifier(monkeypatch, tx, [(REAL_SENDER, REAL_RECEIVER, 100)], confirmed=False)
    pending = client.post('/api/stand/deals/1490/crm-close', json={
        'version': 1, 'crm': _manual_origin_crm(tx)})
    assert pending.status_code == 422 and pending.json['error'] == 'payin_hash_unverified'


def test_manual_origin_network_without_sender_marks_unknown_sender_and_typed_sender_is_checked(monkeypatch):
    from tests.payin_registry import ensure_payin_wallet
    ensure_payin_wallet(REAL_RECEIVER)
    no_sender = lambda *a, **k: {'status': 'confirmed', 'verifiedAmount': 100.0,
                                 'verifiedAt': '2026-10-18T12:00:00Z', 'from': None, 'to': REAL_RECEIVER}
    # введённый отправитель обязан совпасть с наблюдённым — сеть его не назвала → отказ
    tx = secrets.token_hex(32)
    client = _manual_origin_client(monkeypatch, [
        {'hash': tx, 'network': 'trc20', 'amount': 100, 'from': 'TTypedByManager1111111111111'}])
    monkeypatch.setattr(m, 'verify_transfer', no_sender)
    refused = client.post('/api/stand/deals/1490/crm-close', json={
        'version': 1, 'crm': _manual_origin_crm(tx)})
    assert refused.status_code == 422 and refused.json['error'] == 'payin_hash_unverified'
    # hash-only: сеть подтвердила перевод без отправителя — помечаем неизвестного отправителя
    tx = secrets.token_hex(32)
    client = _manual_origin_client(monkeypatch, [{'hash': tx, 'network': 'trc20', 'amount': 100}])
    monkeypatch.setattr(m, 'verify_transfer', no_sender)
    assert client.post('/api/stand/deals/1490/crm-close', json={
        'version': 1, 'crm': _manual_origin_crm(tx)}).status_code == 201
    saved = json.loads(m.get_session().get(m.StandState, 1).data)['deals'][0]['payinHashes'][0]
    assert saved['from'] is None and saved['unknownSender'] is True
    deal = {'kind': 'Фрихолд', 'payType': 'Крипта', 'payerWallet': 'TTypedByManager1111111111111',
            'invoiceUsd': 100, 'ippsTariff': 'bank', 'payinHashes': [saved]}
    crm = {'deal_kind': 'mf_freehold', 'payin_method': 'crypto_direct', 'payin_amount_usdt': 100}
    assert m._stand_crm_fact_problem(deal, crm, 'mf_freehold') == 'payin_basis_unverified'


def test_manual_origin_payin_receiver_must_be_our_active_registry_wallet(monkeypatch):
    tx = secrets.token_hex(32)
    client = _manual_origin_client(monkeypatch, [{'hash': tx, 'network': 'trc20', 'amount': 100}])
    _real_verifier(monkeypatch, tx, [(REAL_SENDER, 'T' + 'Z' * 33, 100)])  # получатель не в реестре
    refused = client.post('/api/stand/deals/1490/crm-close', json={
        'version': 1, 'crm': _manual_origin_crm(tx)})
    assert refused.status_code == 422 and refused.json['error'] == 'payin_wallet_not_registered'
    board = json.loads(m.get_session().get(m.StandState, 1).data)['deals'][0]
    assert board['closed'] is False
