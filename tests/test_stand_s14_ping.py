"""Напоминание менеджера операционисту о приходе на s14."""
import json
import secrets
import copy

import app as m


def test_s14_ping_role_step_cooldown_note_and_journal(monkeypatch):
    monkeypatch.setattr(m, 'STAND_MODE', True)
    m._stand_migrate()
    state = {'deals': [{'id': 9308, 'code': 'SYN-9308', 'client': 'Татьяна',
                       'step': 's14', 'amountRub': 192666.3, 'payType': 'По реквизитам',
                       'files': {'clientPayinReceipt': [{'file': 'client-check.pdf'}]},
                       'log': []}], 'notes': []}
    db = m.get_session()
    try:
        user = m.AdminUser(username='s14-ping-' + secrets.token_hex(4), role='manager',
                           display_name='Елизавета', password_hash='unused')
        db.add(user)
        db.flush()
        row = m._stand_row(db)
        row.data = json.dumps(state, ensure_ascii=False)
        row.version = 7
        db.commit()
        uid = user.id
    finally:
        db.close()
    client = m.app.test_client()
    with client.session_transaction() as session:
        session['user_id'] = uid
        session['display_name'] = 'Елизавета'
    role = ['manager']
    monkeypatch.setattr(m, 'current_role', lambda: role[0])
    delivered = []
    monkeypatch.setattr(m.stand_notify, 'deliver', lambda: delivered.append('policy-channel') or [])
    post = lambda version, text='Клиент говорит, что оплатил': client.post(
        '/api/stand/s14/ping', json={'version': version, 'dealId': 9308, 'text': text})

    role[0] = 'operator'
    assert post(7).status_code == 403
    role[0] = 'manager'
    forged = copy.deepcopy(state)
    forged['deals'][0]['s14Ping'] = {'at': 1, 'by': 'подделка', 'text': 'мимо лимита'}
    assert m._stand_guard_transition(state, forged, 'manager') == 'Пинг операционисту отправляет только сервер'
    saved = post(7)
    assert saved.status_code == 200, saved.json
    assert delivered == ['policy-channel']
    deal = saved.json['data']['deals'][0]
    assert deal['s14Ping']['by'] == 'Елизавета'
    assert deal['s14Ping']['text'] == 'Клиент говорит, что оплатил'
    assert 'Менеджер пинганул операциониста · Клиент говорит, что оплатил' in deal['log'][-1]['text']
    note = saved.json['data']['notes'][0]
    assert note['role'] == 'operator' and note['dealId'] == 9308
    assert 'Татьяна' in note['text'] and '192666.3 ₽' in note['text']
    assert 'чек клиента приложен' in note['text']
    monkeypatch.setenv('STAND_BASE_URL', 'https://stand.example')
    monkeypatch.setattr(m.stand_notify, '_app', m)
    formatted = m.stand_notify._format_note(note, {'9308': deal})
    assert 'https://stand.example/tasks?deal=9308' in formatted
    limited = post(saved.json['version'])
    assert limited.status_code == 409
    assert 'Уже пинговали в ' in limited.json['error']
    assert delivered == ['policy-channel']

    db = m.get_session()
    try:
        row = m._stand_row(db)
        state = json.loads(row.data)
        state['deals'][0]['s14Ping']['at'] -= 15 * 60 * 1000
        row.data = json.dumps(state, ensure_ascii=False)
        db.commit()
    finally:
        db.close()
    role[0] = 'admin'
    assert post(saved.json['version'], '').status_code == 200
    assert len(delivered) == 2

    db = m.get_session()
    try:
        row = m._stand_row(db)
        state = json.loads(row.data)
        state['deals'][0]['step'] = 's14m'
        row.data = json.dumps(state, ensure_ascii=False)
        db.commit()
    finally:
        db.close()
    assert post(saved.json['version'] + 1).status_code == 409
    assert post(saved.json['version'] + 1).status_code == 409
