"""T17 manual crypto extra uses amount_usdt in the saved stand hash."""
import copy
import errno
import json
import os
import secrets
import threading

import app as m
import requests
import pytest
from werkzeug.serving import make_server


MAIN_HASH = 'a' * 64
EXTRA_HASH = 'b' * 64


def _setup(monkeypatch):
    monkeypatch.setattr(m, 'STAND_MODE', True)
    m._stand_migrate()
    db = m.get_session()
    try:
        manager = m.AdminUser(username='t24-extra-' + secrets.token_hex(6),
                              display_name='T24 extra manager', role='manager',
                              password_hash='unused')
        db.add(manager)
        db.flush()
        row = db.query(m.StandState).filter_by(id=1).first()
        if row is None:
            row = m.StandState(id=1)
            db.add(row)
        row.data = json.dumps({'deals': [], 'notes': []})
        row.version = 1
        row.generation = secrets.token_hex(16)
        db.commit()
        return manager.id
    finally:
        db.close()


def _counts():
    db = m.get_session()
    try:
        return db.query(m.Deal).count(), db.query(m.StandCrmLink).count()
    finally:
        db.close()


def _server():
    start = int(os.environ['CALCCRM_FENCE_PORT_START'])
    for port in range(start + 63, start - 1, -1):
        try:
            return port, make_server('127.0.0.1', port, m.app, threaded=True)
        except OSError as exc:
            if exc.errno != errno.EADDRINUSE:
                raise
    raise AssertionError('fenced HTTP port pool exhausted')


@pytest.mark.parametrize('legacy_amount', [False, True])
def test_manual_crypto_extra_canonical_and_legacy_hash_amounts(monkeypatch, legacy_amount):
    uid = _setup(monkeypatch)
    port, server = _server()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    cookie = m.app.session_interface.get_signing_serializer(m.app).dumps({'user_id': uid})
    headers = {'Cookie': 'session=' + cookie}
    base = f'http://127.0.0.1:{port}/api/stand'
    stand_id = 1481
    extra_tx = {'hash': EXTRA_HASH, 'amount': 20} if legacy_amount else {
        'hash': EXTRA_HASH, 'amount_usdt': 20}
    board = {'deals': [{
        'id': stand_id, 'code': f'СД-{stand_id}', 'client': 'T24 extra synthetic',
        'type': 'Обмен валюты', 'manual': True, 'manualNew': False,
        'step': 'manual', 'closed': False, 'crmDealId': None,
        'sentToClient': False, 'isTask': False, 'files': {}, 'log': [],
        'payType': 'Крипта', 'paySrc': 'cash', 'amountUsdt': 100,
        'payinHashes': [{'hash': MAIN_HASH, 'amount': 100, 'network': 'TRC20'}],
        'payinExtra': [{'method': 'crypto_direct', 'amount_usdt': 20,
                        'partner_name': 'T24 extra partner', 'tx_hashes': [extra_tx]}],
        'payout': {'usdt': 90, 'thb': 3000}, 'pay': {},
    }], 'notes': []}
    crm = {'deal_kind': 'exchange', 'client_name': 'T24 extra synthetic',
           'manager_name': 'T24 manager', 'payin_method': 'crypto_direct',
           'payin_amount_usdt': 100,
           'payin_tx_hashes': [{'hash': MAIN_HASH, 'network': 'trc20',
                                'amount_usdt': 100}],
           'payin_extra': [{'method': 'crypto_direct', 'amount_usdt': 20,
                            'partner_name': 'T24 extra partner', 'tx_hashes': [
                                {'hash': EXTRA_HASH, 'network': 'trc20',
                                 'amount_usdt': 20}]}],
           'payout_method': 'transfer', 'payout_source': 'cash_batch',
           'payout_amount_usdt': 90, 'payout_amount_thb': 3000}
    try:
        with requests.Session() as transport:
            created = transport.put(base + '/state', headers=headers,
                json={'version': 1, 'data': board}, timeout=10)
            assert created.status_code == 200, created.text
            assert created.json()['data']['deals'][0]['originMode'] == 'manual'
            version = created.json()['version']
            valid_data = created.json()['data']
            before = _counts()
            close_url = base + f'/deals/{stand_id}/crm-close'

            def close(payload=None, use_version=None):
                return transport.post(close_url, headers=headers,
                    json={'version': version if use_version is None else use_version,
                          'crm': crm if payload is None else payload}, timeout=10)

            for change in ('hash', 'remove', 'network', 'amount',
                           'dual_amount', 'dual_network', 'crm_legacy_only'):
                wrong = copy.deepcopy(crm)
                tx = wrong['payin_extra'][0]['tx_hashes'][0]
                if change == 'hash':
                    tx['hash'] = 'c' * 64
                elif change == 'remove':
                    wrong['payin_extra'][0]['tx_hashes'] = []
                elif change == 'network':
                    tx['network'] = 'erc20'
                elif change == 'amount':
                    tx['amount_usdt'] = 21
                elif change == 'dual_amount':
                    tx['amount'] = 21
                elif change == 'crm_legacy_only':
                    tx['amount'] = tx.pop('amount_usdt')
                else:
                    tx['net'] = 'ERC20'
                denied = close(wrong)
                print('EXTRA_CRM_NEGATIVE', legacy_amount, change,
                      denied.status_code, denied.json().get('error'))
                assert denied.status_code == 409 and denied.json()['error'] == 'payin_extra_mismatch', (change, denied.text)
                assert _counts() == before
                state = transport.get(base + '/state', headers=headers, timeout=10).json()
                assert state['version'] == version
                assert state['data']['deals'][0]['crmDealId'] is None

            # Stand-side contradictions are saved through the real PUT, then
            # rejected at close. A transfer amount 30 cannot fund a part 20:
            # T17 stores per-part allocated shares, not whole-chain capacity.
            for change in ('dual_amount', 'dual_network', 'part_hash_mismatch'):
                state = transport.get(base + '/state', headers=headers, timeout=10).json()
                modified = copy.deepcopy(state['data'])
                tx = modified['deals'][0]['payinExtra'][0]['tx_hashes'][0]
                if change == 'dual_amount':
                    tx['amount_usdt' if legacy_amount else 'amount'] = 21
                elif change == 'dual_network':
                    tx.update(net='ERC20', network='TRC20')
                else:
                    tx['amount' if legacy_amount else 'amount_usdt'] = 30
                saved = transport.put(base + '/state', headers=headers,
                    json={'version': version, 'data': modified}, timeout=10)
                assert saved.status_code == 200, (change, saved.text)
                version = saved.json()['version']
                saved_extra = saved.json()['data']['deals'][0]['payinExtra']
                assert saved_extra == modified['deals'][0]['payinExtra']
                wrong_crm = copy.deepcopy(crm)
                if change == 'part_hash_mismatch':
                    wrong_crm['payin_extra'][0]['tx_hashes'][0]['amount_usdt'] = 30
                denied = close(wrong_crm, version)
                print('EXTRA_STAND_NEGATIVE', legacy_amount, change,
                      denied.status_code, denied.json().get('error'))
                assert denied.status_code == 409 and denied.json()['error'] == 'payin_extra_mismatch', (change, denied.text)
                assert _counts() == before
                after_denial = transport.get(base + '/state', headers=headers, timeout=10).json()
                assert after_denial['version'] == version
                assert after_denial['data']['deals'][0]['payinExtra'] == saved_extra
                assert after_denial['data']['deals'][0]['crmDealId'] is None
                restored = transport.put(base + '/state', headers=headers,
                    json={'version': version, 'data': valid_data}, timeout=10)
                assert restored.status_code == 200, (change, restored.text)
                version = restored.json()['version']

            accepted = close()
            print('EXTRA_CANONICAL_CLOSE', accepted.status_code, accepted.json().get('error'))
            assert accepted.status_code == 201, accepted.text
            crm_id = accepted.json()['deal']['id']
            assert accepted.json()['deal']['payin_amount_usdt'] == 120
            assert accepted.json()['data']['deals'][0]['closed'] is True
            assert accepted.json()['data']['deals'][0]['crmDealId'] == crm_id
            assert _counts() == (before[0] + 1, before[1] + 1)
            db = m.get_session()
            try:
                saved = db.query(m.Deal).filter_by(id=crm_id).one()
                extra = json.loads(saved.payin_extra)
                assert len(extra) == 1 and extra[0]['amount_usdt'] == 20
                assert extra[0]['tx_hashes'][0]['hash'] == EXTRA_HASH
                assert extra[0]['tx_hashes'][0]['amount_usdt'] == 20
            finally:
                db.close()
            replay = close({**crm, 'payin_amount_usdt': 999999})
            assert replay.status_code == 200 and replay.json()['duplicate'] is True
            assert replay.json()['deal']['id'] == crm_id
            assert _counts() == (before[0] + 1, before[1] + 1)
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


@pytest.mark.parametrize('variant', ['main_extra', 'extra_extra', 'distinct'])
def test_manual_extra_raw_hash_reuse(monkeypatch, variant):
    """Real PUT/close: one raw receipt must not fund multiple allocated parts."""
    uid = _setup(monkeypatch)
    port, server = _server()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    cookie = m.app.session_interface.get_signing_serializer(m.app).dumps({'user_id': uid})
    headers = {'Cookie': 'session=' + cookie}
    base = f'http://127.0.0.1:{port}/api/stand'
    first_hash = MAIN_HASH if variant == 'main_extra' else EXTRA_HASH
    extra_specs = [(first_hash, 10)]
    if variant != 'main_extra':
        extra_specs.append((EXTRA_HASH if variant == 'extra_extra' else 'c' * 64, 20))
    board_extras = [
        {'method': 'crypto_direct', 'amount_usdt': amount,
         'tx_hashes': [{'hash': hash_value, 'network': 'TRC20', 'amount_usdt': amount}]}
        for hash_value, amount in extra_specs]
    crm_extras = [
        {'method': 'crypto_direct', 'amount_usdt': amount,
         'tx_hashes': [{'hash': hash_value, 'network': 'trc20', 'amount_usdt': amount}]}
        for hash_value, amount in extra_specs]
    board = {'deals': [{
        'id': 1482, 'code': 'СД-1482', 'client': 'T24 duplicate probe',
        'type': 'Обмен валюты', 'manual': True, 'manualNew': False,
        'step': 'manual', 'closed': False, 'crmDealId': None,
        'sentToClient': False, 'isTask': False, 'files': {}, 'log': [],
        'payType': 'Крипта', 'paySrc': 'cash', 'amountUsdt': 100,
        'payinHashes': [{'hash': MAIN_HASH, 'amount': 100, 'network': 'TRC20'}],
        'payinExtra': board_extras, 'payout': {'usdt': 90, 'thb': 3000}, 'pay': {},
    }], 'notes': []}
    crm = {'deal_kind': 'exchange', 'client_name': 'T24 duplicate probe',
           'manager_name': 'T24 manager', 'payin_method': 'crypto_direct',
           'payin_amount_usdt': 100,
           'payin_tx_hashes': [{'hash': MAIN_HASH, 'network': 'trc20',
                                'amount_usdt': 100}],
           'payin_extra': crm_extras, 'payout_method': 'transfer',
           'payout_source': 'cash_batch', 'payout_amount_usdt': 90,
           'payout_amount_thb': 3000}
    try:
        with requests.Session() as transport:
            created = transport.put(base + '/state', headers=headers,
                                    json={'version': 1, 'data': board}, timeout=10)
            assert created.status_code == 200, created.text
            version = created.json()['version']
            saved_board = created.json()['data']['deals'][0]
            assert saved_board['payinExtra'] == board_extras
            before = _counts()
            response = transport.post(base + '/deals/1482/crm-close', headers=headers,
                                      json={'version': version, 'crm': crm}, timeout=10)
            state = transport.get(base + '/state', headers=headers, timeout=10).json()
            after = _counts()
            print('EXTRA_RAW_HASH_PROBE', variant, response.status_code,
                  response.json().get('error'), before, after, version,
                  state['version'], state['data']['deals'][0]['crmDealId'])
            if variant == 'distinct':
                assert response.status_code == 201, response.text
                assert after == (before[0] + 1, before[1] + 1)
                assert state['data']['deals'][0]['crmDealId'] == response.json()['deal']['id']
            else:
                assert response.status_code == 409, response.text
                assert response.json()['error'] == 'payin_extra_duplicate_hash'
                assert after == before
                assert state['version'] == version
                assert state['data']['deals'][0] == saved_board
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
