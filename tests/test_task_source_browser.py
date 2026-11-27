"""Check that the working task form uses the board's source contract."""
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

import app as A
from tests.test_browser_crm import chromium, crm_server  # noqa: F401


@pytest.mark.browser
@pytest.mark.parametrize('width', [390, 1440])
def test_working_task_requires_source_before_creation(chromium, crm_server, monkeypatch, width):
    monkeypatch.setattr(A, 'TASKS_ENABLED', True)
    monkeypatch.setattr(A, '_stand_deliver_notes', lambda: [])
    with A.get_session() as db:
        manager = A.AdminUser(username='source-qa', display_name='Source QA', role='manager',
                              password_hash='unused')
        db.add(manager)
        db.add(A.StandChannel(channel='tg', account='audit', chat_id='42', name='QA Telegram Chat'))
        db.commit()
        user_id = manager.id

    base, _ = crm_server
    cookie = A.app.session_interface.get_signing_serializer(A.app).dumps({'user_id': user_id})
    with chromium.new_context(viewport={'width': width, 'height': 880}) as context:
        context.add_cookies([{'name': 'session', 'value': cookie, 'url': base}])
        context.route('**/*', lambda route: route.continue_()
                      if urlsplit(route.request.url).hostname == '127.0.0.1' else route.abort())
        page = context.new_page()
        page.on('dialog', lambda dialog: dialog.accept())
        submits = []

        def record(request):
            if request.method == 'PUT' and urlsplit(request.url).path == '/api/stand/state':
                submits.append(request)

        page.on('request', record)
        page.goto(base + '/tasks')
        page.get_by_role('button', name='+ Новая задача').click()
        submit = page.get_by_role('button', name='Создать заявку', exact=False)
        source = page.locator('#draftSourceCard')
        page.locator('#draftInquiryType').select_option('client')
        page.locator('#d_sum').fill('32000')

        for name in ('Telegram', 'WhatsApp'):
            source.get_by_text(name, exact=True).click()
            page.wait_for_function('!standBusy && !standPush && !standSaveScheduled')
            count = len(submits)
            submit.click()
            expect(source.get_by_role('alert')).to_contain_text('Выберите чат')
            expect(source).to_be_focused()
            assert len(submits) == count

        def fill_draft(client):
            page.locator('#draftInquiryType').select_option('client')
            page.locator('#cq').fill(client)
            page.get_by_role('button', name=f'Создать нового клиента «{client}»').click()
            page.locator('#d_sum').fill('32000')

        def save_source(channel, reference, manual):
            submit.click()
            expect(page.locator('.deal-head')).to_be_visible()
            board = context.request.get(base + '/api/stand/state?read_only=1').json()['data']
            matching = [deal for deal in board['deals'] if deal['source'] == channel]
            assert len(matching) == 1
            saved = matching[0]
            assert saved.get('sourceRef', '') == reference
            assert bool(saved.get('srefOther')) is manual

        source.get_by_text('Без переписки', exact=True).click()
        fill_draft('QA Without Chat')
        save_source('none', '', False)

        page.goto(base + '/tasks')
        page.get_by_role('button', name='+ Новая задача').click()
        source.get_by_text('WhatsApp', exact=True).click()
        page.get_by_role('button', name='Чата нет в списке', exact=False).click()
        page.locator('#sref_m').fill('QA WhatsApp manual reference')
        page.get_by_role('button', name='Привязать', exact=True).click()
        fill_draft('QA Manual Chat Client')
        save_source('wa', 'QA WhatsApp manual reference', True)

        page.goto(base + '/tasks')
        page.get_by_role('button', name='+ Новая задача').click()
        source.get_by_text('QA Telegram Chat', exact=True).click()
        fill_draft('QA Directory Chat Client')
        save_source('tg', 'audit:42', False)
