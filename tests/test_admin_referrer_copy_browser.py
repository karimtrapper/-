"""Exercise copy feedback from the authenticated admin referrer list."""

from urllib.parse import urlsplit

import pytest

import app as A


@pytest.mark.browser
@pytest.mark.parametrize('mode', ['light', 'dark'])
def test_admin_referrer_link_copy(monkeypatch, pytestconfig, mode):
    from playwright.sync_api import expect, sync_playwright

    monkeypatch.setattr(A, 'TASKS_ENABLED', True)
    monkeypatch.setattr(A, 'STAND_MODE', False)
    origin = 'https://calccrm.test'
    token = f'admin-copy-{mode}'
    name = 'Synthetic "Name" & O\'Example'
    urls = {
        'referral_link': 'https://site.invalid/?ref=test&lang=en',
        'bot_link': 'https://bot.invalid/start?ref=test&lang=en',
        'wa_link': 'https://chat.invalid/send/?text="test\'"&lang=en',
    }
    monkeypatch.setattr(A, 'referral_links', lambda *_: urls)
    with A.get_session() as db:
        staff = A.AdminUser(username=f'admin-copy-{mode}', display_name='Copy Admin',
                            role='admin', password_hash=A.AdminUser.hash_password('synthetic-local'))
        referrer = A.Referrer(name=name, code='TEST&"CODE"', telegram='@demo & <test>',
                              token=token, active=True)
        deal = A.Deal(deal_type=A.DealType.PAY_IN, status=A.DealStatus.COMPLETED, client_name='Synthetic client')
        db.add_all([staff, referrer, deal])
        db.flush()
        db.add(A.DealAgent(referrer_id=referrer.id, deal_id=deal.id, payout_usdt=5))
        db.commit()
        staff_id, deal_id = staff.id, deal.id

    client = A.app.test_client()
    assert client.post('/api/auth/login', json={
        'username': f'admin-copy-{mode}', 'password': 'synthetic-local',
    }).status_code == 200

    def serve(route):
        request = route.request
        url = urlsplit(request.url)
        if url.hostname != 'calccrm.test':
            route.abort()
            return
        if url.path == '/api/rates':
            route.fulfill(json={'success': False})
            return
        response = client.open(url.path, query_string=url.query, method=request.method)
        route.fulfill(status=response.status_code, content_type=response.content_type, body=response.get_data())

    def contrast(toast):
        return toast.evaluate("""el => {
            const css = getComputedStyle(el);
            const ctx = document.createElement('canvas').getContext('2d', {willReadFrequently: true});
            const luminance = color => {
                ctx.clearRect(0, 0, 1, 1);
                ctx.fillStyle = color;
                ctx.fillRect(0, 0, 1, 1);
                return [...ctx.getImageData(0, 0, 1, 1).data].slice(0, 3)
                    .map(value => value / 255)
                    .map(value => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4)
                    .reduce((sum, value, i) => sum + value * [0.2126, 0.7152, 0.0722][i], 0);
            };
            const levels = [luminance(css.color), luminance(css.backgroundColor)];
            return (Math.max(...levels) + 0.05) / (Math.min(...levels) + 0.05);
        }""")

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, executable_path=pytestconfig.getoption('--chromium-executable'))
            page = browser.new_page(service_workers='block')
            page.route('**/*', serve)
            page.add_init_script(f"""localStorage.setItem('calccrm:slate-preferences', JSON.stringify({{mode: '{mode}'}}));""")
            page.add_init_script("""Object.defineProperty(navigator, 'clipboard', {value: {
                async writeText(text) {
                    if (!navigator.userActivation.isActive) throw new DOMException('', 'NotAllowedError');
                    if (window.clipboardRejected) throw new DOMException('', 'NotAllowedError');
                    await new Promise(resolve => { window.finishClipboard = resolve; });
                    window.copied = text;
                }
            }, configurable: true});""")
            page.goto(origin + '/crm?section=referrers')
            expect(page.locator('html')).to_have_attribute('data-mode', mode)
            row = page.locator('.referrer-row').filter(has_text=name)
            expect(row).to_contain_text('TEST&"CODE"')
            expect(row).to_contain_text('@demo & <test>')
            assert row.get_attribute('data-referrer-name') == name
            success = page.locator('.toast.success', has_text='Ссылка скопирована')
            fields = {
                'Статистика': f'{origin}/ref/{token}',
                'Сайт': urls['referral_link'], 'Telegram': urls['bot_link'], 'WhatsApp': urls['wa_link'],
            }
            for index, (label, url) in enumerate(fields.items()):
                field = row.get_by_role('textbox', name=label, exact=True)
                expect(field).to_have_value('WhatsApp' if label == 'WhatsApp' else url)
                if index == 1:
                    field.press('Enter')
                else:
                    field.click()
                page.wait_for_function('window.finishClipboard')
                expect(success).to_have_count(0)
                page.evaluate('window.finishClipboard(); delete window.finishClipboard;')
                expect(success).to_be_visible()
                assert page.evaluate('window.copied') == url
                assert contrast(success) >= 4.5
                success.evaluate('el => el.remove()')
            assert len(page.context.pages) == 1
            page.evaluate('window.clipboardRejected = true;')
            field = row.get_by_role('textbox', name='WhatsApp', exact=True)
            field.click()
            warning = page.locator('.toast.warning', has_text='Скопируйте выделенную ссылку')
            expect(warning).to_be_visible()
            assert field.evaluate('el => el.value.slice(el.selectionStart, el.selectionEnd)') == fields['WhatsApp']
            assert contrast(warning) >= 4.5
            expect(success).to_have_count(0)
            warning.evaluate('el => el.remove()')
            page.evaluate('delete navigator.clipboard; Object.defineProperty(navigator, "clipboard", {value: undefined});')
            field = row.get_by_role('textbox', name='Статистика', exact=True)
            for _ in range(2):
                field.click()
                expect(warning).to_be_visible()
                assert field.evaluate("""async el => {
                    await new Promise(resolve => setTimeout(resolve, 400));
                    return el.value.slice(el.selectionStart, el.selectionEnd);
                }""") == fields['Статистика']
                expect(success).to_have_count(0)
                warning.evaluate('el => el.remove()')
            row.locator('summary').click()
            row.get_by_role('button', name='Сделки', exact=True).click()
            expect(page.locator('#dealModal .modal-title')).to_have_text('Реферер: ' + name)
            page.locator('#dealModal .modal-close').click()
            row.get_by_role('button', name='Выплатить', exact=True).click()
            modal = page.locator('#dealModal')
            expect(modal.locator('.modal-title')).to_have_text('Выплата: ' + name)
            confirmations = []
            def cancel_payout(dialog):
                confirmations.append(dialog.message)
                dialog.dismiss()
            page.once('dialog', cancel_payout)
            modal.get_by_role('button', name='Выплатить выбранные', exact=True).click()
            assert len(confirmations) == 1 and name in confirmations[0]
            browser.close()
    finally:
        with A.get_session() as db:
            db.query(A.DealAgent).filter_by(deal_id=deal_id).delete()
            db.query(A.Deal).filter_by(id=deal_id).delete()
            db.query(A.Referrer).filter_by(token=token).delete()
            db.query(A.AdminUser).filter_by(id=staff_id).delete()
            db.commit()
