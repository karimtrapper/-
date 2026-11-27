"""Exercise the analysis form with synthetic API responses in the Slate console."""
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

import app as A
from tests.helpers.slate_contrast import TEXT_CONTRAST_FAILURES
from tests.test_browser_crm import chromium, crm_server, stand_ui  # noqa: F401


@pytest.mark.browser
def test_bitrix_analysis_summary_and_form_use_slate_colors(stand_ui, monkeypatch):
    page, errors = stand_ui
    monkeypatch.setattr(A, 'STAND_MODE', False)
    monkeypatch.setattr(A, 'TASKS_ENABLED', True)
    verdict = 'WON'
    unexpected = []

    def serve_bitrix(route):
        path = urlsplit(route.request.url).path
        if route.request.method == 'GET' and path == '/api/bitrix/active-deals':
            return route.fulfill(json={'success': True, 'deals': [dict(
                ID=7, TITLE='Синтетическая сделка', STAGE_ID='NEW', DATE_CREATE='2026-11-27'
            )]})
        if route.request.method == 'GET' and path == '/api/bitrix/deals/7/analyze':
            if verdict == 'ERROR':
                return route.fulfill(json={'success': False, 'error': 'Синтетическая ошибка'})
            return route.fulfill(json={
                'success': True,
                'deal': {'id': 7, 'client_name': 'QA Client'},
                'analysis': {'verdict': verdict, 'confidence': 'medium', 'summary': 'Проверить получение средств.',
                             'messages_count': 6, 'prev_deal_id': 4, 'prev_deal_stage': 'LOSE',
                             'prev_deal_closedate': '2026-11-01', 'prev_deal_summary': 'Прошлый отказ',
                             'total_closed_deals': 1},
                'deal_payload': {'payin_method': 'sber_wl', 'payin_amount_rub': 10000,
                                 'payin_amount_usdt': 110, 'payout_amount_thb': 3400, 'payout_method': 'transfer'},
            })
        unexpected.append(path)
        return route.abort()

    page.route('**/api/bitrix/**', serve_bitrix)
    origin = page.evaluate('location.origin')
    page.goto(origin + '/crm?section=closing')
    expect(page.locator('html')).to_have_class('slate-console')
    section = page.locator('#closing')
    analyze = section.get_by_role('button', name='Разобрать')
    card = section.locator('#bitrixAnalysisCard')
    summary = card.locator('.bitrix-analysis-summary')
    visible_text = card.locator(''' .bitrix-analysis-verdict, .bitrix-analysis-text,
        .bitrix-analysis-meta, .alert-warning, .alert-warning b, .form-label,
        .form-control, .btn''')

    for verdict in ('WON', 'LOSE', 'UNKNOWN'):
        analyze.click()
        expect(summary.locator('.bitrix-analysis-verdict')).to_have_attribute('data-verdict', verdict)
        expect(card.locator('#bitrixAnalysisTitle')).to_have_text('Сделка #7 · QA Client')
        expect(summary).to_contain_text('Проверить получение средств.')
        expect(summary).to_contain_text('Прошлая сделка #4')
        expect(card.locator('#bxPayoutThb')).to_have_value('3400')
        for width in (1440, 390):
            page.set_viewport_size({'width': width, 'height': 900})
            for preset in ('slate', 'tangerine'):
                for mode in ('light', 'dark'):
                    page.evaluate('([preset, mode]) => Object.assign(document.documentElement.dataset, {preset, mode})',
                                  [preset, mode])
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    failures = visible_text.evaluate_all(TEXT_CONTRAST_FAILURES)
                    assert not failures, (verdict, width, preset, mode, failures)
                    assert summary.evaluate('el => getComputedStyle(el).backgroundColor !== "rgb(248, 250, 252)"')

    verdict = 'ERROR'
    analyze.click()
    error = card.locator('.bitrix-analysis-error')
    expect(error).to_have_text('Синтетическая ошибка')
    assert not error.evaluate_all(TEXT_CONTRAST_FAILURES)
    assert not unexpected
    assert not errors
