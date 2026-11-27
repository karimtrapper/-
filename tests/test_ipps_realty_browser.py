"""Headless HTTP regression for the manual IPPS draft and linked CRM editor."""
from urllib.parse import urlsplit
import json

import pytest
from playwright.sync_api import expect

import app as m
from tests.payin_registry import ensure_payin_wallet
from tests.test_browser_crm import choose, chromium, crm_server  # noqa: F401
from tests.test_ipps_realty import COST, OPENING_THB, THB, _accounts, _network_payin


pytestmark = pytest.mark.browser


@pytest.mark.parametrize('width', [1440, 390])
def test_manual_ipps_form_save_reload_close_and_open_crm(width, chromium, crm_server, monkeypatch):
    monkeypatch.setattr(m, 'STAND_MODE', True)
    monkeypatch.setattr(m, 'verify_transfer', _network_payin)
    monkeypatch.setattr(m, '_stand_deliver_notes', lambda: None)
    monkeypatch.setattr(m, '_tronscan_fetch_incoming', lambda *a, **k: ([], [], []))
    ensure_payin_wallet()
    with m.get_session() as db:
        manager = m.AdminUser(username='ipps-browser', display_name='IPPS QA',
                              role='manager', password_hash='unused')
        db.add(manager)
        row = m._stand_row(db)
        data = json.loads(row.data)
        data['bal'] = {'ipps': 50000.52, 'cash': 200, 'scb': 500, 'usdt': 900}
        row.data = json.dumps(data)
        card_id, _ = _accounts(db)
        db.commit()
        manager_id = manager.id

    base, cookie = crm_server
    context = chromium.new_context(viewport={'width': width, 'height': 900})
    context.add_cookies([{'name': 'session', 'value': cookie, 'url': base}])
    context.route('**/*', lambda route: route.continue_()
                  if urlsplit(route.request.url).hostname == '127.0.0.1' else route.abort())
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(error.stack or str(error)))
    page.on('dialog', lambda dialog: dialog.accept())
    try:
        with page.expect_response(lambda response: response.url.endswith('/api/stand/state')):
            page.goto(base + '/tasks')
        page.wait_for_load_state('networkidle')
        page.evaluate("() => setTab('deals')")
        page.get_by_role('button', name='+ Создать сделку', exact=True).click()
        shadow = page.locator('#crmDraftHost')
        kind = shadow.locator('#dealKindSelect')
        expect(kind.locator('option[value="ipps_realty"]')).to_have_text('Недвижимость лизхолд через ИППС')
        expect(kind.locator('option[value="mf_realty"]')).to_have_text('Недвижимость через MF Corp')
        expect(shadow.locator('#managerSelect option').filter(has_text='IPPS QA')).to_have_count(1)
        shadow.locator('#managerSelect').select_option(f'user:{manager_id}', force=True)
        choose(shadow, '#dealProductSelect', 'Недвижимость лизхолд')
        choose(shadow, '#leaseholdPayoutRoute', 'ИППС')
        expect(shadow.locator('#ippsCardSelect')).to_have_value(str(card_id))
        expect(shadow.locator('#ippsCardSelect option:checked')).to_contain_text('IPPS счет компании')
        expect(shadow.locator('#ippsCostUsdt')).to_have_attribute('readonly', '')
        expect(shadow.locator('#payoutSectionStd')).to_be_hidden()
        expect(shadow.locator('#mfDealSection')).to_be_hidden()
        shadow.locator('#clientSearchInput').fill(f'QA IPPS {width}')
        shadow.locator('#payinMethod').select_option('crypto_direct', force=True)
        shadow.locator('#ippsPurpose').fill('QA invoice')
        shadow.locator('#ippsPayoutThb').fill(str(THB))
        expect(shadow.locator('#ippsCostUsdt')).to_have_value(f'{COST:.2f}')
        shadow.locator('#payinManualHash').fill('a' * 64)
        with page.expect_response(lambda response: '/manual-close/verify-hash' in response.url) as lookup:
            shadow.get_by_role('button', name='Добавить хеш').click()
        assert lookup.value.ok, lookup.value.json()
        expect(shadow.locator('#ippsProfitSummary')).to_have_text('Валовая прибыль 100.00 USDT')
        inquiry_type = page.locator('#crmDraftInquiryType')
        inquiry_type.select_option(label='Клиент')
        expect(inquiry_type).to_have_value('client')
        with page.expect_response(lambda response: response.url.endswith('/api/stand/state')
                                  and response.request.method == 'PUT') as save:
            page.locator('.edit-page button[onclick^="editSave("]').first.click()
        assert save.value.ok, save.value.json()
        saved = save.value.json()['data']['deals'][0]
        assert saved['payout']['thb'] == THB and saved['payout']['bankCardId'] == card_id
        with m.get_session() as db:
            assert db.get(m.BankCard, card_id).balance_thb == OPENING_THB
            assert not db.query(m.CardAllocation).first()
        assert save.value.json()['data']['bal']['ipps'] == 50000.52

        page.goto(f'{base}/tasks?deal={saved["id"]}')
        page.get_by_role('button', name='Редактировать', exact=True).click()
        expect(shadow.locator('#dealKindSelect')).to_have_value('ipps_realty')
        expect(shadow.locator('#ippsPayoutThb')).to_have_value(str(THB))
        expect(shadow.locator('#ippsCostUsdt')).to_have_value(f'{COST:.2f}')
        page.get_by_role('button', name='Отмена', exact=True).first.click()
        with page.expect_response(lambda response: response.url.endswith('/crm-close')) as close:
            page.get_by_role('button', name='Сохранить в CRM', exact=True).click()
        assert close.value.status == 201, close.value.json()
        result = close.value.json()
        assert result['deal']['profit_usdt'] == 100
        assert result['data']['bal']['ipps'] == 50000.52
        assert result['deal']['bank_card_id'] == card_id
        with m.get_session() as db:
            alloc = db.query(m.CardAllocation).filter_by(deal_id=result['deal']['id']).one()
            assert alloc.card_id == card_id and alloc.cost_usdt == COST
            assert db.get(m.BankCard, card_id).balance_thb == THB

        page.goto(f'{base}/crm')
        page.evaluate('id => openDealEditor(id)', result['deal']['id'])
        expect(page.locator('#ippsDealSection')).to_be_visible()
        expect(page.locator('#dealKindSelect')).to_have_value('ipps_realty')
        expect(page.locator('#ippsCostUsdt')).to_have_value(f'{COST:.2f}')
        expect(page.locator('#ippsCostUsdt')).to_have_attribute('readonly', '')
        assert not errors, errors
    finally:
        context.close()
