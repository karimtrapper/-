"""Authenticated, full NavShell visual gate for every CRM section at 375 and 768."""
import json
import re
from pathlib import Path

import pytest
from playwright.sync_api import expect

from tests.test_browser_crm import chromium, crm_server, stand_ui, ui  # noqa: F401: pytest fixtures


pytestmark = pytest.mark.browser
SECTIONS = [
    'deals', 'documents', 'closing', 'exchangers', 'balance', 'incomes',
    'conversions', 'reimbursements', 'transactions', 'managers', 'verification',
    'kyc', 'partners', 'referrers', 'payoutRequests', 'admins',
]
EVIDENCE = Path('/tmp/calccrm-mobile-crm-gate')
TABLE_SAMPLES = {
    'incomes': ('#incomesTable', ['✓', '15.10.2026', 'QA Payer', '100 000 ₽', '—',
                                'Ожидает', 'Сбер', 'QA', '—', '—', '—']),
    'conversions': ('#conversionsTable', ['CNV-QA', 'Сбер', '15.10.2026', 'QA Broker',
                                        'QA Request', '100 000 ₽', '100', '1 000 USDT',
                                        '0', 'Ожидает']),
    'exchangers': ('#rx-deals-body', ['WL-QA', '15.10.2026', 'QA Merchant', '100 000 ₽',
                                   '1 000 USDT', '1 100 USDT', '$100', '—', 'Оплачено']),
}


def layout(page, section):
    return page.evaluate('''section => {
      const root = document.documentElement;
      const body = document.body;
      const active = document.getElementById(section);
      const tables = [...active.querySelectorAll('table.crm-mobile-table')];
      const visible = node => node.getClientRects().length > 0;
      const offenders = [...active.querySelectorAll('*')].filter(node => {
        if (!visible(node) || getComputedStyle(node).position === 'fixed') return false;
        const rect = node.getBoundingClientRect();
        return rect.right > innerWidth + 1 || rect.left < -1;
      }).slice(0, 8).map(node => ({tag: node.tagName, id: node.id,
        cls: String(node.className).slice(0, 70),
        left: Math.round(node.getBoundingClientRect().left),
        right: Math.round(node.getBoundingClientRect().right)}));
      const internalOverflow = [...active.querySelectorAll('*')].filter(node =>
        visible(node) && node.clientWidth > 0 && node.scrollWidth > node.clientWidth + 2 &&
        !['INPUT', 'TEXTAREA', 'SELECT', 'CANVAS', 'SVG'].includes(node.tagName)
      ).slice(0, 10).map(node => ({tag: node.tagName, id: node.id,
        cls: String(node.className).slice(0, 70),
        parent: String(node.parentElement?.className || '').slice(0, 70),
        snippet: node.outerHTML.slice(0, 180),
        client: node.clientWidth, scroll: node.scrollWidth}));
      return {width: innerWidth, html: root.scrollWidth, body: body.scrollWidth,
        sectionWidth: active.scrollWidth, sectionClient: active.clientWidth,
        navCount: document.querySelectorAll('.site-shell-section-list [data-shell-section]').length,
        tableCount: tables.length,
        tableDisplays: tables.map(table => getComputedStyle(table).display),
        detailsVisible: [...active.querySelectorAll('.crm-mobile-details')].filter(visible).length,
        rows: tables.reduce((n, t) => n + t.querySelectorAll('tbody > tr[data-crm-card-ready="1"]').length, 0),
        filters: [...active.querySelectorAll('.crm-mobile-filter-panel')].map(panel => ({
          id: panel.id, visible: visible(panel), open: panel.classList.contains('is-open')})),
        primary: [...active.querySelectorAll('.btn-primary')].filter(node => visible(node) &&
          getComputedStyle(node).backgroundColor === 'rgb(194, 65, 12)').length,
        offenders, internalOverflow};
    }''', section)


def test_all_mobile_crm_sections_design_gate(stand_ui):
    page, errors = stand_ui
    EVIDENCE.mkdir(mode=0o700, exist_ok=True)
    results, failures = {}, []
    for width in (375, 768):
        page.set_viewport_size({'width': width, 'height': 844})
        for section in SECTIONS:
            page.locator(f'.site-shell-section-list [data-shell-section="{section}"]').click()
            expect(page.locator(f'#{section}')).to_be_visible()
            page.wait_for_load_state('networkidle')
            page.wait_for_timeout(80)
            result = layout(page, section)
            results[f'{section}-{width}'] = result
            page.screenshot(path=str(EVIDENCE / f'{section}-{width}.png'), full_page=True)
            if result['navCount'] != 17:
                failures.append(f'{section}/{width}: nav has {result["navCount"]} links')
            if result['html'] > width + 1 or result['body'] > width + 1 or result['sectionWidth'] > result['sectionClient'] + 1:
                failures.append(f'{section}/{width}: horizontal overflow {result}')
            if width == 375:
                if any(display != 'block' for display in result['tableDisplays']):
                    failures.append(f'{section}/375: table not in card layout')
                if result['primary'] > 1:
                    failures.append(f'{section}/375: {result["primary"]} coral actions')
                if any(f['visible'] for f in result['filters']):
                    failures.append(f'{section}/375: filter open by default')
            else:
                if any(not f['visible'] for f in result['filters']):
                    failures.append(f'{section}/768: desktop filters hidden')
                if any(display != 'table' for display in result['tableDisplays']) or result['detailsVisible']:
                    failures.append(f'{section}/768: desktop table layout changed')

    page.set_viewport_size({'width': 375, 'height': 844})
    page.locator('.site-shell-section-list [data-shell-section="deals"]').click()
    expect(page.locator('#dealsTable tr')).to_have_count(1)
    details = page.locator('#dealsTable tr').get_by_role('button', name='Детали', exact=True)
    expect(details).to_be_visible()
    details.click()
    expect(page.locator('#dealModal')).to_be_visible()
    page.screenshot(path=str(EVIDENCE / 'deals-details-375.png'), full_page=True)
    page.locator('#dealModal .modal-close').click()
    filter_button = page.locator('#deals > .crm-mobile-filter-toggle')
    expect(filter_button).to_have_attribute('aria-expanded', 'false')
    filter_button.click()
    expect(filter_button).to_have_attribute('aria-expanded', 'true')
    expect(page.locator('#filterStatus')).to_be_visible()

    section_list = page.locator('.site-shell-section-list')
    section_list.evaluate('(el) => { el.scrollLeft = 0; }')
    next_arrow = page.locator('[data-shell-scroll="1"]')
    previous_arrow = page.locator('[data-shell-scroll="-1"]')
    for _ in range(20):
        if next_arrow.is_disabled():
            break
        next_arrow.click()
        page.wait_for_timeout(300)
    if not next_arrow.is_disabled():
        failures.append('375: right arrow could not reach the 17th section')
    at_end = section_list.evaluate('(el) => el.scrollLeft')
    if at_end <= 0 or previous_arrow.is_disabled():
        failures.append('375: section arrows did not advance')
    else:
        previous_arrow.click()
        page.wait_for_timeout(300)
        if section_list.evaluate('(el) => el.scrollLeft') >= at_end:
            failures.append('375: left arrow did not scroll back')
    page.locator('.site-shell-section-list [data-shell-section="analytics"]').click()
    expect(page).to_have_url(re.compile(r'/tasks\?section=analytics$'))
    for width in (375, 768):
        page.set_viewport_size({'width': width, 'height': 844})
        page.wait_for_load_state('networkidle')
        page.screenshot(path=str(EVIDENCE / f'analytics-{width}.png'), full_page=True)
        result = page.evaluate('''() => ({width: innerWidth,
          html: document.documentElement.scrollWidth, body: document.body.scrollWidth,
          navCount: document.querySelectorAll('.site-shell-section-list [data-shell-section]').length})''')
        results[f'analytics-{width}'] = result
        if result['html'] > width + 1 or result['body'] > width + 1 or result['navCount'] != 17:
            failures.append(f'analytics/{width}: {result}')

    (EVIDENCE / 'results.json').write_text(json.dumps({'results': results, 'failures': failures,
        'pageErrors': errors}, ensure_ascii=False, indent=2))
    assert not errors, errors
    assert not failures, '\n'.join(failures)


def test_populated_tables_and_subtabs_at_375(stand_ui):
    page, errors = stand_ui
    page.set_viewport_size({'width': 375, 'height': 844})
    EVIDENCE.mkdir(mode=0o700, exist_ok=True)
    failures = []
    for section, (selector, values) in TABLE_SAMPLES.items():
        page.locator(f'.site-shell-section-list [data-shell-section="{section}"]').click()
        page.wait_for_load_state('networkidle')
        page.locator(selector).evaluate('''(body, values) => {
          const row = document.createElement('tr');
          row.innerHTML = values.map(value => `<td>${value}</td>`).join('');
          body.replaceChildren(row);
        }''', values)
        row = page.locator(f'{selector} > tr')
        expect(row).to_have_attribute('data-crm-card-ready', '1')
        expect(row.locator('[data-crm-card-role="title"]')).to_be_visible()
        expect(row.locator('[data-crm-card-role="amount"]')).to_be_visible()
        expect(row.locator('[data-crm-card-role="status"]')).to_be_visible()
        details = row.get_by_role('button', name='Детали', exact=True)
        expect(details).to_be_visible()
        page.screenshot(path=str(EVIDENCE / f'{section}-populated-375.png'), full_page=True)
        details.click()
        expect(row.locator('[data-crm-card-role="extra"]').first).to_be_visible()
        result = layout(page, section)
        if result['html'] > 376 or result['body'] > 376 or result['internalOverflow']:
            failures.append(f'{section} populated: {result}')

    page.locator('.site-shell-section-list [data-shell-section="exchangers"]').click()
    for subtab, selector, values in [
        ('brokers', '#rx-brokers-body', ['#1', '15.10.2026', 'QA Broker', 'QA Wallet',
                                       'QA Hash', '1 000 USDT', '1', 'Ожидает']),
        ('requests', '#rx-requests-body', ['QA Bitrix', 'QA Merchant', '1 000 USDT',
                                         '15.10.2026', '—', 'QA Wallet', '1', 'Ожидает']),
        ('wallets', '#rx-wallets-body', ['T' + 'A' * 33, 'QA Wallet', 'TRON',
                                       '1 000 USDT', '15.10.2026', 'Активен']),
    ]:
        page.locator(f'.rx-subtab[data-rx="{subtab}"]').click()
        page.locator(selector).evaluate('''(body, values) => {
          const row = document.createElement('tr');
          row.innerHTML = values.map(value => `<td>${value}</td>`).join('');
          body.replaceChildren(row);
        }''', values)
        row = page.locator(f'{selector} > tr')
        expect(row).to_have_attribute('data-crm-card-ready', '1')
        expect(row.locator('[data-crm-card-role="title"]')).to_be_visible()
        expect(row.locator('[data-crm-card-role="amount"]')).to_be_visible()
        expect(row.locator('[data-crm-card-role="status"]')).to_be_visible()
        page.screenshot(path=str(EVIDENCE / f'exchangers-{subtab}-375.png'), full_page=True)
        result = layout(page, 'exchangers')
        if result['html'] > 376 or result['body'] > 376 or result['internalOverflow']:
            failures.append(f'exchangers/{subtab}: {result}')

    page.locator('.site-shell-section-list [data-shell-section="balance"]').click()
    for subtab, button in [('cash', '#btnSubCash'), ('cards', '#btnSubCards')]:
        page.locator(button).click()
        page.wait_for_load_state('networkidle')
        page.screenshot(path=str(EVIDENCE / f'balance-{subtab}-375.png'), full_page=True)
        result = layout(page, 'balance')
        if result['html'] > 376 or result['body'] > 376 or result['internalOverflow']:
            failures.append(f'balance/{subtab}: {result}')
    (EVIDENCE / 'populated-results.json').write_text(json.dumps({
        'failures': failures, 'pageErrors': errors}, ensure_ascii=False, indent=2))
    assert not errors, errors
    assert not failures, '\n'.join(failures)


def test_dashboard_panel_additional_mobile_screen(stand_ui):
    page, errors = stand_ui
    EVIDENCE.mkdir(mode=0o700, exist_ok=True)
    origin = page.evaluate('location.origin')
    results = {}
    for width in (375, 768):
        page.set_viewport_size({'width': width, 'height': 844})
        page.goto(origin + '/panel')
        expect(page.locator('#dashboard')).to_be_visible()
        page.wait_for_load_state('networkidle')
        results[str(width)] = layout(page, 'dashboard')
        page.screenshot(path=str(EVIDENCE / f'dashboard-{width}.png'), full_page=True)
    (EVIDENCE / 'dashboard-results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2))
    assert not errors, errors
    assert results['375']['html'] <= 376 and results['375']['body'] <= 376, results['375']
    assert results['375']['sectionWidth'] <= results['375']['sectionClient'] + 1, results['375']
    assert not results['375']['internalOverflow'], results['375']['internalOverflow']
    assert all(display == 'block' for display in results['375']['tableDisplays']), results['375']
    assert results['768']['html'] <= 769 and results['768']['body'] <= 769, results['768']
    assert all(display == 'table' for display in results['768']['tableDisplays']), results['768']


def test_production_navigation_unchanged(ui):
    page, errors, _, _ = ui
    page.set_viewport_size({'width': 375, 'height': 844})
    page.evaluate("showSection('deals')")
    expect(page.locator('#deals > .crm-mobile-filter-toggle')).to_be_hidden()
    expect(page.locator('#deals .crm-mobile-details').first).to_be_hidden()
    page.evaluate("showSection('documents')")
    expect(page.locator('#documents .docs-mobile-label').first).to_be_hidden()
    assert not errors, errors


@pytest.mark.parametrize('width', [320, 414])
def test_mobile_edge_widths_no_horizontal_overflow(stand_ui, width):
    page, errors = stand_ui
    page.set_viewport_size({'width': width, 'height': 844})
    failures = []
    for section in SECTIONS:
        page.locator(f'.site-shell-section-list [data-shell-section="{section}"]').click()
        page.wait_for_load_state('networkidle')
        result = layout(page, section)
        if (result['html'] > width + 1 or result['body'] > width + 1 or
                result['sectionWidth'] > result['sectionClient'] + 1 or
                result['internalOverflow']):
            failures.append((section, result))
    origin = page.evaluate('location.origin')
    page.goto(origin + '/panel')
    page.wait_for_load_state('networkidle')
    result = layout(page, 'dashboard')
    if (result['html'] > width + 1 or result['body'] > width + 1 or
            result['sectionWidth'] > result['sectionClient'] + 1 or
            result['internalOverflow']):
        failures.append(('dashboard', result))
    EVIDENCE.mkdir(mode=0o700, exist_ok=True)
    (EVIDENCE / f'edge-{width}.json').write_text(json.dumps(failures, ensure_ascii=False, indent=2))
    assert not errors, errors
    assert not failures, failures
