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


def test_late_operator_quote_survives_manager_agreement(board_server):
    import requests
    base = board_server['BOARD_RACE_URL']
    manager, operator = [{'Cookie': c} for c in json.loads(board_server['BOARD_RACE_COOKIES'])]
    initial = requests.get(base + '/api/stand/state', headers=manager, timeout=5).json()
    board = {'deals': [{'id': 1484, 'code': 'QA-1484', 'client': 'Иван',
        'type': 'Оплата недвижимости', 'kind': 'Фрихолд', 'payType': 'По реквизитам',
        'step': 's6', 'selfRate': True, 'rates': {'client': '90', 'rubUsdt': '85'}, 'quotes': [], 'log': [],
        'invoiceUsd': 1000}], 'notes': [], 'cps': [{'id': 'tradex',
        'name': 'Tradex', 'dirs': ['rub']}], 'seq': 1484}
    created = requests.put(base + '/api/stand/state', headers=manager, timeout=5,
                           json={'version': initial['version'], 'data': board})
    assert created.status_code == 200, created.json()
    stale_version = created.json()['version']
    agreed = json.loads(json.dumps(created.json()['data']))
    agreed['deals'][0]['step'] = 's8'
    agreed['deals'][0]['rates']['client'] = '91'
    agreed['deals'][0]['amountRub'] = 91000
    saved = requests.put(base + '/api/stand/state', headers=manager, timeout=5,
                         json={'version': stale_version, 'data': agreed})
    assert saved.status_code == 200, saved.json()
    late = requests.post(base + '/api/stand/quote', headers=operator, timeout=5,
                         json={'version': stale_version, 'dealId': 1484,
                               'cpId': 'tradex', 'dir': 'rub', 'rate': '82,45'})
    assert late.status_code == 200, late.json()
    forbidden = requests.post(base + '/api/stand/quote', headers=manager, timeout=5,
                              json={'version': stale_version, 'dealId': 1484,
                                    'cpId': 'tradex', 'dir': 'rub', 'rate': '83'})
    assert forbidden.status_code == 403
    deal = late.json()['data']['deals'][0]
    assert deal['step'] == 's8'
    assert deal['rates']['client'] == '91'
    assert deal['rates']['rubUsdt'] == '82,45'
    assert deal['quotes'][0]['rate'] == '82,45'
    assert any('Курс получен' in e['text'] for e in deal['log'])
    stale = requests.post(base + '/api/stand/quote', headers=operator, timeout=5,
                          json={'version': stale_version, 'dealId': 1484,
                                'cpId': 'tradex', 'dir': 'rub', 'rate': '83',
                                'previousAt': None})
    assert stale.status_code == 409
    assert requests.get(base + '/api/stand/state', headers=manager,
                        timeout=5).json()['data']['deals'][0]['quotes'][0]['rate'] == '82,45'


def test_s23_requisites_reopen_stops_ipps_instruction(board_server):
    import requests
    base = board_server['BOARD_RACE_URL']
    manager = {'Cookie': json.loads(board_server['BOARD_RACE_COOKIES'])[0]}
    db = m.get_session()
    try:
        row = m._stand_row(db)
        payto = {'dev': 'QA Developer', 'bank': 'QA Bank', 'acc': '123456789',
                 'swift': 'QATESTXX', 'purpose': 'Invoice 1484'}
        row.data = json.dumps({'deals': [{'id': 1484, 'code': 'QA-1484',
            'type': 'Оплата недвижимости', 'kind': 'Фрихолд', 'step': 's23',
            'postConv': 'ipps_swift', 'payTo': payto, 'reqTask': 'done',
            'payToConfirm': {'payTo': payto, 'at': 1},
            'ippsPayoutOrder': {'confirmedAt': '2026-10-13T01:00:00Z',
                                'address': 'TQA', 'amount': 1000},
            'transfer': {'addr': 'TQA', 'net': 'TRC20', 'amount': 1000, 'sends': []},
            'log': []}], 'notes': []})
        row.version = 5
        db.commit()
    finally:
        db.close()
    reopened = requests.post(base + '/api/stand/payto/reopen', headers=manager,
        timeout=5, json={'version': 5, 'dealId': 1484})
    assert reopened.status_code == 200, reopened.json()
    deal = reopened.json()['data']['deals'][0]
    assert deal['step'] == 's22'
    assert not deal.get('ippsPayoutOrder')
    assert not deal.get('payToConfirm')
    assert deal['reqTask'] == 'open'
    assert not (deal.get('transfer') or {}).get('addr')
    assert 'остановлена' in deal['log'][-1]['text']
    assert m._stand_current_step_role(reopened.json()['data'], deal) == 'manager'
    proposal = json.loads(json.dumps(deal))
    proposal.update(step='s23', reqTask='done', _ippsPayoutInstruction=True)
    assert 'менеджер' in m._stand_freehold_ipps_order_problem(
        reopened.json()['data'], deal, proposal, 'operator').lower()
    forged = json.loads(json.dumps(reopened.json()['data']))
    forged['deals'][0]['transfer']['sends'] = [{'hash': 'fake', 'amount': 1}]
    blocked = requests.put(base + '/api/stand/state', headers=manager, timeout=5,
                           json={'version': reopened.json()['version'], 'data': forged})
    assert blocked.status_code == 409
    assert 'поручен' in blocked.json()['error'].lower()
