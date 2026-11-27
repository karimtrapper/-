"""A working manager can assign agents without access to referral finances."""
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

import app as A
from tests.test_browser_crm import choose, chromium, crm_server  # noqa: F401


@pytest.mark.browser
@pytest.mark.parametrize('working_tasks', [True, False], ids=['working-manager', 'legacy-admin'])
def test_crm_agent_directory_populates_both_deal_forms(chromium, crm_server, monkeypatch, working_tasks):
    monkeypatch.setattr(A, 'TASKS_ENABLED', working_tasks)
    monkeypatch.setattr(A, 'STAND_MODE', False)
    monkeypatch.setitem(A.app.config, 'SESSION_COOKIE_SECURE', False)
    with A.get_session() as db:
        db.add(A.AdminUser(username='qa_agent_manager', display_name='QA Agent Manager',
                           role='manager', password_hash=A.AdminUser.hash_password('qa-password')))
        agent = A.Referrer(name='QA & Partner', code='QA-ACTIVE', token='synthetic-active-token',
                           telegram='qa_private_contact', notes='synthetic private notes',
                           default_percent=13, comp_model='markup', markup_percent=2.75)
        db.add_all([agent,
                    A.Referrer(name='QA Disabled', code='QA-OFF', token='synthetic-disabled-token', active=False),
                    A.Referrer(name='QA Test', code='QA-TEST', token='synthetic-test-token', is_test=True)])
        db.commit()
        agent_id = str(agent.id)

    base, admin_cookie = crm_server
    with chromium.new_context(viewport={'width': 1440, 'height': 900}) as context:
        if working_tasks:
            login = context.request.post(base + '/api/auth/login',
                                         data={'username': 'qa_agent_manager', 'password': 'qa-password'})
            assert login.ok
            assert context.request.get(base + '/api/auth/me').json()['user']['role'] == 'manager'
            assert context.request.get(base + '/api/referrers').status == 403
            assert context.request.get(base + f'/api/referrers/{agent_id}/unpaid').status == 403
            catalog = context.request.get(base + '/api/stand/referrers')
            assert catalog.ok and catalog.headers['cache-control'] == 'private, no-store'
            assert [str(row['id']) for row in catalog.json()['referrers']] == [agent_id]
            assert set(catalog.json()['referrers'][0]) == {
                'id', 'name', 'code', 'active', 'is_test', 'default_percent', 'comp_model',
                'markup_percent', 'payout_currency', 'lang',
            }
            with chromium.new_context() as anonymous:
                assert anonymous.request.get(base + '/api/stand/referrers').status == 401
        else:
            context.add_cookies([{'name': 'session', 'value': admin_cookie, 'url': base}])
            assert context.request.get(base + '/api/stand/referrers').status == 404

        context.route('**/*', lambda route: route.continue_()
                      if urlsplit(route.request.url).hostname == '127.0.0.1' else route.abort())
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.set_default_timeout(7000)
        page.goto(base + '/crm?section=deals')
        if working_tasks:
            expect(page.locator('html')).to_have_class('slate-console')
            page.locator('.slate-link[data-slate-route="deals"]').click()
        else:
            page.locator('.nav-tab[data-section="deals"]').click()
        catalog_requests = []
        page.route('**/api/stand/referrers', lambda route: catalog_requests.append(route))
        page.locator('#deals .nav-create-btn').click()
        product = '#dealProductSelect'
        choose(page, product, 'Кастомная — нестандартные валюты')
        custom = page.locator('#agentsBlockCustom')
        page.locator('#customDealSection').get_by_role('button', name='Добавить агента').click()
        custom_agent = custom.locator('select[onchange*="referrer_id"]')
        expect(custom_agent.locator('option')).to_have_count(1)

        percent = custom.locator('input[type="number"]')
        percent.fill('9')
        assert len(catalog_requests) == 1
        catalog_requests[0].continue_()
        expect(custom_agent.locator(f'option[value="{agent_id}"]')).to_have_text('QA & Partner')
        expect(custom_agent.locator('option').filter(has_text='QA Disabled')).to_have_count(0)
        if working_tasks:
            expect(custom_agent.locator('option').filter(has_text='QA Test')).to_have_count(0)
        expect(percent).to_be_focused()
        expect(percent).to_have_value('9')
        choose(page, '#agentsBlockCustom select[data-agent-directory]', 'QA & Partner')
        expect(custom.locator('select[onchange*="comp_model"]')).to_have_value('markup')
        expect(custom.locator('input[type="number"]')).to_have_value('2.75')
        custom.locator('input[type="number"]').fill('7')
        page.unroute('**/api/stand/referrers')
        page.evaluate('loadReferrerDropdowns()')
        expect(custom_agent).to_have_value(agent_id)
        expect(custom.locator('input[type="number"]')).to_have_value('7')

        choose(page, product, 'Обычная (обмен)')
        page.locator('#standardDealSection').get_by_role('button', name='Добавить агента').click()
        standard = page.locator('#agentsBlockStd')
        standard_agent = standard.locator('select[onchange*="referrer_id"]')
        choose(page, '#agentsBlockStd select[data-agent-directory]', 'QA & Partner')
        expect(standard_agent).to_have_value(agent_id)
        expect(standard.locator('select[onchange*="comp_model"]')).to_have_value('markup')
        expect(standard.locator('input[type="number"]')).to_have_value('2.75')
        assert not errors
