"""A working handoff saves once as the manager and recognises files as the operator."""
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

import app as A
from tests.test_browser_crm import chromium, crm_server  # noqa: F401


@pytest.mark.browser
def test_document_handoff_recognises_as_operator_and_preserves_edits(chromium, crm_server, monkeypatch):
    monkeypatch.setattr(A, 'TASKS_ENABLED', True)
    monkeypatch.setattr(A, 'STAND_MODE', False)
    monkeypatch.setattr(A, '_stand_deliver_notes', lambda: None)
    monkeypatch.setitem(A.app.config, 'SESSION_COOKIE_SECURE', False)
    password = 'synthetic-only'
    with A.get_session() as db:
        db.add_all([
            A.AdminUser(username=f'qa_handoff_{role}', display_name=f'QA Handoff {role}',
                        role=role, password_hash=A.AdminUser.hash_password(password))
            for role in ('manager', 'operator')
        ])
        db.commit()

    base, _ = crm_server

    def state_write(request):
        return request.url.endswith('/api/stand/state') and request.method == 'PUT'

    def login(context, role):
        assert context.request.post(base + '/api/auth/login', data={
            'username': f'qa_handoff_{role}', 'password': password,
        }).ok
        context.route('**/api/docs/parse/capability', lambda route: route.fulfill(json={'available': True}))

    with (chromium.new_context(viewport={'width': 390, 'height': 900}, reduced_motion='reduce') as manager,
          chromium.new_context(viewport={'width': 1440, 'height': 900}, reduced_motion='reduce') as operator):
        login(manager, 'manager')
        login(operator, 'operator')
        manager.route('**/api/docs/parse', lambda route: route.fulfill(
            status=403, json={'success': False, 'error': 'stand_blocked'}))
        page = manager.new_page()
        page.set_default_timeout(7000)
        page.goto(base + '/tasks')
        expect(page.locator('html')).to_have_class('slate-console')
        page.get_by_role('button', name='+ Новая задача').click()
        page.get_by_text('Без переписки', exact=True).click()
        page.locator('#cq').fill('QA Handoff Client')
        page.get_by_role('button', name='Создать нового клиента «QA Handoff Client»').click()
        page.locator('#draftInquiryType').select_option('client')
        page.locator('#d_sum').fill('15500')
        page.get_by_role('button', name='Курс знаю — сам').click()
        page.wait_for_load_state('networkidle')
        held = []
        dropped = []

        def delay_then_drop_save(route):
            if not state_write(route.request):
                route.continue_()
            elif not held:
                held.append(route)
            elif not dropped:
                dropped.append(route.request)
                route.abort('failed')
            else:
                route.continue_()

        page.route('**/api/stand/state', delay_then_drop_save)
        page.get_by_role('button', name='Нет, спросить операциониста').click()
        page.get_by_role('button', name='Курс знаю — заполню сам').click()
        page.locator('#m1').fill('92.5')
        page.locator('#m2').fill('34.5')
        page.get_by_role('button', name='Курс проставлен — считать клиенту').click()
        page.locator('#r3').fill('2.8')
        expect(page.locator('#r4')).to_have_value('43 400')
        page.get_by_role('button', name='Клиент согласен').click()
        expect(page.get_by_text('Сохраняем курсы. Дождитесь подтверждения и повторите.', exact=True)).to_be_visible()
        assert len(held) == 1
        with page.expect_event('requestfailed', predicate=state_write):
            held[0].continue_()
        expect(page.get_by_text('Не сохранилось — проверьте связь', exact=True)).to_be_visible()
        expect(page.locator('#r3')).to_have_value('2.8')
        with page.expect_response(lambda response: state_write(response.request)) as retry:
            page.get_by_role('button', name='Клиент согласен').click()
        assert retry.value.ok, retry.value.json()
        assert retry.value.json()['data']['deals'][0]['step'] == 's6'
        expect(page.locator('#r3')).to_have_value('2.8')
        with page.expect_response(lambda response: state_write(response.request)) as agreed:
            page.get_by_role('button', name='Клиент согласен').click()
        assert agreed.value.ok, agreed.value.json()
        assert agreed.value.json()['data']['deals'][0]['step'] == 's8'
        expect(page.get_by_role('button', name='Передать операционисту')).to_be_visible()
        page.unroute('**/api/stand/state', delay_then_drop_save)

        for caption, name in (('Загранпаспорт', 'qa-passport.pdf'), ('Инвойс', 'qa-invoice.pdf')):
            row = page.locator('.li').filter(has=page.get_by_text(caption, exact=True))
            with page.expect_file_chooser() as chooser:
                row.get_by_role('button', name='Загрузить').click()
            with page.expect_response('**/api/stand/files') as uploaded:
                chooser.value.set_files({'name': name, 'mimeType': 'application/pdf',
                                         'buffer': b'%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\n%%EOF'})
            assert uploaded.value.ok, uploaded.value.json()
            expect(row.get_by_text(name, exact=False).first).to_be_visible()
        assert page.evaluate('standWaitSaved()')['ok']

        writes, recognition = [], []
        page.on('request', lambda request: writes.append(request) if state_write(request) else None)
        page.on('request', lambda request: recognition.append(request)
                if urlsplit(request.url).path == '/api/docs/parse' else None)
        with page.expect_response(lambda response: state_write(response.request)) as handoff:
            page.get_by_role('button', name='Передать операционисту').click()
        assert handoff.value.ok, handoff.value.json()
        card, = handoff.value.json()['data']['deals']
        assert card['step'] == 's11'
        assert card['files']['pass'] and card['files']['inv']
        expect(page.get_by_text('Задача сохранена', exact=True)).to_be_visible()
        page.wait_for_load_state('networkidle')
        assert len(writes) == 1
        assert not recognition
        expect(page.get_by_text('Не удалось сохранить задачу', exact=True)).to_have_count(0)

        pending = []
        operator.route('**/api/docs/parse', lambda route: pending.append(route))
        receiver = operator.new_page()
        receiver.set_default_timeout(7000)
        receiver.goto(f'{base}/tasks?deal={card["id"]}')
        expect(receiver.locator('.deal-screen')).to_contain_text('QA Handoff Client')
        expect(receiver.get_by_text('Распознаём документы…', exact=False)).to_be_visible()
        assert len(pending) == 1
        name = receiver.locator('#df_dev')
        name.fill('QA Manual Recipient')
        with receiver.expect_response(lambda response: state_write(response.request)) as saved:
            pending[0].fulfill(json={'success': True, 'fields': {
                'recipient_name': 'QA OCR Recipient', 'client_name_en': 'QA OCR CLIENT',
            }, 'parsed_slots': ['passport', 'invoice']})
        assert saved.value.ok, saved.value.json()
        result, = saved.value.json()['data']['deals']
        assert result['docParse']['fields']['recipient_name'] == 'QA OCR Recipient'
        expect(receiver.locator('#df_fioLat')).to_have_value('QA OCR CLIENT')
        expect(name).to_have_value('QA Manual Recipient')
