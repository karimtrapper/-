"""Check the financial panels of a rendered synthetic CRM deal."""
import re

import pytest
from playwright.sync_api import expect

import app as A
from tests.helpers.slate_contrast import TEXT_CONTRAST_FAILURES
from tests.test_browser_crm import chromium, crm_server, stand_ui  # noqa: F401


@pytest.mark.browser
def test_deal_transfers_and_partners_follow_slate_colors(stand_ui, monkeypatch):
    page, errors = stand_ui
    monkeypatch.setattr(A, 'STAND_MODE', False)
    monkeypatch.setattr(A, 'TASKS_ENABLED', True)
    address = 'T' + 'A' * 33
    proof = {'hash': 'a' * 64, 'amount_usdt': 125.50, 'network': 'trc20',
             'to_address': address, 'date': '2026-11-27'}
    partner = {'name': 'QA Partner', 'percent': 12.5, 'payout_usdt': 5,
               'paid': True, 'comp_model': 'revshare'}
    shared = {'client_name': 'QA Client', 'status': 'completed', 'payin_method': 'crypto_direct',
              'payin_amount_usdt': 250, 'payout_amount_usdt': 125.5, 'profit_usdt': 15,
              'payout_tx_hashes': [proof], 'referrer_payout_usdt': 5}
    deals = {
        101: dict(shared, id=101, deal_kind='mf_realty', invoice_amount_thb=3500, company_sent_thb=4000,
                  agents=[dict(partner, tier=1), dict(partner, name='QA Fixed', tier=2, paid=False,
                                                    comp_model='fixed', fixed_usdt=3)]),
        102: dict(shared, id=102, deal_kind='mf_freehold', referrer_name='QA Legacy Partner',
                  referrer_comp_model='markup', referrer_markup_percent=2, referrer_paid=True),
        103: dict(shared, id=103, deal_kind='ipps_realty', payout_amount_thb=4000,
                  referrer_name='QA Pending Partner', referrer_paid=False),
    }

    def serve_deal(route):
        assert route.request.method == 'GET'
        route.fulfill(json={'success': True, 'deal': deals[int(route.request.url.rsplit('/', 1)[1])]})

    page.route(re.compile(r'/api/deals/10[123]$'), serve_deal)
    page.add_init_script('''Object.defineProperty(navigator.clipboard, 'writeText', {
        value: async value => { window.copiedProof = value; }
    });''')
    origin = page.evaluate('location.origin')
    for deal_id in deals:
        page.goto(f'{origin}/crm?deal={deal_id}')
        expect(page.locator('html')).to_have_class('slate-console')
        dialog = page.locator('#dealModal')
        expect(dialog).to_be_visible()
        expect(dialog.locator('.deal-detail-hash')).to_have_count(1)
        expect(dialog.locator('.deal-detail-hash')).to_have_attribute('href', re.compile('a{64}'))
        expect(dialog.locator('.deal-detail-partners')).to_contain_text('Партнёр:')
        text = dialog.locator(''' .deal-detail-panel, .deal-detail-panel :is(p, strong, span, a),
            .deal-detail-proof strong, .deal-detail-hash''')
        for width in (1440, 390):
            page.set_viewport_size({'width': width, 'height': 900})
            for preset in ('slate', 'tangerine'):
                for mode in ('light', 'dark'):
                    page.evaluate('([preset, mode]) => Object.assign(document.documentElement.dataset, {preset, mode})',
                                  [preset, mode])
                    failures = text.evaluate_all(TEXT_CONTRAST_FAILURES)
                    assert not failures, (deal_id, width, preset, mode, failures)
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        if deal_id in (101, 102):
            expect(dialog.locator('.deal-detail-transfers')).to_contain_text('Итого ушло:')
            dialog.get_by_role('button', name='Скопировать адрес').click()
            assert page.evaluate('window.copiedProof') == address
        else:
            dialog.get_by_role('button', name='Скопировать хэш').click()
            assert page.evaluate('window.copiedProof') == proof['hash']
    assert not errors
