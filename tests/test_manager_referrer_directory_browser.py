"""Manager directory journeys through the CRM and authenticated Flask routes."""

from urllib.parse import urlsplit

import pytest

import app as A


@pytest.mark.browser
@pytest.mark.parametrize('width', [390, 1440])
def test_manager_referrer_directory_and_deal_picker(monkeypatch, pytestconfig, width):
    from playwright.sync_api import expect, sync_playwright

    monkeypatch.setattr(A, 'TASKS_ENABLED', True)
    monkeypatch.setattr(A, 'STAND_MODE', False)
    origin = 'https://calccrm.test'
    legacy_name = f'Browser {width} legacy'
    new_name = f'Browser {width} new'
    with A.get_session() as db:
        manager = A.AdminUser(username=f'ui-manager-{width}', display_name='UI Manager',
                              role='manager', password_hash=A.AdminUser.hash_password('synthetic-local'))
        legacy = A.Referrer(name=legacy_name, code=f'LEGACY-{width}', token=f'legacy-ui-{width}',
                            auth_mode='telegram', telegram='legacy contact format', active=True)
        db.add_all([manager, legacy])
        db.commit()
        legacy_id, manager_id = legacy.id, manager.id

    client = A.app.test_client()
    reply = client.post('/api/auth/login', json={'username': f'ui-manager-{width}', 'password': 'synthetic-local'})
    assert reply.status_code == 200
    changes = []

    def serve(route):
        request = route.request
        url = urlsplit(request.url)
        if url.hostname != 'calccrm.test':
            route.abort()
            return
        if request.method == 'PUT' and url.path.startswith('/api/manager/referrers/'):
            changes.append(request.post_data_json)
        response = client.open(
            url.path, query_string=url.query, method=request.method, data=request.post_data_buffer,
            content_type=request.headers.get('content-type'),
        )
        headers = {key: value for key, value in response.headers.items()
                   if key.lower() in {'content-type', 'cache-control'}}
        route.fulfill(status=response.status_code, headers=headers, body=response.get_data())

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, executable_path=pytestconfig.getoption('--chromium-executable'))
            page = browser.new_page(viewport={'width': width, 'height': 850}, is_mobile=width == 390,
                                    service_workers='block')
            page.route('**/*', serve)
            page.add_init_script("""Object.defineProperty(navigator, 'clipboard', {value: {
                async write(items) {
                    if (!navigator.userActivation.isActive) throw new DOMException('', 'NotAllowedError');
                    window.copied = await (await items[0].getType('text/plain')).text();
                }
            }});""")
            page.goto(origin + '/crm?section=deals')
            if width == 390:
                page.get_by_role('button', name='Найти раздел').click()
                page.get_by_role('searchbox', name='Название раздела').fill('Рефереры')
                page.locator('.slate-palette').get_by_role('link', name='Рефереры').click()
            else:
                page.locator('.slate-side').get_by_role('link', name='Рефереры').click()
            expect(page.locator('#managerReferrers')).to_be_visible()
            expect(page.locator('#adminReferrers')).to_be_hidden()
            page.locator('#managerReferrerSearch').fill(f'LEGACY-{width}')
            expect(page.locator('.manager-referrer-row')).to_have_count(1)
            expect(page.locator('.manager-referrer-row')).to_contain_text('Укажите имя пользователя Telegram')
            expect(page.get_by_role('button', name=f'Скопировать ссылку на кабинет — {legacy_name}')).to_have_count(0)
            page.get_by_role('button', name=f'Настроить кабинет — {legacy_name}').click()
            page.get_by_label('Язык кабинета').select_option('en')
            page.get_by_role('button', name='Сохранить', exact=True).click()
            expect(page.get_by_text('Настройки кабинета сохранены', exact=True)).to_be_visible()
            assert changes == [{'lang': 'en'}]

            page.get_by_role('button', name='Добавить реферера', exact=True).click()
            page.get_by_label('Имя реферера').fill(new_name)
            page.get_by_role('button', name='Сохранить', exact=True).click()
            copy = page.get_by_role('button', name=f'Скопировать ссылку на кабинет — {new_name}')
            with page.expect_response(lambda r: r.url.endswith('/cabinet-link')) as request:
                copy.click()
            endpoint = request.value
            assert endpoint.status == 200
            assert 'no-store' in endpoint.headers['cache-control']
            page.wait_for_function('url => window.copied === url', arg=origin + endpoint.json()['url'])
            assert len(page.context.pages) == 1
            expect(page.get_by_text('Ссылка на кабинет скопирована', exact=True)).to_be_visible()

            if width == 390:
                page.get_by_role('button', name='Переключить навигацию').click()
            page.locator('.slate-side').get_by_role('link', name='Сделки').click()
            page.locator('#deals .nav-create-btn').click()
            page.locator('#create button[onclick="stdAgentsAdd()"]').click()
            expect(page.locator('#agentsBlockStd select[data-agent-directory] option', has_text=new_name)).to_have_count(1)
            page.goto(origin + '/crm?section=referrers')
            expect(copy).to_be_visible()
            browser.close()
    finally:
        with A.get_session() as db:
            db.query(A.Referrer).filter((A.Referrer.id == legacy_id) | (A.Referrer.name == new_name)).delete()
            db.query(A.AdminUser).filter_by(id=manager_id).delete()
            db.commit()
