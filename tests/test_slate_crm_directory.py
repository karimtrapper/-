"""Contrast and responsive layout for populated staff-side CRM lists."""
from datetime import datetime

import pytest
from playwright.sync_api import expect

import app as A
from tests.helpers.slate_contrast import TEXT_CONTRAST_FAILURES
from tests.test_browser_crm import chromium, crm_server, stand_ui  # noqa: F401


@pytest.mark.browser
def test_crm_directory_and_reconciliation(stand_ui, monkeypatch):
    page, errors = stand_ui
    monkeypatch.setattr(A, 'STAND_MODE', False)
    monkeypatch.setattr(A, 'TASKS_ENABLED', True)
    with A.get_session() as db:
        db.add_all([
            A.KycRequest(token='synthetic-pending', client_name='QA Waiting', status='pending'),
            A.KycRequest(token='synthetic-approved', client_name='QA Approved', status='approved',
                         reviewed_at=datetime.now(), files_purged_at=datetime.now()),
            A.Partner(name='QA Partner', token='synthetic-partner', active=False),
            A.Referrer(name='QA Referrer', code='QA001', token='synthetic-referrer', default_percent=10),
        ])
        db.commit()

    base = page.evaluate('location.origin')
    page.goto(base + '/crm')
    expect(page.locator('html')).to_have_class('slate-console')
    for section, ready, text in [
        ('verification', '#verificationSummary .stat-value', '.stat-value, .crm-secondary-text, #webhookStatus span'),
        ('kyc', '#kycVerifiedList .crm-directory-row', '.crm-directory-row strong, .crm-secondary-text, [data-tone], .crm-directory-actions button'),
        ('partners', '#partnersList .crm-directory-row', '.crm-directory-row strong, .crm-secondary-text, .crm-directory-actions button, input[readonly]'),
        ('referrers', '#referrersList .crm-directory-row', '.referrer-name, .crm-secondary-text, [data-tone], input[readonly]'),
    ]:
        page.locator('[data-slate-search]').click()
        page.locator(f'.slate-results [data-slate-route="{section}"]').click()
        expect(page.locator(ready).first).to_be_visible()
        if section == 'referrers':
            page.locator('.referrer-actions summary').first.click()
            expect(page.locator('.referrer-actions-menu').first.get_by_role('button', name='Сделки')).to_be_visible()
        for width in (390, 1440):
            page.set_viewport_size({'width': width, 'height': 900})
            for preset in ('slate', 'tangerine'):
                for mode in ('light', 'dark'):
                    page.evaluate('([preset, mode]) => Object.assign(document.documentElement.dataset, {preset, mode})',
                                  [preset, mode])
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    assert not page.locator(f'#{section}').locator(text).evaluate_all(TEXT_CONTRAST_FAILURES), (
                        section, width, preset, mode)
                    assert page.locator(f'#{section}').evaluate('el => el.scrollWidth <= el.clientWidth + 1')
    page.locator('.referrer-actions-menu').first.get_by_role('button', name='Сделки').click()
    referrer_modal = page.locator('#dealModal')
    expect(referrer_modal).to_be_visible()
    expect(referrer_modal.locator('.ref-card-summary')).to_contain_text('Комиссия всего')
    referrer_modal.get_by_role('button', name='Заявки (0)').click()
    expect(referrer_modal.get_by_role('button', name='Заявки (0)')).to_have_attribute('aria-pressed', 'true')
    assert not referrer_modal.locator('.ref-card-summary span, .ref-card-summary b, .ref-card-tab').evaluate_all(
        TEXT_CONTRAST_FAILURES)
    referrer_modal.get_by_role('button', name='Закрыть').click()

    page.locator('[data-slate-search]').click()
    page.locator('.slate-results [data-slate-route="kyc"]').click()
    page.locator('#kycVerifiedList').get_by_role('button', name='Документы').click()
    reviewed = page.locator('#kycReviewModal')
    expect(reviewed.locator('.crm-tone-block')).to_contain_text('Верификация одобрена')
    assert not reviewed.locator('.crm-tone-block, .kyc-missing-photo, .kyc-review-warning span').evaluate_all(
        TEXT_CONTRAST_FAILURES)
    reviewed.get_by_role('button', name='Закрыть').click()
    assert not errors


@pytest.mark.browser
def test_card_history_contrast_and_dialog_keyboard_close(stand_ui, monkeypatch):
    page, errors = stand_ui
    monkeypatch.setattr(A, 'STAND_MODE', False)
    monkeypatch.setattr(A, 'TASKS_ENABLED', True)
    with A.get_session() as db:
        db.add(A.BankCard(bank_name='QA Bank', card_name=A.IPPS_CARD_NAME, balance_thb=3000,
                          topups=[A.CardTopup(amount_thb=3000, cost_usdt=100, purchase_rate=30,
                                              source_type='separate', notes='QA Synthetic purchase')]))
        db.commit()
    page.set_viewport_size({'width': 390, 'height': 900})
    page.goto(page.evaluate('location.origin') + '/crm?section=balance')
    expect(page.locator('html')).to_have_class('slate-console')
    page.get_by_role('button', name='Карты (THB)').click()
    page.get_by_role('button', name='Добавить карту').click()
    modal = page.locator('#addCardModal')
    close = modal.get_by_role('button', name='Закрыть')
    expect(close).to_be_visible()
    close.focus()
    close.press('Enter')
    expect(modal).to_be_hidden()
    page.get_by_role('button', name='ИППС (THB)').click()
    page.locator('#subtabIpps').get_by_role('button', name='История', exact=True).click()
    history = page.locator('#historyModal')
    expect(history.locator('.history-summary')).to_contain_text('QA Bank')
    expect(history.locator('.history-record')).to_contain_text('QA Synthetic purchase')
    for width in (390, 1440):
        page.set_viewport_size({'width': width, 'height': 900})
        for preset in ('slate', 'tangerine'):
            for mode in ('light', 'dark'):
                page.evaluate('([preset, mode]) => Object.assign(document.documentElement.dataset, {preset, mode})',
                              [preset, mode])
                assert not history.locator('.history-summary, .history-record small, [data-tone]').evaluate_all(
                    TEXT_CONTRAST_FAILURES)
                assert history.locator('.modal-content').evaluate('el => el.scrollWidth <= el.clientWidth + 1')
    assert not errors
