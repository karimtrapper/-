"""Explicit RUB principal survives s6, document generation and legacy reads."""
import copy
import pytest
import app as m
from tests.test_stand_freehold_amount import board, seed, snapshot
from tests.test_stand_docs import stand, _deal, _fields, _text


def rub_board(step='s6', explicit=False):
    state = board(step=step)
    d = state['deals'][0]
    d.update(payType='По реквизитам', amountRub=8123456.78,
             rates={'client': '83,317505', 'rubUsdt': '80'}, invoiceCurrency='usd')
    if explicit:
        d['freeholdClientInput'] = 'sum'
    return state


def test_s6_explicit_sum_preserved_and_guards_retained(monkeypatch):
    client = seed(monkeypatch, rub_board())
    monkeypatch.setattr(m, 'current_role', lambda: 'manager')
    before = snapshot(client)
    state = copy.deepcopy(before['data'])
    state['deals'][0].update(step='s8', freeholdClientInput='sum')
    response = client.put('/api/stand/state', json={'version': before['version'], 'data': state})
    assert response.status_code == 200, response.json
    assert response.json['data']['deals'][0]['amountRub'] == 8123456.78
    assert client.put('/api/stand/state', json={'version': before['version'], 'data': state}).status_code == 409
    assert client.put('/api/stand/state', json={'data': state}).status_code == 400


@pytest.mark.parametrize('amount,rate', [(0, '83,317505'), (8123456.78, '83,3175'), (-1, '83,317505')])
def test_explicit_sum_does_not_bypass_money_checks(monkeypatch, amount, rate):
    client = seed(monkeypatch, rub_board())
    before = snapshot(client)
    state = copy.deepcopy(before['data'])
    state['deals'][0].update(step='s8', freeholdClientInput='sum', amountRub=amount)
    state['deals'][0]['rates']['client'] = rate
    response = client.put('/api/stand/state', json={'version': before['version'], 'data': state})
    assert response.status_code == 409, response.json
    assert snapshot(client) == before


def test_old_completed_s6_read_is_unchanged(monkeypatch):
    state = rub_board('s12')
    state['deals'][0]['rates']['client'] = '83,3175'
    client = seed(monkeypatch, state)
    first = snapshot(client)
    assert snapshot(client) == first
    assert first['data']['deals'][0]['amountRub'] == 8123456.78
    assert 'freeholdClientInput' not in first['data']['deals'][0]


def test_explicit_sum_in_all_generated_documents(stand):
    d = _deal(9908, **{k:v for k,v in rub_board('s11', True)['deals'][0].items() if k != 'id'})
    stand.put_board([d])
    # Stale form amounts must never replace the approved principal.
    fields = _fields(amountThb='97500', amountPay='8123456.25', rate='83.3175')
    response = stand.post('/api/stand/docs/issue', json={'dealId': d['id'], 'docFields': fields})
    assert response.status_code == 200, response.json
    assert [x['kind'] for x in response.json['issued']] == ['dog', 'app', 'bill']
    for entry in response.json['issued']:
        text = _text(stand, entry['docId']).replace('\xa0','').replace(' ','')
        assert '8123456.25' not in text and '8123456,25' not in text
        # Framework agreement delegates payment amounts to Payment Instruction.
        if entry['kind'] != 'dog':
            assert '8123456.78' in text or '8123456,78' in text, (entry['kind'],text)
    saved = stand.get('/api/stand/state').json['data']['deals'][0]
    assert saved['amountRub'] == 8123456.78
    assert saved['docFields']['amountPay'] == '8123456.78'


@pytest.mark.parametrize('tamper', ['skip', 'journal'])
def test_explicit_sum_keeps_transition_and_journal_guards(monkeypatch, tamper):
    state = rub_board(explicit=True)
    state['deals'][0]['log'] = [{'text': 'Saved history', 'at': 1, 'role': 'manager'}]
    client = seed(monkeypatch, state)
    before = snapshot(client)
    changed = copy.deepcopy(before['data'])
    changed['deals'][0]['step'] = 's14' if tamper == 'skip' else 's8'
    if tamper == 'journal':
        changed['deals'][0]['log'] = []
    response = client.put('/api/stand/state', json={'version': before['version'], 'data': changed})
    assert response.status_code == 409, response.json
    assert snapshot(client) == before
