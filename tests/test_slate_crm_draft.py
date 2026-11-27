"""Exercise the working Tasks entry into the shared CRM editor."""
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

import app as A
from tests.test_browser_crm import chromium, crm_server  # noqa: F401


@pytest.mark.browser
def test_enter_full_deal_opens_themed_crm_form(chromium, crm_server, monkeypatch):
    monkeypatch.setattr(A, 'TASKS_ENABLED', True)
    monkeypatch.setattr(A, 'STAND_MODE', False)
    monkeypatch.setattr(A, '_stand_deliver_notes', lambda: None)
    with A.get_session() as db:
        db.add(A.AdminUser(username='qa_draft_manager', display_name='QA Draft Manager',
                           role='manager', password_hash='unused'))
        db.commit()

    base, cookie = crm_server
    with chromium.new_context(viewport={'width': 1440, 'height': 900}, reduced_motion='reduce') as context:
        context.add_cookies([{'name': 'session', 'value': cookie, 'url': base}])
        context.route('**/*', lambda route: route.continue_()
                      if urlsplit(route.request.url).hostname == '127.0.0.1' else route.abort())
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('dialog', lambda dialog: dialog.accept())
        page.goto(base + '/tasks')
        page.get_by_role('button', name='+ Новая задача').click()
        page.locator('#draftSourceCard').get_by_text('Telegram', exact=True).click()
        page.locator('#cq').fill('QA Synthetic Client')
        page.get_by_role('button', name='Создать нового клиента «QA Synthetic Client»').click()
        page.locator('#d_manager').select_option(label='QA Draft Manager')
        page.locator('#draftInquiryType').select_option('client')
        page.locator('#d_sum').fill('15500')
        page.evaluate('standWaitSaved()')
        page.get_by_role('button', name='Внести целиком').click()

        editor = page.locator('#crmDraftHost')
        client = editor.locator('#clientSearchInput')
        expect(client).to_have_value('QA Synthetic Client')
        source = page.locator('#crmDraftSource')
        reference = page.locator('#crmDraftSourceRef')
        error = page.locator('#crmDraftSourceError')
        expect(source).to_have_value('tg')
        expect(reference).to_have_value('')
        expect(reference).to_have_attribute('required', '')
        page.evaluate('standWaitSaved()')
        saves = []
        page.on('request', lambda request: saves.append(request)
                if request.method == 'PUT' and request.url.endswith('/api/stand/state') else None)
        page.locator('#crmDraftSave').click()
        expect(error).to_have_text('Укажите чат.')
        expect(reference).to_be_focused()
        assert not saves

        source.select_option('none')
        expect(reference).not_to_have_attribute('required', '')
        expect(error).to_be_hidden()
        source.select_option('wa')
        reference.fill('QA Manual WhatsApp Source')
        expect(reference).to_have_attribute('required', '')
        root = page.locator('html')
        expect(root).to_have_class('slate-console')
        expect(editor.locator('#managerSelect')).to_have_attribute('data-upgraded', 'true')
        for field in ('managerSelect', 'dealProductSelect', 'leaseholdPayoutRoute', 'payinMethod'):
            wrap = editor.locator(f'#{field}').locator('..')
            expect(wrap.locator('.custom-select-btn')).to_be_visible()
            expect(wrap.locator('.custom-select-list')).to_be_hidden()
            assert wrap.locator('.custom-select-btn').evaluate('el => el.getBoundingClientRect().height >= 44')
        product = editor.locator('#dealProductSelect').locator('..')
        button = product.locator('.custom-select-btn')
        menu = product.locator('.custom-select-list')
        button.click()
        expect(menu).to_be_visible()
        assert menu.evaluate('el => getComputedStyle(el).position === "absolute"')
        menu.get_by_text('Недвижимость лизхолд', exact=True).click()
        expect(menu).to_be_hidden()

        editor.get_by_role('button', name='Добавить агента').click()
        agent = editor.locator('#agentsBlockStd [data-key="percent"]')
        expect(agent).to_be_visible()
        agent.fill('15')
        expect(agent).to_have_value('15')
        invoice = editor.locator('#mfInvoiceThb')
        expect(invoice).to_have_value('15500')
        invoice.fill('16000')
        invoice.blur()

        # A queued board save sends a snapshot without the local draft. The reply
        # must apply without removing the draft or resetting values in the editor.
        with page.expect_response(lambda response: response.request.method == 'PUT'
                                  and response.url.endswith('/api/stand/state')) as reply:
            page.evaluate('standSave()')
        assert reply.value.ok
        assert not reply.value.json()['data']['deals']
        expect(editor.locator('#managerSelect')).to_have_attribute('data-upgraded', 'true')
        expect(invoice).to_have_value('16000')
        expect(agent).to_have_value('15')
        expect(reference).to_have_value('QA Manual WhatsApp Source')
        button.click()
        expect(menu).to_be_visible()
        button.press('Escape')
        expect(menu).to_be_hidden()

        for width in (1440, 390):
            page.set_viewport_size({'width': width, 'height': 900})
            for preset in ('slate', 'tangerine'):
                page.evaluate('preset => document.documentElement.dataset.preset = preset', preset)
                for mode in ('light', 'dark'):
                    if root.get_attribute('data-mode') != mode:
                        previous = client.evaluate('el => getComputedStyle(el).backgroundColor')
                        page.locator('[data-slate-mode]').click()
                        assert client.evaluate('el => getComputedStyle(el).backgroundColor') != previous
                    expect(root).to_have_attribute('data-mode', mode)
                    assert client.evaluate('''el => {
                        const token = document.createElement('div');
                        token.style.backgroundColor = 'var(--card)';
                        el.parentElement.append(token);
                        const result = getComputedStyle(el).backgroundColor === getComputedStyle(token).backgroundColor;
                        token.remove();
                        return result;
                    }''')
                    assert editor.locator('#mfDealHint').evaluate(
                        'el => getComputedStyle(el).backgroundColor !== "rgb(245, 243, 255)"'
                    )
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')

        # The form remains wired to its original fields after changing appearance.
        expect(editor.locator('#dealKindSelect')).to_have_value('mf_realty')
        expect(client).to_have_value('QA Synthetic Client')
        with page.expect_response(lambda response: response.request.method == 'PUT'
                                  and response.url.endswith('/api/stand/state')) as published:
            page.locator('#crmDraftSave').click()
        assert published.value.ok, published.value.json()
        [card] = published.value.json()['data']['deals']
        assert card['client'] == 'QA Synthetic Client'
        assert (card['source'], card['sourceRef'], card['srefOther']) == (
            'wa', 'QA Manual WhatsApp Source', True)
        assert not errors
