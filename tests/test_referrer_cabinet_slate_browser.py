"""Withdrawal journeys through the public cabinet and the local Flask API."""

import re
from threading import Thread

import pytest
from werkzeug.serving import make_server

import app as A


@pytest.fixture
def cabinet_server(monkeypatch):
    monkeypatch.setattr(A, 'STAND_MODE', False)
    monkeypatch.setattr(A, '_bitazza_bids', lambda: [(35.0, 10_000)])
    monkeypatch.setattr(A, 'send_referrer_dm', lambda *args, **kwargs: False)
    with make_server('127.0.0.1', 0, A.app, threaded=True) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f'http://127.0.0.1:{server.server_port}'
        finally:
            server.shutdown()
            thread.join(timeout=5)


@pytest.fixture
def funded_cabinet():
    with A.get_session() as db:
        partner = A.Referrer(name='Synthetic Partner', code='SLATE-QA', token='synthetic-slate-payout', is_test=True)
        deal = A.Deal(deal_type=A.DealType.PAY_IN, status=A.DealStatus.COMPLETED, payout_amount_thb=9_800)
        db.add_all([partner, deal])
        db.flush()
        db.add(A.DealAgent(deal_id=deal.id, referrer_id=partner.id, name=partner.name,
                           payout_usdt=80.0, comp_model='fixed'))
        db.commit()
        partner_id, deal_id = partner.id, deal.id
    try:
        yield partner
    finally:
        with A.get_session() as db:
            db.query(A.PayoutRequest).filter_by(referrer_id=partner_id).delete()
            db.query(A.DealAgent).filter_by(deal_id=deal_id).delete()
            db.query(A.Deal).filter_by(id=deal_id).delete()
            db.query(A.Referrer).filter_by(id=partner_id).delete()
            db.commit()


@pytest.mark.browser
@pytest.mark.parametrize(
    'width, language, method, request_label, method_label, done_label, cancel_label, sent_label',
    [
        (390, 'ru', 'usdt', 'Запросить выплату', 'Криптовалютой',
         'Готово', 'Отменить заявку', 'Заявка уже отправлена'),
        (1440, 'en', 'thb', 'Request a payout', 'THB to a bank account',
         'Done', 'Cancel request', 'Request already sent'),
    ],
    ids=['mobile-ru-usdt', 'desktop-en-thb'],
)
def test_withdrawal_refreshes_in_place_and_can_be_repeated(
        cabinet_server, funded_cabinet, pytestconfig, width, language, method,
        request_label, method_label, done_label, cancel_label, sent_label):
    from playwright.sync_api import expect, sync_playwright

    with A.get_session() as db:
        db.get(A.Referrer, funded_cabinet.id).lang = language
        db.commit()
    api = f'{cabinet_server}/api/ref/{funded_cabinet.token}'
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True, executable_path=pytestconfig.getoption('--chromium-executable'))
        context = browser.new_context(viewport={'width': width, 'height': 850},
                                      is_mobile=width == 390, service_workers='block')
        context.route('**/*', lambda route: route.continue_()
                      if route.request.url.startswith(cabinet_server + '/') else route.abort())
        page = context.new_page()
        page.set_default_timeout(8000)
        errors = []
        navigations = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('framenavigated', lambda frame: navigations.append(frame.url)
                if frame == page.main_frame else None)
        page.on('dialog', lambda dialog: dialog.accept())
        page.goto(f'{cabinet_server}/ref/{funded_cabinet.token}')
        expect(page.locator('html')).to_have_attribute('lang', language)
        expect(page.locator('#deals-list')).to_be_visible()
        request_button = page.get_by_role('button', name=request_label, exact=True)
        modal = page.locator('#payoutModal')
        expect(modal).not_to_be_visible()
        request_ids = []

        for attempt in range(2):
            request_button.click()
            expect(modal.locator('#payoutAmount')).to_have_text(re.compile(r'\$80\.00|80,00\s*\$'))
            if method == 'thb':
                expect(modal.locator('#pmThbAmt')).to_contain_text('฿')
            modal.get_by_role('button', name=re.compile(method_label)).click()
            if method == 'usdt':
                modal.locator('#pmWallet').fill('synthetic-usdt-wallet')
                modal.locator('#pmContactValue').fill('@synthetic_contact')
                submit = modal.locator('#pmSubmit')
            else:
                expect(modal.locator('#thbBigAmount')).to_contain_text('฿')
                bank = modal.get_by_role('combobox', name='Bank', exact=True)
                options = modal.get_by_role('listbox')
                if attempt == 0:
                    bank.click()
                    expect(options).to_be_visible()
                    expect(options.get_by_role('option', name='Bangkok Bank', exact=True)).to_be_visible()
                    bank.fill('kbank')
                    expect(options.get_by_role('option')).to_have_count(1)
                    selected_bank = 'Kasikorn (KBank)'
                    options.get_by_role('option', name=selected_bank, exact=True).click()
                    expect(options).not_to_be_visible()
                else:
                    selected_bank = 'Synthetic Bank'
                    bank.fill(selected_bank)
                    expect(options.get_by_role('option')).to_have_count(0)
                expect(bank).to_have_value(selected_bank)
                modal.locator('#pmThbAccName').fill('Synthetic Recipient')
                modal.locator('#pmThbAccNum').fill('000-0-00000-0')
                modal.locator('#pmThbContact').fill('@synthetic_contact')
                submit = modal.locator('#pmSubmitThb')

            with page.expect_response(f'{api}/payout-request') as submitted:
                submit.click()
            assert submitted.value.ok
            payout = submitted.value.json()['request']
            assert payout['payout_method'] == method and payout['amount_usdt'] == 80.0
            request_id = payout['id']
            if method == 'thb':
                assert payout['thb_amount'] == 2773
                assert submitted.value.request.post_data_json['bank_name'] == selected_bank
                with A.get_session() as db:
                    assert db.get(A.PayoutRequest, request_id).bank_name == selected_bank
            request_ids.append(request_id)
            expect(modal.locator('#payoutSuccessBox')).to_be_visible()
            modal.get_by_role('button', name=done_label, exact=True).click()
            expect(modal).not_to_be_visible()
            expect(page.get_by_role('button', name=sent_label, exact=True)).to_be_disabled()

            with page.expect_response(f'{api}/payout-request/{request_id}/cancel') as cancelled:
                page.get_by_role('button', name=cancel_label, exact=True).click()
            assert cancelled.value.ok
            expect(request_button).to_be_enabled()
            expect(page.locator('#payouts-list .payout-status.cancelled').first).to_be_attached()

        stats = page.request.get(f'{api}/stats').json()
        assert not stats['active_request']
        assert stats['available_for_withdraw'] == 80.0
        assert {item['id'] for item in stats['payout_requests'] if item['status'] == 'cancelled'} == set(request_ids)
        assert len(navigations) == 1
        assert not errors
        browser.close()


@pytest.mark.browser
def test_mobile_payout_stays_visible_when_keyboard_changes_only_the_visual_viewport(
        cabinet_server, funded_cabinet, pytestconfig):
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True, executable_path=pytestconfig.getoption('--chromium-executable'))
        context = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True,
                                      has_touch=True, service_workers='block')
        context.route('**/*', lambda route: route.continue_()
                      if route.request.url.startswith(cabinet_server + '/') else route.abort())
        # A headless browser has no system keyboard. Keep its real layout
        # viewport intact while delivering iOS-like visual viewport updates.
        context.add_init_script("""
            const viewport = Object.assign(new EventTarget(), {
                width: 390, height: 844, offsetTop: 0, offsetLeft: 0,
                pageTop: 0, pageLeft: 0, scale: 1,
            });
            Object.defineProperty(window, 'visualViewport', {value: viewport});
            window.__setKeyboardViewport = ({height, top, event}) => {
                Object.assign(viewport, {height, offsetTop: top, pageTop: scrollY + top});
                viewport.dispatchEvent(new Event(event));
            };
        """)
        page = context.new_page()
        page.goto(f'{cabinet_server}/ref/{funded_cabinet.token}')
        page.get_by_role('button', name='Запросить выплату', exact=True).click()
        modal = page.locator('#payoutModal')
        modal.get_by_role('button', name=re.compile('Батами на банк')).click()
        contact = modal.locator('#pmThbContact')
        contact.focus()
        expect(contact).to_be_focused()
        layout_height = page.evaluate('document.documentElement.clientHeight')

        def set_visual_viewport(height, top, event):
            page.evaluate('update => window.__setKeyboardViewport(update)',
                          {'height': height, 'top': top, 'event': event})
            assert page.evaluate('document.documentElement.clientHeight') == layout_height

        def wait_for_visible_dialog_and_contact():
            page.wait_for_function("""
                () => {
                    const modal = document.querySelector('#payoutModal');
                    const contact = document.querySelector('#pmThbContact');
                    const top = visualViewport.offsetTop;
                    const bottom = top + visualViewport.height;
                    const frame = modal.getBoundingClientRect();
                    const field = contact.getBoundingClientRect();
                    return modal.open && document.activeElement === contact &&
                        frame.top >= top - 1 && frame.bottom <= bottom + 1 &&
                        field.top >= frame.top - 1 && field.bottom <= frame.bottom + 1;
                }
            """, timeout=3000)

        set_visual_viewport(height=335, top=116, event='resize')
        wait_for_visible_dialog_and_contact()
        set_visual_viewport(height=335, top=168, event='scroll')
        wait_for_visible_dialog_and_contact()
        set_visual_viewport(height=844, top=0, event='resize')
        wait_for_visible_dialog_and_contact()
        browser.close()
