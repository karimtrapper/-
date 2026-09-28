"""Real HTTP cash workflow: evidence alone cannot supply missing USDT money."""
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


def _setup(monkeypatch):
    monkeypatch.setattr(m, 'STAND_MODE', True)
    m._stand_migrate()
    db = m.get_session()
    try:
        manager = m.AdminUser(username='t24mf-' + secrets.token_hex(6),
                              display_name='T24 MF Manager', role='manager',
                              password_hash='unused')
        operator = m.AdminUser(username='t24mf-' + secrets.token_hex(6),
                               display_name='T24 MF Operator', role='operator',
                               password_hash='unused')
        db.add(manager); db.add(operator)
        db.flush()
        mgr_id, op_id = manager.id, operator.id
        row = db.query(m.StandState).filter_by(id=1).first()
        if row is None:
            row = m.StandState(id=1)
            db.add(row)
        row.data = json.dumps({'deals': [], 'notes': []})
        row.version = 1
        row.generation = secrets.token_hex(16)
        db.commit()
        return mgr_id, op_id
    finally:
        db.close()


def _counts():
    db = m.get_session()
    try:
        return db.query(m.Deal).count(), db.query(m.StandCrmLink).count()
    finally:
        db.close()


@pytest.mark.parametrize('claimed_usdt,rub_amount,broker_rate,expected_status', [
    (1, 9200, None, 409), (999999, 9200, None, 409),
    (996.60, 100000, 100, 201), (999, 100000, 100, 409),
    (996.75, 100015, 100, 201),
])
def test_cash_payin_requires_persisted_basis(
        monkeypatch, claimed_usdt, rub_amount, broker_rate, expected_status):
    """Manager/operator use only real endpoints; no evidence rows are seeded."""
    mgr_id, op_id = _setup(monkeypatch)
    # Earlier full-suite port-zero fixtures can leave a listener in the
    # fenced pool. Bind atomically from its far end; use only the exact ports
    # granted by the wrapper's sandbox profile.
    start = int(os.environ['CALCCRM_FENCE_PORT_START'])
    for port in range(start + 63, start - 1, -1):
        try:
            server = make_server('127.0.0.1', port, m.app, threaded=True)
            break
        except OSError as exc:
            if exc.errno != errno.EADDRINUSE:
                raise
    else:
        raise AssertionError('fenced HTTP port pool exhausted')
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    serializer = m.app.session_interface.get_signing_serializer(m.app)
    mgr_headers = {'Cookie': 'session=' + serializer.dumps({'user_id': mgr_id})}
    op_headers = {'Cookie': 'session=' + serializer.dumps({'user_id': op_id})}
    base = f'http://127.0.0.1:{port}/api/stand'
    baseline = _counts()
    log = []
    try:
        with requests.Session() as t:
            deal_id = 8100 + int(claimed_usdt) % 97
            deal = {'id': deal_id, 'code': f'СД-{deal_id}', 'client': 'T24 MF probe',
                    'type': 'Обмен валюты', 'step': 's6', 'closed': False,
                    'crmDealId': None, 'sentToClient': False, 'payType': 'Наличные',
                    'pay': {}, 'log': []}
            r1 = t.put(base + '/state', json={'version': 1,
                       'data': {'deals': [deal], 'notes': []}}, headers=mgr_headers, timeout=10)
            log.append(('create_draft', r1.status_code, r1.json().get('error')))
            assert r1.status_code == 200, r1.json()

            state = r1.json()['data']
            advanced = copy.deepcopy(state)
            d = advanced['deals'][0]
            d.update(step='s27', sentToClient=True, incomeAmount=rub_amount,
                     client='T24 MF probe')
            if broker_rate:
                d['rates'] = {'broker': broker_rate}
            d['files'] = {'receipt': [{'file': 'receipt.pdf', 'mime': 'application/pdf',
                                       'data': 'data:application/pdf;base64,JVBERi0='}]}
            r2 = t.put(base + '/state', json={'version': r1.json()['version'],
                       'data': advanced}, headers=mgr_headers, timeout=10)
            log.append(('advance_s27_cash_rub_only', r2.status_code, r2.json().get('error')))
            assert r2.status_code == 200, r2.json()
            assert d.get('amountUsdt') is None and d.get('payinHashes') is None
            assert (d.get('pay') or {}).get('usdt') is None

            r3 = t.post(base + f'/deals/{deal_id}/close-evidence',
                       json={'version': r2.json()['version'], 'kind': 'payin'},
                       headers=op_headers, timeout=10)
            log.append(('payin_evidence', r3.status_code, r3.json()))
            payin_evidence_admitted = r3.status_code == 200

            version = r3.json().get('version', r2.json()['version'])
            payout_deal = t.get(base + '/state', headers=mgr_headers, timeout=10).json()['data']
            pd = payout_deal['deals'][0]
            pd.update(paySrc='cash', client='T24 MF probe',
                      payout={'thb': 3000, 'usdt': 90})
            r4 = t.put(base + '/state', json={'version': version, 'data': payout_deal},
                      headers=mgr_headers, timeout=10)
            log.append(('set_payout_facts', r4.status_code, r4.json().get('error')))
            assert r4.status_code == 200, r4.json()
            r5 = t.post(base + f'/deals/{deal_id}/close-evidence',
                       json={'version': r4.json()['version'], 'kind': 'payout'},
                       headers=op_headers, timeout=10)
            log.append(('payout_evidence', r5.status_code, r5.json()))
            payout_evidence_admitted = r5.status_code == 200

            close_version = r5.json().get('version', r4.json()['version'])
            crm = {'deal_kind': 'exchange', 'client_name': 'T24 MF probe',
                   'manager_name': 'QA', 'payin_method': 'partners_cash',
                   'payin_amount_usdt': claimed_usdt, 'payin_amount_rub': rub_amount,
                   'payout_method': 'transfer', 'payout_source': 'cash_batch',
                   'payout_amount_usdt': 90, 'payout_amount_thb': 3000}
            r6 = t.post(base + f'/deals/{deal_id}/crm-close',
                       json={'version': close_version, 'crm': crm},
                       headers=mgr_headers, timeout=10)
            log.append(('crm_close', r6.status_code, r6.json()))
        print('MISSING_FACTS_PROBE claimed_usdt=', claimed_usdt,
              'payin_evidence_admitted=', payin_evidence_admitted,
              'payout_evidence_admitted=', payout_evidence_admitted,
              'close_status=', r6.status_code,
              'committed_usdt=', (r6.json().get('deal') or {}).get('payin_amount_usdt'))
        for step in log:
            print('STEP', step)
        assert r6.status_code == expected_status, r6.json()
        if expected_status == 409:
            assert r6.json().get('error') == ('payin_basis_missing' if broker_rate is None else
                                             'payin_amount_mismatch')
        else:
            assert r6.json()['deal']['payin_amount_usdt'] == claimed_usdt
        assert _counts() == ((baseline[0] + 1, baseline[1] + 1) if expected_status == 201
                             else baseline)
        print('VERDICT', 'BOUND_TO_PERSISTED_RUB_AND_RATE' if expected_status == 201
              else 'REJECTED_UNBOUND_MONEY', r6.json().get('error'))
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
