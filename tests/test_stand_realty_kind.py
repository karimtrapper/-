"""Early stand corrections to leasehold/freehold classification."""
import json
import secrets
from pathlib import Path

import app as m
import pytest

pytestmark = pytest.mark.usefixtures('stand_demo_environment')


def _setup(monkeypatch, step='s5'):
    monkeypatch.setattr(m, 'STAND_MODE', True)
    monkeypatch.setattr(m, '_stand_deliver_notes', lambda: [])
    m._stand_migrate()
    db = m.get_session()
    try:
        manager = m.AdminUser(username='kind-manager-' + secrets.token_hex(4),
                              display_name='Kind Manager', role='manager', password_hash='unused')
        operator = m.AdminUser(username='kind-operator-' + secrets.token_hex(4),
                               display_name='Kind Operator', role='operator', password_hash='unused')
        admin = m.AdminUser(username='kind-admin-' + secrets.token_hex(4),
                            display_name='Kind Admin', role='admin', password_hash='unused')
        db.add_all((manager, operator, admin))
        db.flush()
        state = {'deals': [{'id': 1532, 'code': 'СД-1532', 'client': 'Synthetic client',
                            'type': 'Оплата недвижимости', 'kind': 'Лизхолд', 'step': step,
                            'isTask': True, 'closed': False, 'managerUserId': manager.id,
                            'assigneeAdminId': operator.id, 'stepEnteredAt': 1763980000000,
                            'payType': 'По реквизитам',
                            'amountRub': 5000000,
                            'log': [], 'rates': {'at': 1795509184493, 'rubUsdt': '83'},
                            'quotes': [{'cpId': 1, 'name': 'Synthetic counterparty',
                                        'dir': 'rub', 'rate': 83, 'at': 1763980000000}],
                            'pay': {}, 'docs': {}, 'files': {},
                            'issued': {}, 'payinParts': [], 'payinHashes': []}], 'notes': []}
        row = db.query(m.StandState).filter_by(id=1).first()
        if row is None:
            row = m.StandState(id=1)
            db.add(row)
        row.data = json.dumps(state, ensure_ascii=False)
        row.version = 1
        row.updated_by = None
        db.commit()
        return manager.id, operator.id, admin.id
    finally:
        db.close()


def _client(user_id):
    from tests.test_stand_crm_close_atomic import _client as stand_client
    return stand_client(user_id)


def _seed_late_state(change):
    db = m.get_session()
    try:
        row = db.query(m.StandState).filter_by(id=1).first()
        state = json.loads(row.data)
        state['deals'][0].update(change)
        row.data = json.dumps(state, ensure_ascii=False)
        row.version += 1
        db.commit()
        return row.version
    finally:
        db.close()


def test_manager_corrects_kind_early_and_change_persists_with_audit(monkeypatch):
    manager_id, _, _ = _setup(monkeypatch)
    manager = _client(manager_id)

    changed = manager.patch('/api/stand/deals/1532/kind',
                            json={'version': 1, 'kind': 'Фрихолд'})
    assert changed.status_code == 200, changed.json
    assert changed.json['version'] == 2
    saved = manager.get('/api/stand/state').json
    deal = saved['data']['deals'][0]
    assert deal['kind'] == 'Фрихолд'
    assert deal['step'] == 's6'
    assert deal['assigneeAdminId'] is None
    assert deal['stepEnteredAt'] > 1763980000000
    assert deal['amountRub'] == 5000000
    assert deal['freeholdClientInput'] == 'sum'
    assert deal['rates']['rubUsdt'] == '83'
    assert deal['rates']['at'] == 1795509184493
    assert deal['quotes'][0]['dir'] == 'rub'
    from stand_workflow import quote_dirs
    assert quote_dirs(deal) == ('rub',)
    assert deal['log'][-1]['text'] == 'Тип недвижимости изменён: Лизхолд → Фрихолд; задача передана на расчёт'
    assert deal['log'][-1]['role'] == 'manager'
    assert deal['log'][-1]['author'] == 'Kind Manager'
    assert any(note.get('role') == 'manager' and note.get('dealId') == 1532
               and 'шаг s6' in note.get('text', '') for note in saved['data']['notes'])
    assert m._stand_current_step_role(saved['data'], deal) == 'manager'

    followup = manager.put('/api/stand/state', json=saved)
    assert followup.status_code == 200, followup.json
    assert followup.json['data']['deals'][0]['log'][-1] == deal['log'][-1]


def test_kind_cannot_be_changed_by_operator_or_whole_board_put(monkeypatch):
    manager_id, operator_id, _ = _setup(monkeypatch)
    operator = _client(operator_id)
    denied = operator.patch('/api/stand/deals/1532/kind',
                            json={'version': 1, 'kind': 'Фрихолд'})
    assert denied.status_code == 403

    snapshot = operator.get('/api/stand/state').json
    snapshot['data']['deals'][0]['kind'] = 'Фрихолд'
    refused = operator.put('/api/stand/state', json=snapshot)
    assert refused.status_code == 409
    assert 'отдельным действием' in refused.json['error']


@pytest.mark.parametrize('change', [
    {'step': 's11'}, {'amountThb': 10000}, {'rates': {'client': 35}},
    {'files': {'spa': [{'file': 'agreement.pdf', 'id': 'file-1'}]}},
])
def test_late_or_materialized_deal_kind_change_is_blocked(monkeypatch, change):
    manager_id, _, _ = _setup(monkeypatch)
    manager = _client(manager_id)
    version = _seed_late_state(change)

    refused = manager.patch('/api/stand/deals/1532/kind',
                            json={'version': version, 'kind': 'Фрихолд'})
    assert refused.status_code == 409
    assert manager.get('/api/stand/state').json['data']['deals'][0]['kind'] == 'Лизхолд'


def test_kind_patch_rejects_stale_version_and_invalid_value(monkeypatch):
    manager_id, _, _ = _setup(monkeypatch)
    manager = _client(manager_id)
    stale = manager.patch('/api/stand/deals/1532/kind',
                          json={'version': 0, 'kind': 'Фрихолд'})
    assert stale.status_code == 409 and stale.json['error'] == 'conflict'
    invalid = manager.patch('/api/stand/deals/1532/kind',
                            json={'version': 1, 'kind': 'Аренда'})
    assert invalid.status_code == 400


def test_auto_payment_cannot_use_realty_kind_correction(monkeypatch):
    manager_id, _, _ = _setup(monkeypatch)
    manager = _client(manager_id)
    version = _seed_late_state({'autoPayment': True, 'kind': 'Фрихолд'})
    refused = manager.patch('/api/stand/deals/1532/kind',
                            json={'version': version, 'kind': 'Лизхолд'})
    assert refused.status_code == 409
    assert manager.get('/api/stand/state').json['data']['deals'][0]['kind'] == 'Фрихолд'


def test_manager_cannot_reclassify_another_managers_deal_but_admin_can(monkeypatch):
    manager_id, _, admin_id = _setup(monkeypatch)
    db = m.get_session()
    try:
        other = m.AdminUser(username='kind-owner-' + secrets.token_hex(4),
                            display_name='Other Manager', role='manager', password_hash='unused')
        db.add(other)
        db.flush()
        row = db.query(m.StandState).filter_by(id=1).first()
        state = json.loads(row.data)
        state['deals'][0]['managerUserId'] = other.id
        row.data = json.dumps(state, ensure_ascii=False)
        db.commit()
        version = row.version
    finally:
        db.close()

    refused = _client(manager_id).patch('/api/stand/deals/1532/kind',
                                        json={'version': version, 'kind': 'Фрихолд'})
    assert refused.status_code == 403
    allowed = _client(admin_id).patch('/api/stand/deals/1532/kind',
                                      json={'version': version, 'kind': 'Фрихолд'})
    assert allowed.status_code == 200, allowed.json


def test_deal_card_exposes_editor_for_early_task_and_applies_server_snapshot():
    html = Path(m.app.static_folder, 'stand', 'tasks.html').read_text(encoding='utf-8')
    assert "row('Тип недвижимости',dealRealtyKindControl(d))" in html
    assert "d.isTask===true&&d.autoPayment!==true" in html
    assert "['s1','s4','s5'].includes(d.step)" in html
    assert "fetch('/api/stand/deals/'+id+'/kind'" in html
    assert 'standBase=standClone(result.data);standApply(merged.data)' in html
