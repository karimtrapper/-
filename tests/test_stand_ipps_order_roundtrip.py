"""Browser JSON number round-trips preserve a claimed IPPS order's fingerprint."""
import copy
import json
import subprocess

import pytest

from tests.test_stand_files_storage import (
    api, base_api, fake_role_api, clear_file_rows, board, upload, read_db, seed, m,
)


@pytest.fixture
def claimed_ipps(api):
    api[1][0] = 'operator'
    address = 'TQgQCBXkewuW4RoieDKFP9Ko2SopBh8jso'
    with m.SessionLocal() as db:
        wallet = m.Wallet(address=address, active=True, blockchain='TRON',
                          initiator_roles='["operator"]', confirmer_roles='["teodor"]',
                          owner_can_alone=True)
        db.add(wallet)
        db.commit()
        wallet_id, fields = wallet.id, wallet.to_dict()
    try:
        state = board('s26')
        deal = state['deals'][0]
        deal.update(walletId=wallet_id, transfer={'amount': 10000, 'addr': address,
                    'net': 'TRC-20', 'sends': []},
                    ippsPayoutOrder={'amount': 10000.0, 'address': address,
                                     'network': 'TRC-20', 'confirmedAt': '2026-11-18T01:00:00Z'})
        state['wallets'] = [dict(id=wallet_id, addr=address, multisig=False,
            **{k: fields[k] for k in ('purpose', 'limit_usd', 'initiator_roles',
               'confirmer_roles', 'owner_can_alone', 'signer_addresses')})]
        with m.SessionLocal() as db:
            policy = m._stand_transfer_policy(db, state, deal)
        deal['transferClaim'] = {'byId': 987, 'role': 'findir',
                                 'fingerprint': policy['fingerprint']}
        deal['transferConfirmation'] = {'byId': 988, 'serverComplete': True}
        seed(state)
        yield state
    finally:
        with m.SessionLocal() as db:
            db.query(m.Wallet).filter_by(id=wallet_id).delete()
            db.commit()


def browser_json(value):
    script = "let s='';process.stdin.on('data',x=>s+=x);process.stdin.on('end',()=>process.stdout.write(JSON.stringify(JSON.parse(s))));"
    return json.loads(subprocess.run(['node', '-e', script], input=json.dumps(value),
                      text=True, capture_output=True, check=True).stdout)


@pytest.mark.parametrize('auto', [False, True])
def test_sequential_uploads_and_browser_roundtrip_put_preserve_claim(api, claimed_ipps, auto):
    state = claimed_ipps
    if auto:
        state['deals'][0].update(autoPayment=True, payType='По реквизитам',
            invoiceCurrency='usd', autoRequestMode='usd', requestedUsd=10000, invoiceUsd=10000)
        seed(state)
    for kind in ('payment_order', 'receipt'):
        raw = b'%PDF-1.4\n' + kind.encode()
        response = upload(api, raw, kind)
        assert response.status_code == 200, response.json
        payload = browser_json({'version': response.json['version'], 'fileStorageVersion': 1,
                                'data': response.json['data']})
        assert type(payload['data']['deals'][0]['ippsPayoutOrder']['amount']) is int
        saved = api[0].put('/api/stand/state', json=payload)
        assert saved.status_code == 200, saved.json
        _, stored = read_db()
        deal = stored['deals'][0]
        assert type(deal['ippsPayoutOrder']['amount']) is float
        assert deal['ippsPayoutOrder'] == state['deals'][0]['ippsPayoutOrder']
        assert deal['transferClaim'] == state['deals'][0]['transferClaim']
        assert api[0].get(f'/api/stand/file/1473/{kind}/0').data == raw
    assert set(read_db()[1]['deals'][0]['files']) == {'payment_order', 'receipt'}


@pytest.mark.parametrize('field,value', [
    ('amount', 10000.00000001), ('amount', '10000'), ('amount', True),
    ('amount', float('inf')), ('amount', float('nan')),
    ('address', 'different-recipient'), ('network', 'ERC-20'),
    ('confirmedAt', '2026-11-18T02:00:00Z'),
])
def test_roundtrip_normalization_retains_order_mutation_guard(api, claimed_ipps, field, value):
    payload = browser_json({'version': 1, 'data': claimed_ipps})
    payload['data']['deals'][0]['ippsPayoutOrder'][field] = value
    response = api[0].put('/api/stand/state', json=payload)
    assert response.status_code == 409, response.json
    assert 'После взятия отправки' in response.json['error']
    assert read_db() == (1, claimed_ipps)


def test_equal_boolean_does_not_replace_stored_number(api, claimed_ipps):
    state = copy.deepcopy(claimed_ipps)
    deal = state['deals'][0]
    deal['ippsPayoutOrder']['amount'] = 1.0
    with m.SessionLocal() as db:
        deal['transferClaim']['fingerprint'] = m._stand_transfer_policy(db, state, deal)['fingerprint']
    seed(state)
    changed = copy.deepcopy(state)
    changed['deals'][0]['ippsPayoutOrder']['amount'] = True
    response = api[0].put('/api/stand/state', json={'version': 1, 'data': changed})
    assert response.status_code == 409, response.json
    assert 'После взятия отправки' in response.json['error']
    assert type(read_db()[1]['deals'][0]['ippsPayoutOrder']['amount']) is float


@pytest.mark.parametrize('order', ['invalid-order', ['invalid-order']])
def test_non_object_order_still_reaches_claim_guard(api, claimed_ipps, order):
    changed = copy.deepcopy(claimed_ipps)
    changed['deals'][0]['ippsPayoutOrder'] = order
    response = api[0].put('/api/stand/state', json={'version': 1, 'data': changed})
    assert response.status_code == 409, response.json
    assert 'После взятия отправки' in response.json['error']
