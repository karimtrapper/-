"""Совместная работа правки реквизитов и фактического кошелька предоплаты."""
from tests.test_stand_freehold_e2e_fixes import (
    api, base_api, chain, initial_board, prepare_after_rub, ipps_order,
    send_ipps, send_broker, post, edit,
)
from tests.test_stand_prepay import IPPS, TEODOR


def test_reopened_prepaid_order_keeps_payer_and_accepts_actual_broker_wallet(api, chain, monkeypatch):
    monkeypatch.delenv('STAND_ALLOW_DEMO', raising=False)
    initial_board(api)
    saved = prepare_after_rub(api)
    post(api, 'operator', '/api/stand/prepay', action='start', dealId=1484,
         walletId='teodor', version=saved['version'])
    saved = ipps_order(api, IPPS)
    original_prepay = saved['data']['deals'][0]['prepay']
    reopened = post(api, 'manager', '/api/stand/payto/reopen', dealId=1484,
                    version=saved['version'])
    d = reopened['data']['deals'][0]
    assert d['step'] == 's22' and d['prepay'] == original_prepay
    assert not d.get('ippsPayoutOrder') and not d.get('payToConfirm')
    assert not d['transfer'].get('addr')
    edit(api, 'manager', lambda s, d: d['payTo'].update(acc='UPDATED-DEVELOPER-ACCOUNT'))
    ipps_order(api, IPPS)
    paid = send_ipps(api, chain, personal=True)
    assert paid['data']['deals'][0]['step'] == 's26'
    saved = send_broker(api)
    changed = post(api, 'operator', '/api/stand/incoming/wallet', dealId=1484,
                   walletId='founder', version=saved['version'])
    d = changed['data']['deals'][0]
    assert d['prepay']['wallet']['addr'] == TEODOR
    assert d['transfer']['addr'] == IPPS
    assert d['serverTransferComplete'] and d['prepay']['brokerStep'] == 's18w'
    assert not d['demoTransfers']
    assert changed['data']['convs'][0]['walletId'] == 'founder'
