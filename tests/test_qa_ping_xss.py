"""Исходный текст пинга сохраняется в журнале для безопасного вывода на клиенте."""
import json
import secrets

import app as m


def test_ping_text_with_html_is_preserved_in_journal(monkeypatch):
    monkeypatch.setattr(m, 'STAND_MODE', True)
    m._stand_migrate()
    state = {'deals': [{'id': 9500, 'code': 'SYN-9500', 'client': 'Клиент',
                       'step': 's14', 'amountRub': 1000, 'payType': 'По реквизитам',
                       'log': []}], 'notes': []}
    db = m.get_session()
    try:
        user = m.AdminUser(username='qa-ping-' + secrets.token_hex(4), role='manager',
                           display_name='Елизавета', password_hash='unused')
        db.add(user)
        db.flush()
        row = m._stand_row(db)
        row.data = json.dumps(state, ensure_ascii=False)
        row.version = 1
        db.commit()
        uid = user.id
    finally:
        db.close()
    client = m.app.test_client()
    with client.session_transaction() as session:
        session['user_id'] = uid
        session['display_name'] = 'Елизавета'
    monkeypatch.setattr(m, 'current_role', lambda: 'manager')
    monkeypatch.setattr(m.stand_notify, 'deliver', lambda: [])

    payload_text = '<img src=x onerror=alert(1)>'
    resp = client.post('/api/stand/s14/ping', json={'version': 1, 'dealId': 9500, 'text': payload_text})
    assert resp.status_code == 200, resp.json
    deal = resp.json['data']['deals'][0]
    log_text = deal['log'][-1]['text']
    # Экранирование делается в HTML-представлениях; двойное экранирование при
    # сохранении испортило бы текст журнала и Telegram-уведомление.
    assert payload_text in log_text
    assert '&lt;img' not in log_text
