"""Две ролевые HTTP-сессии и управляемое запаздывание ответов клиенту."""
import json
import os
import secrets
import subprocess
import threading

import pytest
from werkzeug.serving import make_server
import app as m


@pytest.fixture
def board_server(monkeypatch):
    monkeypatch.setattr(m, 'STAND_MODE', True)
    monkeypatch.setattr(m, '_stand_deliver_notes', lambda: [])
    m._stand_migrate()
    db = m.get_session()
    try:
        row = m._stand_row(db)
        old = (row.data, row.version, row.generation)
        row.data = json.dumps({'deals': [], 'notes': [], 'seq': 1471})
        row.version = 1
        row.generation = secrets.token_hex(16)
        users = []
        for name, role in [('marina', 'manager'), ('artem', 'operator')]:
            user = m.AdminUser(username=f'race-{name}-{secrets.token_hex(4)}',
                               role=role, password_hash='unused')
            db.add(user)
            db.flush()
            users.append(user.id)
        db.commit()
    finally:
        db.close()
    # Барьер выбирает свободный порт из разрешённого пула; первый мог занять
    # HTTP-сервер предыдущего теста или ещё не освобождённое соединение.
    server = make_server('127.0.0.1', 0, m.app, threaded=True)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    serializer = m.app.session_interface.get_signing_serializer(m.app)
    env = dict(os.environ, BOARD_RACE_URL=f'http://127.0.0.1:{port}',
               BOARD_RACE_COOKIES=json.dumps(['session='+serializer.dumps({'user_id': uid}) for uid in users]))
    yield env
    server.shutdown()
    thread.join(5)
    server.server_close()
    db = m.get_session()
    try:
        row = m._stand_row(db)
        row.data, row.version, row.generation = old
        db.commit()
    finally:
        db.close()


@pytest.mark.parametrize('scenario', ['late_poll', 'conflict_fields'])
def test_two_role_sessions_keep_new_deal_and_quotes(board_server, scenario):
    result = subprocess.run(['node', 'tests/helpers/stand_board_race.js', scenario],
                            env=board_server, capture_output=True, text=True, timeout=20)
    print(result.stdout)
    assert result.returncode == 0, result.stdout + result.stderr


def test_stale_or_incomplete_board_cannot_delete_persisted_deal(board_server):
    import requests
    base = board_server['BOARD_RACE_URL'] + '/api/stand/state'
    manager, operator = [{'Cookie': c} for c in json.loads(board_server['BOARD_RACE_COOKIES'])]
    initial = requests.get(base, headers=operator, timeout=5).json()
    saved = requests.put(base, headers=manager, timeout=5, json={
        'version': initial['version'], 'data': {'deals': [{
            'id': 1472, 'client': 'Synthetic persisted', 'type': 'Обмен валюты',
            'step': 's5', 'amountRub': 100000}], 'notes': []}})
    assert saved.status_code == 200, saved.json()
    stale = requests.put(base, headers=operator, timeout=5,
                         json={'version': initial['version'], 'data': initial['data']})
    assert stale.status_code == 409 and stale.json()['error'] == 'conflict'
    missing = requests.put(base, headers=operator, timeout=5,
                           json={'version': saved.json()['version'], 'data': initial['data']})
    assert missing.status_code == 409 and missing.json()['error'] == 'missing_deals_forbidden'
    assert len(requests.get(base, headers=manager, timeout=5).json()['data']['deals']) == 1
