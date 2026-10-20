"""Завершённый s26 «Оплатить инвойс» с чеком сам принимает факт чека на s27."""
import copy
import json

import pytest
import app as m
from tests.test_stand_single_confirm import setup_verified, change_board

pytestmark = pytest.mark.usefixtures('stand_demo_environment')
AT_UPLOAD, AT_GO, AT_STEP = 1760852000000, 1760852982000, 1760852982001
GO_SCB = 'Оплачено, чек у менеджера — отправить клиенту и закрыть'
GO_IPPS = 'MT103 подтверждён, чек у менеджера — отправить клиенту и закрыть'


def trail(file, *, go=GO_IPPS, role='operator', author='Артём', upload=True, step=True,
          comment=True, upload_after=False):
    """Журнал в форме реальной сделки: чек, переход (комментарий сервера), шаг дальше."""
    upload_entry = {'at': AT_UPLOAD, 'role': 'operator', 'text': 'Приложен файл: receipt · ' + file}
    go_entry = ({'at': AT_GO, 'role': role, 'author': author, 'kind': 'comment',
                 'text': f'Комментарий · {author}: {go}'} if comment
                else {'at': AT_GO, 'ts': '19.10, 12:49', 'role': role, 'by': author, 'text': go})
    log = ([upload_entry] if upload else []) + [go_entry]
    if step:
        log.append({'at': AT_STEP, 'role': 'operator', 'text': 'Шаг передан дальше'})
    if upload_after:
        log.append(dict(upload_entry, at=AT_STEP + 5))
    return log


def receipt_fact(client):
    status = client.get('/api/stand/deals/1474/close-evidence').json
    return next(f for f in status['facts'] if f['kind'] == 'receipt'), status


def board(monkeypatch, **kwargs):
    # Загрузил менеджер: серверной приёмки (operator_upload) нет — только журнал.
    client, uid, crm = setup_verified(monkeypatch, property_deal=True, uploader_role='manager', **kwargs)
    db = m.get_session()
    try:
        deal = json.loads(m._stand_row(db).data)['deals'][0]
        name = deal['files']['receipt'][0]['file']
    finally:
        db.close()
    return client, uid, crm, name


@pytest.mark.parametrize('go,comment', [(GO_IPPS, True), (GO_SCB, True), (GO_SCB, False)])
def test_historical_completion_accepts_receipt_with_actor_and_time(monkeypatch, go, comment):
    client, _, crm, name = board(monkeypatch)
    assert receipt_fact(client)[0]['reason'] == 'operator_receipt_acceptance_missing'
    version = change_board(lambda d: d.update(log=trail(name, go=go, comment=comment)))
    fact, status = receipt_fact(client)
    assert fact['ready'] and fact['implicit'] and fact['system']
    assert fact['confirmed_by'] == 'Артём' and fact['confirmed_role'] == 'operator'
    assert fact['checked_at'] == '2025-10-19T05:49:42Z'  # at, а не ts: UTC epoch ms
    assert status['missing'] == []
    closed = client.post('/api/stand/deals/1474/crm-close', json={'version': version, 'crm': crm})
    assert closed.status_code == 201, closed.json


def test_completion_beats_stale_signed_record_and_no_backfill(monkeypatch):
    client, uid, _, name = board(monkeypatch)
    db = m.get_session()
    try:
        row = m._stand_row(db)
        deal = json.loads(row.data)['deals'][0]
        stale = copy.deepcopy(deal)
        stale['pay'] = {'invoicePaid': False}
        m._stand_upsert_close_evidence(db, row, stale, 'receipt', uid, 'operator_attestation')
        db.commit()
    finally:
        db.close()
    change_board(lambda d: d.update(log=trail(name)))
    fact, _ = receipt_fact(client)
    assert fact['ready'] and fact['implicit'] and fact['checked_at'] == '2025-10-19T05:49:42Z'
    db = m.get_session()
    try:
        row = m._stand_row(db)
        assert db.query(m.StandCloseEvidence).filter_by(generation=row.generation, kind='receipt').count() == 1
    finally:
        db.close()


def test_signed_receipt_alone_does_not_bypass_missing_completion(monkeypatch):
    client, uid, _, _ = board(monkeypatch)
    db = m.get_session()
    try:
        row = m._stand_row(db)
        deal = json.loads(row.data)['deals'][0]
        m._stand_upsert_close_evidence(db, row, deal, 'receipt', uid, 'operator_attestation')
        db.commit()
    finally:
        db.close()
    fact, status = receipt_fact(client)
    assert not fact['ready'] and fact['reason'] == 'operator_receipt_acceptance_missing'
    assert status['missing'] == ['receipt']


def test_no_completion_incomplete_s26_and_unpaid_stay_blocked(monkeypatch):
    client, _, crm, name = board(monkeypatch)
    cases = {
        'only upload': dict(log=[trail(name)[0]]),
        'still on s26': dict(log=trail(name), step='s26'),
        'unpaid': dict(log=trail(name), pay={'invoicePaid': False}),
    }
    for label, patch in cases.items():
        version = change_board(lambda d: d.update(copy.deepcopy(patch)))
        fact, status = receipt_fact(client)
        assert not fact['ready'], label
        before = m.get_session().query(m.Deal).count()
        closed = client.post('/api/stand/deals/1474/crm-close', json={'version': version, 'crm': crm})
        assert closed.status_code == 409, label
        assert m.get_session().query(m.Deal).count() == before
        change_board(lambda d: d.update(step='s27', pay={'invoicePaid': True, 'coinsNotified': True,
                                                        'coinsCredit': {'thb': 3030}}))


@pytest.mark.parametrize('label,log_kwargs', [
    ('manager wrote it', dict(role='manager')),
    ('no upload entry', dict(upload=False)),
    ('no step handoff', dict(step=False)),
    ('generic payment text', dict(go='Инвойс оплачен со счёта SCB — 3 000 ฿ · Dev · чек приложен')),
    ('generic ipps text', dict(go='Подтверждение от IPPS: MT103 приложен — застройщику дошло $1')),
    ('receipt re-attached after completion', dict(upload_after=True)),
])
def test_forged_or_partial_trails_do_not_accept_receipt(monkeypatch, label, log_kwargs):
    client, _, _, name = board(monkeypatch)
    change_board(lambda d: d.update(log=trail(name, **log_kwargs)))
    fact, _ = receipt_fact(client)
    assert not fact['ready'], label


def test_replaced_receipt_after_completion_is_rejected(monkeypatch):
    client, _, _, name = board(monkeypatch)
    change_board(lambda d: d.update(log=trail('other-' + name)))
    assert not receipt_fact(client)[0]['ready']


def test_author_prefix_must_match_server_author(monkeypatch):
    client, _, _, name = board(monkeypatch)
    log = trail(name)
    log[1]['text'] = 'Комментарий · Другой: ' + GO_IPPS
    change_board(lambda d: d.update(log=log))
    assert not receipt_fact(client)[0]['ready']


def test_manager_cannot_forge_completion_through_board_put(monkeypatch):
    client, _, _, name = board(monkeypatch)
    state = client.get('/api/stand/state').json
    deal = state['data']['deals'][0]
    deal['log'] = deal['log'] + [
        {'at': 1, 'role': 'operator', 'text': 'Приложен файл: receipt · ' + name},
        {'at': 2, 'role': 'operator', 'by': 'Артём', 'text': GO_IPPS},
        {'at': 3, 'role': 'operator', 'text': 'Шаг передан дальше'}]
    deal['s26Done'] = {'at': 1, 'byId': 1, 'by': 'Артём', 'role': 'operator', 'receipts': ['x']}
    deal['log'].append({'at': 4, 'role': 'operator', 'kind': 's26_completed', 'byId': 1,
                        'by': 'Артём', 'receipts': ['x'], 'text': 'Оплата инвойса завершена с чеком'})
    response = client.put('/api/stand/state', json={'version': state['version'], 'data': state['data']})
    assert response.status_code == 200, response.json
    fact, _ = receipt_fact(client)
    assert not fact['ready']
    db = m.get_session()
    try:
        stored = json.loads(m._stand_row(db).data)['deals'][0]
    finally:
        db.close()
    assert 's26Done' not in stored
    assert all(e.get('kind') == 'comment' and e['role'] == 'manager'
               for e in stored['log'][-4:])
    assert not any(e.get('kind') == 's26_completed' for e in stored['log'])


def test_structured_completion_entry_binds_receipt_and_actor(monkeypatch):
    client, _, _, name = board(monkeypatch)
    db = m.get_session()
    try:
        deal = json.loads(m._stand_row(db).data)['deals'][0]
    finally:
        db.close()
    ids = sorted(m._stand_receipt_content_ids(deal))
    assert m._stand_s26_completion_entry(deal, 'manager', 5, 'Мэн', 1) is None
    assert m._stand_s26_completion_entry(deal, 'operator', None, 'Оп', 1) is None
    entry = m._stand_s26_completion_entry(deal, 'operator', 7, 'Настя', AT_GO)
    assert (entry['at'], entry['byId'], entry['by'], entry['role'], entry['receipts'], entry['kind']) == (
        AT_GO, 7, 'Настя', 'operator', ids, 's26_completed')
    assert 'Настя' in entry['text']
    change_board(lambda d: d.update(log=[dict(entry)]))
    fact, _ = receipt_fact(client)
    assert fact['ready'] and fact['confirmed_by'] == 'Настя'
    assert fact['checked_at'] == '2025-10-19T05:49:42Z'
    # Последняя структурная запись решает: чек подменили — запись не подходит.
    change_board(lambda d: d['log'][0].update(receipts=['0' * 64]))
    assert not receipt_fact(client)[0]['ready']
    # Роль менеджера в записи не принимается.
    change_board(lambda d: d['log'][0].update(receipts=ids, role='manager'))
    assert not receipt_fact(client)[0]['ready']


def put_step(client, mutate):
    state = client.get('/api/stand/state').json
    mutate(state['data']['deals'][0])
    return client.put('/api/stand/state', json={'version': state['version'], 'data': state['data']})


def test_operator_s26_to_s27_put_writes_completion_to_log(monkeypatch):
    client, uid, _, name = board(monkeypatch)
    payto = {'dev': 'Dev', 'bank': 'BBL', 'acc': '123', 'purpose': 'rent', 'amount': 3000}
    change_board(lambda d: d.update(step='s26', payTo=payto, payToConfirm={'payTo': dict(payto)},
                                    pay=dict(d['pay'], invoicePaid=True)))
    db = m.get_session()
    try:
        operator = db.get(m.AdminUser, uid)
        operator.role, operator.display_name = 'operator', 'Настя'
        db.commit()
    finally:
        db.close()
    state = client.get('/api/stand/state').json
    state['data']['deals'][0]['step'] = 's27'
    response = client.put('/api/stand/state', json={'version': state['version'], 'data': state['data']})
    assert response.status_code == 200, response.json
    db = m.get_session()
    try:
        stored = json.loads(m._stand_row(db).data)['deals'][0]
    finally:
        db.close()
    done = [e for e in stored['log'] if e.get('kind') == 's26_completed']
    assert len(done) == 1 and 's26Done' not in stored
    assert done[0]['by'] == 'Настя' and done[0]['byId'] == uid
    assert done[0]['role'] == 'operator' and done[0]['receipts'] and done[0]['at']
    assert stored['log'][-1] is not None and stored['log'][-1]['kind'] == 's26_completed'  # после accept_journal
    fact, _ = receipt_fact(client)
    assert fact['ready'] and fact['implicit'] and fact['confirmed_by'] == 'Настя'


def test_non_s27_transition_does_not_write_completion(monkeypatch):
    client, uid, _, _ = board(monkeypatch)
    change_board(lambda d: d.update(step='s26'))
    db = m.get_session()
    try:
        db.get(m.AdminUser, uid).role = 'operator'
        db.commit()
    finally:
        db.close()
    state = client.get('/api/stand/state').json
    state['data']['deals'][0]['step'] = 's15'
    client.put('/api/stand/state', json={'version': state['version'], 'data': state['data']})
    db = m.get_session()
    try:
        stored = json.loads(m._stand_row(db).data)['deals'][0]
        assert not any(e.get('kind') == 's26_completed' for e in stored['log'])
    finally:
        db.close()
