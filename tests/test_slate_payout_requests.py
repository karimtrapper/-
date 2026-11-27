"""Protect payout cards against hard-coded light surfaces in the Slate console."""
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import expect

import app as A
from tests.helpers.slate_contrast import TEXT_CONTRAST_FAILURES
from tests.test_browser_crm import chromium, crm_server, stand_ui  # noqa: F401


@pytest.mark.browser
def test_populated_payout_requests_follow_slate_colors(stand_ui, monkeypatch):
    page, errors = stand_ui
    monkeypatch.setattr(A, 'STAND_MODE', False)
    monkeypatch.setattr(A, 'TASKS_ENABLED', True)
    requests = [
        dict(id=index, status=status, payout_method=method, amount_usdt=125.50,
             thb_amount=4300, client_rate=34, bitazza_rate=34.2, bank_name='QA Bank',
             account_name='QA Account', account_number='123456789000',
             referrer_name='QA Referrer', referrer_code='QA', contact_method='telegram',
             contact_value='@qa', wallet='T' + 'A' * 33, notes='QA note',
             created_at='2026-11-27T10:00:00',
             has_receipt=method == 'thb' and status == 'paid',
             tx_hash='a' * 64 if method == 'usdt' and status == 'paid' else None)
        for index, (method, status) in enumerate(
            ((method, status) for method in ('thb', 'usdt')
             for status in ('new', 'in_progress', 'paid', 'cancelled')), 1)
    ]

    def serve_payouts(route):
        assert route.request.method == 'GET'
        status = parse_qs(urlsplit(route.request.url).query).get('status', [''])[0]
        route.fulfill(json={'success': True, 'requests': [
            row for row in requests if not status or row['status'] == status
        ]})

    page.route('**/api/payout-requests*', serve_payouts)
    origin = page.evaluate('location.origin')
    page.goto(origin + '/crm?section=payoutRequests')
    expect(page.locator('html')).to_have_class('slate-console')
    section = page.locator('#payoutRequests')
    cards = section.locator('.payout-request-card')
    expect(cards).to_have_count(8)

    text = section.locator(''' .payout-request-name, .payout-request-total, .payout-request-meta,
        .payout-request-status, .payout-request-thb, .payout-request-reference, .payout-request-receipt,
        .payout-request-details strong, .payout-request-paid-entry input, .payout-request-actions button,
        .payout-filter-btn''')
    for width in (1440, 390):
        page.set_viewport_size({'width': width, 'height': 900})
        for preset in ('slate', 'tangerine'):
            for mode in ('light', 'dark'):
                page.evaluate('([preset, mode]) => Object.assign(document.documentElement.dataset, {preset, mode})',
                              [preset, mode])
                expect(cards.first).to_be_visible()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                failures = text.evaluate_all(TEXT_CONTRAST_FAILURES)
                assert not failures, (width, preset, mode, failures)
                assert cards.first.evaluate(
                    '(el) => getComputedStyle(el).backgroundColor !== "rgb(255, 255, 255)"'
                )
    expect(section.get_by_text('Чек отправлен')).to_be_visible()
    expect(section.locator('.payout-request-tx')).to_have_text('a' * 64)
    expect(section.get_by_label('Чек выплаты').first).to_be_visible()
    tx_input = section.get_by_label('Хеш транзакции TRC-20 для выплаты').first
    page.keyboard.press('Tab')
    tx_input.focus()
    assert tx_input.evaluate('el => el.matches(":focus-visible") && getComputedStyle(el).outlineWidth === "2px"')
    selected = section.locator('.payout-filter-btn[data-status="paid"]')
    if section.locator('.crm-mobile-filter-toggle').is_visible():
        section.locator('.crm-mobile-filter-toggle').click()
    selected.click()
    expect(selected).to_have_attribute('aria-pressed', 'true')
    expect(cards).to_have_count(2)
    expect(section.locator('.payout-request-actions')).to_have_count(0)
    assert not errors
