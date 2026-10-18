"""Внешние уведомления при закрытии сделки со стенда (crm-close).

Закрытие со стенда создаёт сделку через _create_deal_impl(defer_commit=True,
skip_sync=True), поэтому пост-эффекты там не выполняются. stand_crm_close после
commit вызывает их явно: ровно один раз на закрытие, падение любого эффекта не
превращается в 500.

Маршрутизация Telegram/рефереров:
- STAND_MODE: карточка и копия реферера уходят заметками стенда (_stand_note),
  send_telegram_notification и send_referrer_dm не вызываются;
- прод (STAND_MODE=False, проверяется прямым вызовом диспетчера, т.к. роут
  стенда сам требует STAND_MODE): send_telegram_notification и send_referrer_dm.
GSheet и вебхук одинаковы в обоих режимах (no-op на стенде внутри).

Запуск: python3 scripts/run_fenced_pytest.py tests/test_stand_crm_close_notifications.py
"""
import copy
import json
import secrets

import app as A

STAND_DEAL_ID = 1474
GSHEET_AND_WEBHOOK = ('send_deal_completed_webhook', 'sync_deals_to_gsheet',
                      'sync_referrer_reward_to_gsheet', 'sync_realty_deal_to_gsheet')
LOW_LEVEL_SENDERS = ('send_telegram_notification', 'send_referrer_dm')

# Синтетическая сделка обмена: ручной origin, без чеков и evidence (ручной путь их не требует).
EXCHANGE_DEAL = {
    'id': STAND_DEAL_ID, 'code': 'СД-1474', 'client': 'Synthetic N1',
    'type': 'Обмен валюты', 'step': 'manual', 'closed': False, 'crmDealId': None,
    'sentToClient': False, 'pay': {}, 'amountUsdt': 100, 'payout': {'usdt': 90},
    'files': {}, 'log': [], 'manual': True, 'manualNew': False, 'isTask': False,
    'docLinks': {'invoice': 'https://docs.invalid/invoice',
                 'contract': 'https://docs.invalid/contract',
                 'payment': 'https://docs.invalid/payment'},
}
EXCHANGE_CRM = {
    'deal_kind': 'exchange', 'client_name': 'Synthetic N1', 'manager_name': 'Елизавета',
    'payin_method': 'sber_reqs', 'payin_amount_usdt': 100, 'payout_method': 'transfer',
    'payout_source': 'cash_batch', 'payout_amount_usdt': 90,
    'doc_invoice_url': 'https://docs.invalid/invoice',
    'doc_contract_url': 'https://docs.invalid/contract',
    'doc_payment_url': 'https://docs.invalid/payment',
}
# Лизхолд: тот же набор полей, что в test_stand_crm_close_atomic.py::test_manual_standard_types_close_once
LEASEHOLD_CRM = {
    'deal_kind': 'mf_realty', 'client_name': 'Synthetic N1',
    'payin_method': 'crypto_direct', 'payin_amount_usdt': 19929.17,
    'invoice_amount_thb': 622370, 'buy_rate_thb_usdt': 33.22, 'company_percent': 1,
    'doc_invoice_url': 'https://docs.invalid/invoice',
    'doc_contract_url': 'https://docs.invalid/contract',
    'doc_payment_url': 'https://docs.invalid/payment',
}


def _stand_setup(monkeypatch):
    """Стенд в режиме STAND_MODE, пустая доска и менеджер; возвращает user id."""
    monkeypatch.setattr(A, 'STAND_MODE', True)
    A._stand_migrate()
    db = A.get_session()
    try:
        user = A.AdminUser(username='notif-' + secrets.token_hex(6), display_name='Notif Manager',
                           role='manager', password_hash='unused')
        db.add(user)
        db.flush()
        uid = user.id
        row = db.query(A.StandState).filter_by(id=1).first()
        if row is None:
            row = A.StandState(id=1)
            db.add(row)
        row.data = json.dumps({'deals': [], 'notes': []})
        row.version = 1
        row.generation = secrets.token_hex(16)
        db.commit()
    finally:
        db.close()
    return uid


def _client(uid):
    client = A.app.test_client()
    with client.session_transaction() as sess:
        sess['user_id'] = uid
    return client


def _manual_draft(uid, kind):
    """Создаёт ручную сделку на доске; возвращает текущую версию стенда."""
    deal = copy.deepcopy(EXCHANGE_DEAL)
    if kind == 'leasehold':
        deal.update(type='Оплата недвижимости', kind='Лизхолд', amountThb=622370,
                    invoiceUsd=None, amountUsdt=19929.17, rates={'usdtThb': 33.22},
                    ippsTariff=None)
    created = _client(uid).put('/api/stand/state', json={
        'version': 1, 'data': {'deals': [deal], 'notes': []}})
    assert created.status_code == 200, created.json
    return created.json['version']


def _close(client, version, crm):
    return client.post(f'/api/stand/deals/{STAND_DEAL_ID}/crm-close',
                       json={'version': version, 'crm': crm})


def _with_agent(referrer_id, name):
    """Закрытие с одним агентом-рефералом (revshare 10%): выплата > 0."""
    return {**EXCHANGE_CRM, 'agents': [{'referrer_id': referrer_id, 'name': name,
                                        'tier': 1, 'comp_model': 'revshare', 'percent': 10}]}


def _effects(monkeypatch, raise_on=None):
    """Записывающие заглушки внешних эффектов: GSheet, вебхук и низкоуровневые отправители."""
    raise_on = raise_on or {}
    boxes = {name: [] for name in GSHEET_AND_WEBHOOK + LOW_LEVEL_SENDERS}

    def make(name):
        def fake(*args, **kwargs):
            boxes[name].append(args)
            if name in raise_on:
                raise raise_on[name]
        return fake

    for name in boxes:
        monkeypatch.setattr(A, name, make(name))
    return boxes


def _note_spy(monkeypatch):
    """Записывает (event_id, text) каждой заметки стенда; запись в состояние сохраняется."""
    calls = []
    real = A._stand_note

    def spy(state, event_id, role, deal, text):
        calls.append((event_id, text))
        return real(state, event_id, role, deal, text)

    monkeypatch.setattr(A, '_stand_note', spy)
    return calls


def _claimed(deal_id):
    db = A.get_session()
    try:
        return db.query(A.Deal).filter_by(id=deal_id).one().close_notified_at is not None
    finally:
        db.close()


def _notify_twice_in_session(deal_id):
    """Два подряд вызова настоящей точки входа stand_crm_close на одной committed-сделке."""
    db = A.get_session()
    try:
        deal = db.query(A.Deal).filter_by(id=deal_id).one()
        A._stand_notify_deal_closed(db, deal_id, deal, STAND_DEAL_ID)
        A._stand_notify_deal_closed(db, deal_id, deal, STAND_DEAL_ID)
    finally:
        db.close()


def _referrer(telegram_user_id=777):
    db = A.get_session()
    try:
        ref = A.Referrer(name='Ref ' + secrets.token_hex(3), code='c' + secrets.token_hex(8),
                         token=secrets.token_hex(16), telegram_user_id=telegram_user_id)
        db.add(ref)
        db.commit()
        return ref.id, ref.name
    finally:
        db.close()


def _orm_completed_deal(referrer_id=None):
    """Завершённая CRM-сделка с (опционально) агентом; создаётся напрямую через ORM."""
    db = A.get_session()
    try:
        deal = A.Deal(deal_type=A.DealType.PAY_IN, status=A.DealStatus.COMPLETED,
                      client_name='Direct', profit_usdt=10.0,
                      payin_amount_usdt=100, payout_amount_usdt=90)
        db.add(deal)
        db.flush()
        if referrer_id is not None:
            db.add(A.DealAgent(deal_id=deal.id, referrer_id=referrer_id, name='Ref', tier=1,
                               comp_model='revshare', percent=10, payout_usdt=1.0))
        db.commit()
        return deal.id
    finally:
        db.close()


def test_exchange_close_stand_routes_card_and_referrer_notice(monkeypatch):
    """Стенд: карточка и копия реферера — заметками; низкоуровневые TG/DM не вызываются."""
    uid = _stand_setup(monkeypatch)
    version = _manual_draft(uid, 'exchange')
    effects = _effects(monkeypatch)
    notes = _note_spy(monkeypatch)
    ref_id, ref_name = _referrer()

    resp = _close(_client(uid), version, _with_agent(ref_id, ref_name))

    assert resp.status_code == 201, resp.json
    deal_id = resp.json['deal']['id']
    assert resp.json['deal']['profit_usdt'] is not None
    assert len(notes) == 2, notes
    card = [t for e, t in notes if e == f'stand:close-card:{deal_id}']
    notice = [t for e, t in notes if e.startswith(f'stand:close-ref:{deal_id}:')]
    assert len(card) == 1 and len(notice) == 1
    assert '[стенд]' in notice[0] and ref_name in notice[0] and '$' in notice[0]
    assert effects['send_telegram_notification'] == []
    assert effects['send_referrer_dm'] == []
    for name in ('send_deal_completed_webhook', 'sync_deals_to_gsheet', 'sync_referrer_reward_to_gsheet'):
        assert len(effects[name]) == 1, name
    assert effects['sync_realty_deal_to_gsheet'] == []
    assert _claimed(deal_id)
    _assert_notes_link_board_deal(uid, deal_id)


def _assert_notes_link_board_deal(uid, crm_deal_id):
    """Заметки закрытия ссылаются на задачу доски (dealId), а не на CRM-id сделки."""
    stored = _client(uid).get('/api/stand/state').json['data']
    board = next(d for d in stored['deals'] if d['id'] == STAND_DEAL_ID)
    assert board['crmDealId'] == crm_deal_id
    own = [n for n in stored['notes']
           if str(n.get('id')) == f'stand:close-card:{crm_deal_id}'
           or str(n.get('id')).startswith(f'stand:close-ref:{crm_deal_id}:')]
    assert own, 'заметки закрытия не найдены'
    for note in own:
        assert note['dealId'] == board['id'] == STAND_DEAL_ID, note


def test_exchange_close_without_agent_queues_card_only(monkeypatch):
    uid = _stand_setup(monkeypatch)
    version = _manual_draft(uid, 'exchange')
    effects = _effects(monkeypatch)
    notes = _note_spy(monkeypatch)

    resp = _close(_client(uid), version, EXCHANGE_CRM)

    assert resp.status_code == 201, resp.json
    assert [e for e, _ in notes] == [f"stand:close-card:{resp.json['deal']['id']}"]
    assert effects['send_telegram_notification'] == []
    assert effects['send_referrer_dm'] == []


def test_prod_routing_uses_telegram_and_referrer_dm(monkeypatch):
    """Прод-ветка: send_telegram_notification и send_referrer_dm, без заметок стенда."""
    ref_id, _ = _referrer()
    did = _orm_completed_deal(ref_id)
    effects = _effects(monkeypatch)
    notes = _note_spy(monkeypatch)
    monkeypatch.setattr(A, 'STAND_MODE', False)

    db = A.get_session()
    try:
        A._stand_fire_close_post_effects(db, db.query(A.Deal).filter_by(id=did).one(), STAND_DEAL_ID)
    finally:
        db.close()

    assert len(effects['send_telegram_notification']) == 1
    assert len(effects['send_referrer_dm']) == 1
    assert notes == []


def test_idempotency_holds_with_stand_routing(monkeypatch):
    uid = _stand_setup(monkeypatch)
    version = _manual_draft(uid, 'exchange')
    effects = _effects(monkeypatch)
    notes = _note_spy(monkeypatch)
    ref_id, ref_name = _referrer()

    first = _close(_client(uid), version, _with_agent(ref_id, ref_name))
    assert first.status_code == 201, first.json
    deal_id = first.json['deal']['id']
    before = (len(notes), len(effects['send_telegram_notification']), len(effects['send_referrer_dm']))

    # Повтор роута (ретрай клиента) и повтор настоящей точки входа напрямую.
    second = _close(_client(uid), version, _with_agent(ref_id, ref_name))
    assert second.status_code == 200 and second.json['duplicate'] is True
    _notify_twice_in_session(deal_id)

    assert (len(notes), len(effects['send_telegram_notification']),
            len(effects['send_referrer_dm'])) == before


def test_leasehold_close_stand_queues_realty_card_only(monkeypatch):
    uid = _stand_setup(monkeypatch)
    version = _manual_draft(uid, 'leasehold')
    effects = _effects(monkeypatch)
    notes = _note_spy(monkeypatch)

    resp = _close(_client(uid), version, LEASEHOLD_CRM)

    assert resp.status_code == 201, resp.json
    assert LEASEHOLD_CRM['deal_kind'] in A.REALTY_KINDS
    assert len(effects['sync_realty_deal_to_gsheet']) == 1
    assert [e for e, _ in notes] == [f"stand:close-card:{resp.json['deal']['id']}"]
    assert effects['send_telegram_notification'] == []
    for name in ('send_deal_completed_webhook', 'sync_deals_to_gsheet', 'sync_referrer_reward_to_gsheet'):
        assert effects[name] == [], name
    assert _claimed(resp.json['deal']['id'])
    _assert_notes_link_board_deal(uid, resp.json['deal']['id'])


def test_claim_is_first_wins_and_guarded_fire_runs_once(monkeypatch):
    _stand_setup(monkeypatch)
    effects = _effects(monkeypatch)
    notes = _note_spy(monkeypatch)
    deal_id = _orm_completed_deal()

    first_db, second_db = A.get_session(), A.get_session()
    try:
        assert A._stand_claim_close_notification(first_db, deal_id) is True
        assert A._stand_claim_close_notification(second_db, deal_id) is False
    finally:
        first_db.close()
        second_db.close()

    guarded_id = _orm_completed_deal()
    _notify_twice_in_session(guarded_id)
    assert [e for e, _ in notes].count(f'stand:close-card:{guarded_id}') == 1
    assert len(effects['sync_deals_to_gsheet']) == 1  # диспетчер один раз на вторую сделку, не на попытку


def test_notify_deal_closed_entry_point_twice_fires_exactly_once(monkeypatch):
    """Два вызова настоящей точки входа из роута подряд: эффекты ровно один раз."""
    _stand_setup(monkeypatch)
    effects = _effects(monkeypatch)
    notes = _note_spy(monkeypatch)
    ref_id, _ = _referrer()
    deal_id = _orm_completed_deal(ref_id)

    _notify_twice_in_session(deal_id)

    for name in ('send_deal_completed_webhook', 'sync_deals_to_gsheet', 'sync_referrer_reward_to_gsheet'):
        assert len(effects[name]) == 1, name
    assert effects['send_telegram_notification'] == []
    assert effects['send_referrer_dm'] == []
    names = [e for e, _ in notes]
    assert names.count(f'stand:close-card:{deal_id}') == 1
    assert sum(1 for e in names if e.startswith(f'stand:close-ref:{deal_id}:')) == 1
    assert _claimed(deal_id)


def test_route_retry_returns_duplicate_and_fires_nothing_again(monkeypatch):
    uid = _stand_setup(monkeypatch)
    version = _manual_draft(uid, 'exchange')
    effects = _effects(monkeypatch)
    notes = _note_spy(monkeypatch)
    create_calls = []
    real_create = A._create_deal_impl

    def spy(*args, **kwargs):
        create_calls.append(1)
        return real_create(*args, **kwargs)

    monkeypatch.setattr(A, '_create_deal_impl', spy)

    first = _close(_client(uid), version, EXCHANGE_CRM)
    assert first.status_code == 201, first.json
    # Повтор с тем же payload: origin уже связан, роут отвечает duplicate
    # до _create_deal_impl и до пост-эффектов (ранний `if link:`).
    second = _close(_client(uid), version, EXCHANGE_CRM)

    assert second.status_code == 200, second.json
    assert second.json['duplicate'] is True
    assert second.json['deal']['id'] == first.json['deal']['id']
    assert len(create_calls) == 1, 'второй POST не должен доходить до _create_deal_impl'
    assert len(notes) == 1
    assert len(effects['sync_deals_to_gsheet']) == 1


def test_stand_state_is_savable_right_after_close(monkeypatch):
    """Клиент сохраняет доску с версией из ответа закрытия: сохранение не должно упасть в конфликт."""
    uid = _stand_setup(monkeypatch)
    version = _manual_draft(uid, 'exchange')
    _effects(monkeypatch)
    _note_spy(monkeypatch)

    resp = _close(_client(uid), version, EXCHANGE_CRM)
    assert resp.status_code == 201, resp.json
    saved = _client(uid).put('/api/stand/state', json={
        'version': resp.json['version'], 'data': resp.json['data']})
    assert saved.status_code == 200, saved.json
    # Заметки карточки, записанные после commit, не должны стираться сохранением клиента.
    stored = _client(uid).get('/api/stand/state').json['data']['notes']
    assert any(str(n.get('id')) == f"stand:close-card:{resp.json['deal']['id']}" for n in stored)


def test_inner_effect_failure_keeps_close_and_other_effects(monkeypatch, capsys):
    uid = _stand_setup(monkeypatch)
    version = _manual_draft(uid, 'exchange')
    effects = _effects(monkeypatch, raise_on={
        'send_deal_completed_webhook': RuntimeError('synthetic webhook failure')})
    notes = _note_spy(monkeypatch)

    resp = _close(_client(uid), version, EXCHANGE_CRM)

    assert resp.status_code == 201, resp.json
    assert resp.json['success'] is True
    assert resp.json['data']['deals'][0]['crmDealId'] == resp.json['deal']['id']
    assert '[Webhook] stand close error' in capsys.readouterr().out
    assert len(notes) == 1
    assert len(effects['sync_deals_to_gsheet']) == 1
    assert len(effects['sync_referrer_reward_to_gsheet']) == 1


def test_dispatcher_exception_is_logged_not_500(monkeypatch):
    uid = _stand_setup(monkeypatch)
    version = _manual_draft(uid, 'exchange')
    logged = []

    def boom(session, deal):
        raise RuntimeError('synthetic dispatcher failure')

    monkeypatch.setattr(A, '_stand_fire_close_post_effects', boom)
    monkeypatch.setattr(A.app.logger, 'exception', lambda msg, *a, **k: logged.append(msg))

    resp = _close(_client(uid), version, EXCHANGE_CRM)

    assert resp.status_code == 201, resp.json
    assert resp.json['success'] is True
    assert 'stand close post-effects failed' in logged
