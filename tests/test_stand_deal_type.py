"""Manual deal classification stays independent from payment and referrals."""
import json
import secrets

import app as m
from tests.test_stand_crm_close_atomic import _client, _setup


def _put(browser, change):
    snapshot = browser.get('/api/stand/state').json
    change(snapshot['data'])
    return browser.put('/api/stand/state', json=snapshot)


def _patch(browser, deal_id, version, inquiry_type, **extra):
    return browser.patch(f'/api/stand/deals/{deal_id}/inquiry-type',
                         json={'version': version, 'inquiryType': inquiry_type, **extra})


def test_closed_deal_type_can_be_edited_only_by_manager_or_admin(monkeypatch):
    manager_id = _setup(monkeypatch)
    with m.SessionLocal() as db:
        operator = m.AdminUser(username='deal-type-' + secrets.token_hex(4),
                               role='operator', password_hash='unused')
        db.add(operator)
        row = db.get(m.StandState, 1)
        state = json.loads(row.data)
        state['deals'][0].update(step='done', closed=True, closeReason='Не устроил курс', refId=17)
        row.data = json.dumps(state)
        db.commit()
        operator_id = operator.id
    manager, operator = _client(manager_id), _client(operator_id)

    assert 'inquiryType' not in manager.get('/api/stand/state').json['data']['deals'][0]
    denied = _put(operator, lambda data: data['deals'][0].update(inquiryType='agent'))
    assert denied.status_code == 409
    assert denied.json['error'] == 'Тип сделки меняет менеджер или администратор'

    saved = _put(manager, lambda data: data['deals'][0].update(inquiryType='client'))
    assert saved.status_code == 200, saved.json
    deal = saved.json['data']['deals'][0]
    assert deal['inquiryType'] == 'client'
    assert deal['type'] == 'Обмен валюты'
    assert deal['refId'] == 17
    assert deal['closeReason'] == 'Не устроил курс'

    for invalid in (None, '', 'referral'):
        refused = _put(manager, lambda data: data['deals'][0].update(inquiryType=invalid))
        assert refused.status_code == 409
        assert refused.json['error'] == 'Некорректный тип сделки'
    preserved = _put(operator, lambda data: data['deals'][0].pop('inquiryType'))
    assert preserved.status_code == 200, preserved.json
    assert preserved.json['data']['deals'][0]['inquiryType'] == 'client'
    version = preserved.json['version']
    assert _patch(operator, deal['id'], version, 'agent').status_code == 403
    assert _patch(manager, deal['id'], version, 'agent', docs={}).status_code == 400
    closed = _patch(manager, deal['id'], version, 'agent')
    assert closed.status_code == 200, closed.json
    assert closed.json['version'] == version + 1
    assert manager.get('/api/stand/state').json['data']['deals'][0] == {
        **preserved.json['data']['deals'][0], 'inquiryType': 'agent'}


def test_creating_deal_accepts_explicit_type_and_old_payloads(monkeypatch):
    manager_id = _setup(monkeypatch)
    manager = _client(manager_id)
    monkeypatch.setattr(m, '_stand_deliver_notes', lambda: [])

    def add_deals(data):
        base = {'managerUserId': manager_id, 'step': 's5', 'isTask': True, 'closed': False,
                'type': 'Оплата недвижимости', 'kind': 'Лизхолд', 'payType': 'По реквизитам',
                'amountThb': 10000, 'source': 'none'}
        data['deals'].extend([
            dict(base, id=2001, code='СД-2001', client='Fixture typed', inquiryType='agent'),
            dict(base, id=2002, code='СД-2002', client='Fixture legacy'),
        ])

    created = _put(manager, add_deals)
    assert created.status_code == 200, created.json
    typed, legacy = created.json['data']['deals'][-2:]
    assert typed['inquiryType'] == 'agent'
    assert 'inquiryType' not in legacy
    updated = _patch(manager, typed['id'], created.json['version'], 'client')
    assert updated.status_code == 200, updated.json
    assert updated.json['version'] == created.json['version'] + 1
    stale = _patch(manager, typed['id'], created.json['version'], 'agent')
    assert stale.status_code == 409 and stale.json['error'] == 'conflict'
    current = manager.get('/api/stand/state').json
    assert current['data']['deals'][-2] == {**typed, 'inquiryType': 'client'}
    assert current['data']['deals'][-1] == legacy
