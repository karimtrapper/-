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
