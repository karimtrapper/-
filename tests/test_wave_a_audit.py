"""Regression cases for the 2026-10-14 board audit."""
import subprocess
from pathlib import Path
import pytest
from stand_workflow import quote_dirs


@pytest.mark.parametrize('pair,dirs', [
    ('RUB → THB', ('rub', 'thb')), ('THB → RUB', ('thb', 'rub')),
    ('RUB → USDT', ('rub',)), ('THB → USDT', ('thb',)),
    ('USDT → THB', ('thb',)),
])
def test_exchange_quote_directions(pair, dirs):
    assert quote_dirs({'type': 'Обмен валюты', 'pair': pair}) == dirs


def test_exchange_ui_and_crm():
    result = subprocess.run(['node', 'tests/test_wave_a_exchange.js'], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr

from tests.test_t29_step_role import board


@pytest.mark.parametrize('pair,dirs', list(__import__('stand_workflow').EXCHANGE_PAIRS.items()))
def test_exchange_quote_handoff_requires_only_pair_legs(board, pair, dirs):
    install, client_for = board
    required = dirs[2]
    install('s5', {'pair': pair, 'payType': 'Крипта' if dirs[0] == 'usdt' else 'По реквизитам'},
            {'cps': [{'id': d, 'name': d, 'dirs': [d]} for d in ('rub', 'thb')]})
    client = client_for('operator')
    for i, direction in enumerate(required):
        state = client.get('/api/stand/state').json
        response = client.post('/api/stand/quote', json={'version': state['version'],
            'dealId': 1474, 'dir': direction, 'cpId': direction, 'rate': '80' if direction == 'rub' else '32'})
        assert response.status_code == 200, response.json
        assert response.json['data']['deals'][0]['step'] == ('s6' if i == len(required)-1 else 's5')

import copy


def put_board(client, mutate, version=True):
    current = client.get('/api/stand/state').json
    proposal = copy.deepcopy(current['data'])
    mutate(proposal)
    body = {'data': proposal}
    if version:
        body['version'] = current['version']
    return client.put('/api/stand/state', json=body)


@pytest.mark.parametrize('version', [None, True, '1', 1.5, -1])
def test_version_is_required_integer(board, version):
    install, clients = board
    install('s5')
    client = clients('operator')
    before = client.get('/api/stand/state').json
    response = client.put('/api/stand/state', json={'data': before['data'], 'version': version})
    assert response.status_code == 400
    assert client.get('/api/stand/state').json == before


@pytest.mark.parametrize('edit', ['erase', 'change', 'reorder'])
def test_past_server_journal_is_immutable(board, edit):
    install, clients = board
    log = [{'text': 'server ping', 'role': 'manager', 'at': 1}, {'text': 'legacy', 'role': 'operator'}]
    install('s5', {'log': log})
    client = clients('operator')
    def mutate(state):
        entries = state['deals'][0]['log']
        if edit == 'erase': entries.clear()
        elif edit == 'change': entries[0]['text'] = 'forged'
        else: entries.reverse()
    response = put_board(client, mutate)
    assert response.status_code == 409
    assert client.get('/api/stand/state').json['data']['deals'][0]['log'] == log


def test_append_log_preserves_legacy_and_attributes_author(board):
    install, clients = board
    install('s5', {'log': [{'text': 'legacy'}]})
    def mutate(state):
        state['deals'][0]['log'][0]['at'] = None
        state['deals'][0]['log'].append({'text': 'human note', 'role': 'teodor', 'at': 1})
    response = put_board(clients('operator'), mutate)
    assert response.status_code == 200, response.json
    entries = response.json['data']['deals'][0]['log']
    assert entries[0] == {'text': 'legacy'}
    assert entries[-1]['role'] == 'operator'
    assert entries[-1]['kind'] == 'comment'
    assert entries[-1]['at'] != 1


def test_forged_service_note_is_not_stored_or_delivered(board):
    install, clients = board
    install('s5')
    response = put_board(clients('manager'), lambda state: state['notes'].append(
        {'id': 'forged', 'dealId': 1474, 'role': 'operator', 'text': 'Теодор подписал, можно отправлять'}))
    assert response.status_code == 200, response.json
    assert not response.json['data']['notes']
    assert not response.json['notification_delivery']


@pytest.mark.parametrize('start,end,role', [('s5','s14','operator'), ('s5','s6','operator'),
    ('s6','s8','manager'), ('s8','s11','manager'), ('s11','s12','operator'),
    ('s12','s14','manager'), ('s18w','s22','operator')])
def test_missing_step_facts_and_jumps_are_rejected(board, start, end, role):
    install, clients = board
    install(start)
    response = put_board(clients(role), lambda state: state['deals'][0].update(step=end))
    assert response.status_code == 409, response.json
    assert clients(role).get('/api/stand/state').json['data']['deals'][0]['step'] == start


def test_verified_rate_handoff_generates_service_note(board):
    install, clients = board
    install('s5', {'pair': 'RUB → USDT', 'rates': {'rubUsdt': '85'}})
    response = put_board(clients('operator'), lambda state: state['deals'][0].update(step='s6'))
    assert response.status_code == 200, response.json
    assert response.json['data']['notes'][0]['role'] == 'manager'
    assert response.json['data']['notes'][0]['text'] == 'Задача на вас: шаг s6'


def test_browser_defaults_do_not_edit_other_roles_task(board):
    install, clients = board
    install('s5', {'amountRub': 100000})
    def mutate(state):
        state['deals'][0].update(compare=False, selfCame=False, quotes=[], ratePick={}, payout=None)
        state['deals'].append({'id': 1475, 'type': 'Обмен валюты', 'step': 's5', 'amountRub': 200000})
    response = put_board(clients('manager'), mutate)
    assert response.status_code == 200, response.json
    assert len(response.json['data']['deals']) == 2
    assert 'compare' not in response.json['data']['deals'][0]


@pytest.mark.parametrize('key,value', [('amountRub', 120000), ('compare', True), ('quotes', [{'rate': 80}])])
def test_real_change_to_other_roles_task_still_rejected(board, key, value):
    install, clients = board
    install('s5', {'amountRub': 100000})
    response = put_board(clients('manager'), lambda state: state['deals'][0].update({key: value}))
    assert response.status_code == 409, response.json


@pytest.mark.parametrize('reset', [False, True])
def test_fresh_and_reset_board_counterparties_are_server_owned(board, reset):
    import app as m
    install, clients = board
    admin = clients('admin')
    if reset:
        assert admin.post('/api/stand/reset').status_code == 200
    else:
        with m.SessionLocal() as db:
            db.query(m.StandState).filter_by(id=1).delete()
            db.commit()
    current = admin.get('/api/stand/state').json
    catalog = current['data']['cps']
    with m.SessionLocal() as db:
        import json
        assert json.loads(db.get(m.StandState, 1).data)['cps'] == catalog
    state = current['data']
    state['deals'] = [{'id': 1474, 'step': 's5', 'type': 'Обмен валюты', 'pair': 'RUB → USDT', 'log': []}]
    saved = clients('manager').put('/api/stand/state', json={'version': current['version'], 'data': state})
    assert saved.status_code == 200, saved.json
    broker = next(c for c in catalog if 'rub' in c['dirs'])
    result = clients('operator').post('/api/stand/quote', json={'version': saved.json['version'],
        'dealId': 1474, 'dir': 'rub', 'cpId': broker['id'], 'rate': '85'})
    assert result.status_code == 200, result.json
    assert result.json['data']['deals'][0]['step'] == 's6'


def test_document_form_depends_on_deal_type():
    subprocess.run(['node', 'tests/test_wave_a_documents.js'], check=True)

@pytest.mark.usefixtures('stand_demo_environment')
def test_all_pair_payloads_are_accepted_and_persisted_by_crm(monkeypatch):
    import json
    import app as m
    from tests.test_stand_crm_close_atomic import _setup, _seed_evidence, _client, _post, _board
    cases = json.loads(subprocess.check_output(['node', 'tests/test_wave_a_exchange.js', '--json']))
    for case in cases:
        uid = _setup(monkeypatch)
        deal, crm = case['deal'], case['crm']
        deal.update(id=1474, step='s27', client='Wave A pair', sentToClient=True, pay={}, log=[])
        crm.update(client_name='Wave A pair')
        deal['files'] = _board()['deals'][0]['files']
        with m.SessionLocal() as db:
            row = db.get(m.StandState, 1)
            state = {'deals': [deal], 'notes': []}
            row.data = json.dumps(state)
            db.commit()
            _seed_evidence(db, row, state, uid)
        assert m._stand_crm_fact_problem(deal, crm, 'exchange') is None, (deal['pair'], crm)
        for field in ('payin_amount_usdt', 'payout_amount_usdt'):
            forged = {**crm, field: crm[field] + 10}
            assert m._stand_crm_fact_problem(deal, forged, 'exchange') is not None
        result = _post(_client(uid), crm=crm)
        assert result.status_code == 201, (deal['pair'], result.json)
        persisted = result.json['deal']
        for key in ('payin_amount_usdt', 'payout_amount_usdt', 'custom_payin_currency', 'custom_payout_currency',
                    'custom_payin_amount', 'custom_payout_amount'):
            assert persisted.get(key) == crm.get(key), (deal['pair'], key, persisted.get(key), crm.get(key))

@pytest.mark.parametrize('pair,direction,expected', [
    ('RUB → USDT', 'rub', '80'), ('RUB → THB', 'thb', '90'),
    ('THB → USDT', 'thb', '80'), ('THB → RUB', 'rub', '90')])
def test_best_quote_respects_conversion_direction(board, pair, direction, expected):
    install, clients = board
    install('s5', {'pair': pair}, {'cps': [{'id': n, 'name': n, 'dirs': [direction]} for n in ('low', 'high')]})
    client = clients('operator')
    for cp, rate in [('low', '80'), ('high', '90')]:
        current = client.get('/api/stand/state').json
        result = client.post('/api/stand/quote', json={'version': current['version'], 'dealId':1474,
                                                    'dir': direction, 'cpId': cp, 'rate': rate})
        assert result.status_code == 200, result.json
    assert result.json['data']['deals'][0]['rates']['rubUsdt' if direction == 'rub' else 'usdtThb'] == expected


def test_output_anchor_is_not_crypto_payin():
    from stand_workflow import is_crypto
    assert not is_crypto({'type':'Обмен валюты', 'pair':'RUB → USDT', 'curBase':'usdt'})
    assert not is_crypto({'type':'Обмен валюты', 'pair':'THB → USDT', 'curBase':'usdt'})

@pytest.mark.parametrize('pair,incoming,outgoing,rate,doc_pair', [
    ('RUB → THB', 27000, 10000, 2.7, 'RUB_THB'),
    ('THB → RUB', 10000, 27000, 2.7, 'THB_RUB'),
    ('RUB → USDT', 85000, 1000, 85, 'RUB_USDT'),
    ('THB → USDT', 31200, 1000, 31.2, 'THB_USDT')])
def test_exchange_document_money_uses_pair(pair, incoming, outgoing, rate, doc_pair):
    import app as m
    import doc_routes
    fields = {'fio':'Synthetic Client', 'passNo':'1234567890', 'amountPay':str(incoming),
              'amountThb':str(outgoing), 'rate':str(rate), 'purpose':'Exchange',
              'payTo':'Synthetic bank account','payoutNetwork':'TRON (TRC-20)',
              'payoutWallet':'TKkeEVf2zySaWTLyX2qPwvi6kcdHRuPxkJ'}
    result = m._stand_doc_request({}, {'type':'Обмен валюты','pair':pair,'payType':'По реквизитам'}, fields)
    assert 'error' not in result, result
    money = doc_routes.normalize(result['money'], 'payment')
    assert money['pair'] == doc_pair
    assert money['total_payin'] == str(incoming)
    assert money['transfer_amount'] == str(outgoing)
    assert money['payin_currency'] == doc_pair.split('_')[0]
    assert money['transfer_currency'] == doc_pair.split('_')[1]
    assert doc_routes.validate(money, 'payment') == []


def test_deleting_deal_cannot_erase_journal(board):
    install, clients = board
    install('s5', {'log':[{'role':'system','text':'Server event','at':1}]})
    response = put_board(clients('admin'), lambda state: state.update(deals=[]))
    assert response.status_code == 409
    assert clients('admin').get('/api/stand/state').json['data']['deals'][0]['log'][0]['text'] == 'Server event'
