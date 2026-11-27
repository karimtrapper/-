"""Browser regression for correcting a broker transfer before accepting a batch."""
import json
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright

import app as appmod
from tests.test_stand_docs import _deal
from tests.test_stand_transfers import FROM, TO


@pytest.mark.browser
@pytest.mark.parametrize('role', ['operator', 'admin'])
def test_unlink_broker_hash_with_preview_and_incoming_reload(monkeypatch, pytestconfig, role):
    monkeypatch.setattr(appmod, 'STAND_MODE', True)
    appmod._stand_migrate()
    deal_id = 481
    batch_id = 17
    wrong_hash = ('a3' if role == 'operator' else 'c4') * 32
    preview_hash = 'fa' * 32
    reason_text = 'Выбран перевод другой пачки'

    with appmod.get_session() as db:
        user = appmod.AdminUser(username='browser_unlink_' + role, role=role, password_hash='unused')
        crm = appmod.Conversion(status=appmod.ConversionStatus.SENT)
        tx = appmod.PayinTx(tx_hash=wrong_hash, source='tronscan', network='trc20',
                           amount_usdt=149, to_address=TO)
        db.add_all([user, crm, tx])
        db.flush()
        row = appmod._stand_row(db)
        use = appmod.PayinTxUse(tx_id=tx.id, stand_generation=row.generation,
                              stand_cnv_id=str(batch_id), amount_usdt=149)
        db.add(use)
        db.flush()
        row.data = json.dumps({
            'deals': [_deal(deal_id, step='s18w', cnvId=batch_id)],
            'wallets': [{'id': 'broker-wallet', 'name': 'QA', 'addr': TO, 'owner': 'QA'}],
            'convs': [{'id': batch_id, 'name': 'CNV-17', 'broker': 'QA', 'status': 'sent',
                       'walletId': 'broker-wallet', 'crmConversionId': crm.id,
                       'sources': [{'dealId': deal_id, 'rub': 13200, 'usdt': 149}],
                       'txs': [{'hash': wrong_hash, 'net': 'TRC20', 'status': 'confirmed',
                                'to': TO, 'amount': 149, 'ledgerUseId': use.id}]}],
        })
        user_id = user.id
        db.commit()

    monkeypatch.setattr(appmod, 'verify_transfer', lambda *args, **kwargs: dict(
        status='confirmed', verifiedAmount=200, timestampMs=1700000000000,
        verifiedAt='2026-11-25T12:00:00Z', **{'from': FROM, 'to': TO}))
    client = appmod.app.test_client()
    with client.session_transaction() as session:
        session['user_id'] = user_id

    pending_candidates = []
    page_errors = []

    def route_requests(route):
        req = route.request
        url = urlsplit(req.url)
        if url.hostname != 'calccrm.test':
            route.abort()
        elif url.path == '/api/stand/incoming/candidates':
            pending_candidates.append(route)
        elif url.path.startswith('/api/') and url.path not in {
            '/api/auth/me', '/api/stand/state', '/api/payin-txs',
            '/api/stand/incoming/check', '/api/stand/incoming/unlink',
        }:
            route.fulfill(json={'success': False})
        else:
            response = client.open(url.path + ('?' + url.query if url.query else ''),
                                   method=req.method, data=req.post_data_buffer,
                                   content_type=req.headers.get('content-type'))
            route.fulfill(status=response.status_code, content_type=response.content_type,
                          body=response.data)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=pytestconfig.getoption('--chromium-executable'))
        context = browser.new_context(viewport={'width': 1300, 'height': 1000})
        context.route('**/*', route_requests)
        page = context.new_page()
        page.set_default_timeout(8000)
        page.on('pageerror', lambda error: page_errors.append(str(error)))
        page.goto(f'http://calccrm.test/tasks?deal={deal_id}')
        if role == 'admin':
            page.wait_for_function('id => S.open === id', arg=deal_id)
            page.evaluate("id => {setRole('operator'); openTask(id);}", deal_id)
        wrong_row = page.locator('.hashbox .hrow').filter(has_text=wrong_hash)
        remove = wrong_row.locator('button')
        expect(remove).to_be_visible()
        page.locator('#w2').fill(preview_hash)
        page.get_by_role('button', name='Проверить', exact=True).click()
        expect(page.locator('#incoming_share')).to_be_visible()

        # Complete a slow background request during the click.
        remove.scroll_into_view_if_needed()
        point = remove.bounding_box()
        page.mouse.move(point['x'] + point['width'] / 2, point['y'] + point['height'] / 2)
        page.mouse.down()
        with page.expect_response(lambda r: '/api/stand/incoming/candidates?' in r.url):
            pending_candidates.pop(0).fulfill(json={'success': True, 'txs': [], 'complete': True})
        page.wait_for_function("() => S.incomingLoadState?.status === 'ready'")
        page.mouse.up()
        reason = page.get_by_role('textbox', name='Причина отвязки')
        expect(reason).to_be_visible()
        reason.fill(reason_text)
        with page.expect_response(lambda r: r.url.endswith('/api/stand/incoming/unlink')) as response:
            page.get_by_role('button', name='Отвязать', exact=True).click()
        assert response.value.ok, response.value.json()
        expect(wrong_row).to_have_count(0)
        expect(page.locator('#incoming_share')).to_have_count(0)
        expect(page.locator('#w2')).to_have_value('')
        expect(page.get_by_text('Приход отвязан', exact=True)).to_be_visible()
        assert not page_errors, page_errors
        browser.close()

    with appmod.get_session() as db:
        ledger = db.query(appmod.PayinTx).filter_by(tx_hash=wrong_hash).one()
        assert ledger.amount_usdt == ledger.free_usdt() == 149
        board = json.loads(appmod._stand_row(db).data)
        assert board['convs'][0]['status'] == 'sent' and board['convs'][0]['txs'] == []
        assert board['deals'][0]['step'] == 's18w'
        log_entry = board['deals'][0]['log'][-1]
        assert reason_text in log_entry['text']
        assert (log_entry['role'], log_entry['by']) == (role, user_id)
