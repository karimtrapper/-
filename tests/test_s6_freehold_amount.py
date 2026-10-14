"""Explicit RUB principal survives s6, document generation and legacy reads."""
import copy
import subprocess
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


@pytest.mark.parametrize('invoice,amount,rate,stale', [
    (97500, 8123456.78, '83,317505', '8123456.25'),
    (88320, 933382.32, '10,568187', '933382.28'),
])
def test_explicit_sum_in_all_generated_documents(stand, invoice, amount, rate, stale):
    d = _deal(9908, **{k:v for k,v in rub_board('s11', True)['deals'][0].items() if k != 'id'})
    d.update(invoiceUsd=invoice, amountRub=amount)
    d['rates']['client'] = rate
    stand.put_board([d])
    # Stale form amounts must never replace the approved principal.
    fields = _fields(amountThb=str(invoice), amountPay=stale, rate=rate)
    response = stand.post('/api/stand/docs/issue', json={'dealId': d['id'], 'docFields': fields})
    assert response.status_code == 200, response.json
    assert [x['kind'] for x in response.json['issued']] == ['dog', 'app', 'bill']
    for entry in response.json['issued']:
        text = _text(stand, entry['docId']).replace('\xa0','').replace(' ','')
        assert stale not in text and stale.replace('.', ',') not in text
        # Framework agreement delegates payment amounts to Payment Instruction.
        if entry['kind'] != 'dog':
            assert str(amount) in text or str(amount).replace('.', ',') in text, (entry['kind'],text)
    saved = stand.get('/api/stand/state').json['data']['deals'][0]
    assert saved['amountRub'] == amount
    assert saved['docFields']['amountPay'] == str(amount)


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


def test_ieee754_halfway_rate_accepts_s6_without_changing_principal(monkeypatch):
    rate = subprocess.check_output(['node', '-e',
        "process.stdout.write((Math.round(933382.32/88320*1e6)/1e6).toFixed(6))"], text=True)
    assert rate == '10.568187'  # Decimal HALF_UP gives 10.568188.
    state = rub_board()
    state['deals'][0].update(invoiceUsd=88320, amountRub=933382.32)
    client = seed(monkeypatch, state)
    monkeypatch.setattr(m, 'current_role', lambda: 'manager')
    before = snapshot(client)
    changed = copy.deepcopy(before['data'])
    deal = changed['deals'][0]
    deal.update(step='s8', freeholdClientInput='sum')
    deal['rates']['client'] = rate.replace('.', ',')
    response = client.put('/api/stand/state', json={'version': before['version'], 'data': changed})
    assert response.status_code == 200, response.json
    assert response.json['data']['deals'][0]['amountRub'] == 933382.32
    # Only one last-place unit is tolerated; a larger mismatch remains invalid.
    deal['rates']['client'] = '10,568186'
    assert m._stand_freehold_explicit_rub_problem(deal) == 'freehold_client_rate_mismatch'
