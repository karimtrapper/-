"""Реальный Chromium + Flask + временная SQLite. Внешние сервисы — фикстуры.

Запуск: python3 -m pytest tests/test_browser_crm.py --browser -v
Без --browser явно SKIPPED, отсутствие Chromium при --browser — ERROR.
"""
import json
import re
import threading
from datetime import datetime
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import sync_playwright, expect, Error as PlaywrightError
from werkzeug.serving import make_server

import app as A


def test_website_customers_dashboard_desktop_and_mobile(ui):
    page, errors, server_errors, _ = ui
    db = A.get_session()
    try:
        customer = A.Client(name='<img src=x onerror=alert(1)>')
        db.add(customer); db.flush()
        deal = A.Deal(deal_type=A.DealType('pay_in'), status=A.DealStatus.COMPLETED,
                      client_id=customer.id, client_name=customer.name,
                      source_channel='website_campaign', payin_amount_usdt=1000,
                      profit_usdt=100, net_profit_usdt=80, created_at=datetime(2023, 6, 1))
        db.add(deal); db.commit()
        db.add(A.Deal(deal_type=A.DealType('pay_in'), status=A.DealStatus.COMPLETED,
                      client_id=customer.id, client_name=customer.name,
                      payin_amount_usdt=200, profit_usdt=20, created_at=datetime(2023, 6, 2)))
        db.commit()
        deal_id = deal.id
    finally:
        db.close()

    page.locator('#periodSelector [data-period="all"]').click()
    expect(page.locator('#siteCustomersSummary')).to_contain_text('1')
    expect(page.locator('#siteCustomersCoverage')).to_contain_text('Источник не сохранён у 1')
    expect(page.locator('#siteCustomersRows')).to_contain_text('<img src=x onerror=alert(1)>')
    assert page.locator('#siteCustomersRows img').count() == 0
    page.locator('#siteCustomersRows summary').click()
    page.locator(f'#siteCustomersRows button:has-text("#{deal_id}")').click()
    expect(page.locator('#dealModal')).to_be_visible()
    page.locator('#dealModal .modal-close').click()

    page.locator('#siteCustomersSource').select_option('rentals')
    expect(page.locator('#siteCustomersRows')).to_contain_text('Нет покупок с сохранённой меткой')
    page.locator('#siteCustomersSource').select_option('unknown')
    expect(page.locator('#siteCustomersRows')).to_contain_text('Не сохранён')
    page.locator('#siteCustomersSource').select_option('site')
    page.set_viewport_size({'width': 390, 'height': 844})
    expect(page.locator('#siteCustomersRows')).to_contain_text('<img src=x onerror=alert(1)>')
    assert page.evaluate('document.querySelector("#siteCustomersCard").scrollWidth <= document.querySelector("#siteCustomersCard").clientWidth + 1')
    assert not errors, errors
    assert not server_errors, server_errors

pytestmark = pytest.mark.browser

TABS = ['dashboard', 'deals', 'documents', 'closing', 'exchangers', 'balance',
        'incomes', 'conversions', 'reimbursements', 'transactions', 'managers',
        'verification', 'kyc', 'partners', 'referrers', 'payoutRequests', 'admins']


@pytest.fixture
def crm_server(monkeypatch):
    """Настоящие auth/routes/БД; только границы внешних систем подменены."""
    assert 'calccrm-pytest-' in str(A.engine.url), 'Разрешена только pytest-БД'
    A.Session.remove()
    with A.engine.begin() as conn:
        for table in reversed(A.Base.metadata.sorted_tables):
            conn.execute(table.delete())
    db = A.get_session()
    admin = A.AdminUser(username='qa_browser', display_name='QA Browser',
                       password_hash=A.AdminUser.hash_password('local-test-only'))
    db.add(admin)
    db.add(A.Manager(name='QA Manager', active=True))
    db.commit()
    admin_id = admin.id
    db.close()

    async def rates():
        return {'usdt_thb': 34.5, 'rub_usdt': 92.5}

    monkeypatch.setattr(A.ExchangeRateProvider, 'get_all_rates', rates)
    monkeypatch.setattr(A, '_bitazza_calc_quote', lambda *a, **k: None)
    for name in ('sync_deals_to_gsheet', '_send_deal_telegram',
                 'send_deal_completed_webhook', 'notify_agents_new_deal'):
        monkeypatch.setattr(A, name, lambda *a, **k: None)
    A.app.config.update(TESTING=True, PROPAGATE_EXCEPTIONS=False)
    server = make_server('127.0.0.1', 0, A.app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    cookie = A.app.session_interface.get_signing_serializer(A.app).dumps({
        'user_id': admin_id, 'username': 'qa_browser', 'display_name': 'QA Browser'})
    yield base, cookie
    server.shutdown()
    thread.join(timeout=5)
    server.server_close()


@pytest.fixture(scope='module')
def chromium():
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except PlaywrightError as exc:
            if "Executable doesn't exist" not in str(exc):
                raise
            browser = p.chromium.launch(channel='chrome')
        yield browser
        browser.close()


@pytest.fixture
def ui(chromium, crm_server, tmp_path):
    base, cookie = crm_server
    context = chromium.new_context(viewport={'width': 1440, 'height': 900})
    context.add_cookies([{'name': 'session', 'value': cookie, 'url': base,
                         'httpOnly': True, 'sameSite': 'Lax'}])
    context.tracing.start(screenshots=True, snapshots=True, sources=True)

    def route(request_route):
        if urlsplit(request_route.request.url).hostname != '127.0.0.1':
            request_route.abort()
        else:
            request_route.continue_()

    context.route('**/*', route)
    page = context.new_page()
    errors, server_errors = [], []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('response', lambda r: server_errors.append(f'{r.status} {urlsplit(r.url).path}')
            if r.status >= 500 else None)
    page.goto(base + '/crm')
    expect(page.locator('#dashboard')).to_be_visible()
    yield page, errors, server_errors, base
    page.screenshot(path=str(tmp_path / 'last-state.png'), full_page=True)
    context.tracing.stop(path=str(tmp_path / 'trace.zip'))
    (tmp_path / 'errors.json').write_text(json.dumps({
        'page_errors': errors, 'http_5xx': server_errors}, ensure_ascii=False, indent=2))
    context.close()


@pytest.mark.parametrize('section', TABS)
def test_tab_opens_without_javascript_crash(ui, section):
    page, errors, _, _ = ui
    page.locator(f'.nav-tab[data-section="{section}"]').click()
    expect(page.locator(f'#{section}')).to_be_visible()
    # Дожидаемся fetch/render, а не только синхронного переключения класса.
    page.wait_for_load_state('networkidle')
    assert not errors, errors


@pytest.mark.parametrize('section,path', [
    ('documents', '/api/docs/agreements'), ('conversions', '/api/conversions'),
    ('incomes', '/api/sber-incomes'), ('closing', '/api/bitrix/active-deals')])
@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason='UI-01: showSection при восстановлении вкладки не загружает данные')
def test_reload_restores_tab_and_fetches_its_data(ui, section, path):
    page, _, _, _ = ui
    page.locator(f'.nav-tab[data-section="{section}"]').click()
    page.wait_for_load_state('networkidle')
    # Сохранение вкладки при click — тоже часть ожидаемого контракта.
    page.evaluate('(section) => localStorage.setItem("crm_section", section)', section)
    requests = []
    page.on('request', lambda req: requests.append(urlsplit(req.url).path))
    page.reload()
    expect(page.locator(f'#{section}')).to_be_visible()
    page.wait_for_load_state('networkidle')
    assert path in requests, (section, requests)


@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason='UI-02: мобильная кнопка Выйти не отзывает сессию')
def test_mobile_logout_revokes_session(ui):
    page, _, _, base = ui
    page.set_viewport_size({'width': 390, 'height': 844})
    page.locator('#moreBtn').click()
    page.locator('#morePanel').get_by_role('button', name='Выйти').click()
    page.wait_for_load_state('networkidle')
    assert page.request.get(base + '/api/deals').status == 401


@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason='SEC-XSS: Bitrix TITLE вставляется в innerHTML без escape')
def test_bitrix_title_is_text_not_executable_markup(ui):
    page, _, _, _ = ui
    payload = '<img src="/missing-qa-image" onerror="document.body.dataset.qaXss=1">'
    page.route('**/api/bitrix/active-deals', lambda route: route.fulfill(json={
        'success': True, 'deals': [{'ID': 7, 'TITLE': payload, 'STAGE_ID': 'NEW'}]}))
    page.locator('.nav-tab[data-section="closing"]').click()
    expect(page.locator('#bitrixDealsList')).to_contain_text('#7')
    page.wait_for_load_state('networkidle')
    assert page.locator('body').get_attribute('data-qa-xss') is None
    assert payload in page.locator('#bitrixDealsList').inner_text()


def choose(page, selector, label):
    """Выбор через видимую оболочку кастомного select, как у пользователя."""
    select = page.locator(selector)
    wrap = select.locator('..')
    if wrap.locator('.custom-select-btn').count():
        wrap.locator('.custom-select-btn').click()
        wrap.locator('.custom-select-opt').filter(has_text=label).click()
    else:
        select.select_option(label=label)


def test_calculator_prefill_requires_credited_rub(ui):
    page, errors, _, _ = ui
    page.locator('.nav-create-btn').click()
    expect(page.locator('#create')).to_be_visible()
    page.wait_for_load_state('networkidle')
    page.evaluate('''() => prefillDealForm({
        payin_method: 'sber_wl', payin_gross_reference_rub: 100000,
        payin_amount_usdt: 1000, payin_rate_rub_usdt: 100
    })''')
    expect(page.locator('#payinRubHint')).to_have_text('после комиссии банка')
    expect(page.locator('#payinGrossReference')).to_contain_text(
        'Введите фактически зачисленную сумму')
    expect(page.locator('[name="payin_amount_rub"]')).to_have_value('')
    assert page.locator('[name="payin_amount_rub"]').evaluate('(el) => el.required')
    expect(page.locator('[name="payin_rate_rub_usdt"]')).to_have_value('')
    # Старая ссылка с gross в payin_amount_rub тоже не создаёт gross-сделку.
    page.evaluate('''() => prefillDealForm({
        payin_method: 'sber_wl', payin_amount_rub: 100000,
        payin_rub_is_net: false
    })''')
    expect(page.locator('[name="payin_amount_rub"]')).to_have_value('')
    expect(page.locator('#payinRubHint')).to_have_text('после комиссии банка')
    assert not errors, errors


def test_custom_select_respects_disabled_and_doverka_option(ui):
    page, errors, _, _ = ui
    page.locator('.nav-create-btn').click()
    expect(page.locator('#create')).to_be_visible()
    page.wait_for_timeout(100)
    select = page.locator('#payinMethod')
    button = select.locator('..').locator('.custom-select-btn')
    expect(button).to_be_visible()
    page.evaluate('''() => { document.querySelector('#payinMethod').disabled = true; }''')
    expect(button).to_be_disabled()
    button.evaluate('(el) => el.click()')
    expect(select.locator('..').locator('.custom-select-list')).not_to_be_visible()
    page.evaluate('''() => { document.querySelector('#payinMethod').disabled = false; }''')
    expect(button).to_be_enabled()
    button.click()
    expect(select.locator('..').locator('.custom-select-list')).to_be_visible()
    expect(select.locator('..').locator('.custom-select-opt').filter(
        has_text='СБП (Доверка)')).to_have_count(1)
    page.evaluate('''() => {
        const s = document.querySelector('#payinMethod');
        s.value = 'spp_doverka'; s.dispatchEvent(new Event('change'));
    }''')
    expect(button).to_contain_text('СБП (Доверка)')
    assert select.input_value() == 'spp_doverka'
    assert not errors, errors


def test_flow_sole_custom_keeps_incoming_picker_and_manual_hash(ui):
    page, errors, _, _ = ui
    page.route('**/api/transactions/incoming?*', lambda route: route.fulfill(json={
        'success': True, 'available': [{
            'amount_usdt': 500, 'tx_hash': 'synthetic-flow-sole-hash',
            'from_address': 'synthetic', 'timestamp': '2026-10-20T12:00:00Z'}]}))
    page.locator('.nav-create-btn').click()
    expect(page.locator('#create')).to_be_visible()
    page.wait_for_load_state('networkidle')
    page.set_viewport_size({'width': 375, 'height': 812})
    standard_width = page.evaluate('document.documentElement.scrollWidth')
    assert standard_width <= 436, standard_width
    choose(page, '#payinMethod', 'Flow Sole')
    expect(page.locator('#flowSoleReqsStandard')).to_have_text('СГБ · р/с …0261')
    page.locator('[name="payin_amount_usdt"]').fill('1000')
    standard_tx = page.locator('#payinTxSelect')
    standard_tx.locator('..').locator('.custom-select-btn').click()
    standard_tx.locator('..').locator('.custom-select-opt').filter(has_text='synthetic').click()
    expect(page.locator('[name="payin_amount_usdt"]')).to_have_value('1000')
    assert page.evaluate('document.documentElement.scrollWidth') <= standard_width
    choose(page, '#dealProductSelect', 'Кастомная — нестандартные валюты')
    custom_width = page.evaluate('document.documentElement.scrollWidth')
    assert custom_width <= 436, custom_width
    choose(page, '#customPayinMethod', 'Flow Sole')
    assert page.evaluate('document.documentElement.scrollWidth') <= custom_width
    page.set_viewport_size({'width': 1440, 'height': 900})
    expect(page.locator('#customPayinPicker')).to_be_visible()
    expect(page.locator('#customPayinTxHashGroup')).to_be_visible()
    expect(page.locator('#flowSoleReqsCustom')).to_be_visible()
    expect(page.locator('#flowSoleReqsCustom')).to_have_text('СГБ · р/с …0261')
    expect(page.locator('#customPayinCurrency')).to_be_disabled()
    assert page.locator('#customPayinCurrency').input_value() == 'RUB'
    assert page.locator('#customPayinRate').evaluate('(el) => el.readOnly')
    page.locator('#customPayinAmount').fill('99300')
    page.locator('#customPayinUsdt').fill('1000')
    expect(page.locator('#customPayinRate')).to_have_value('99.3000')
    tx_select = page.locator('#customPayinTxSelect')
    tx_select.locator('..').locator('.custom-select-btn').click()
    tx_select.locator('..').locator('.custom-select-opt').filter(has_text='synthetic').click()
    expect(page.locator('#customPayinAmount')).to_have_value('99300')
    expect(page.locator('#customPayinUsdt')).to_have_value('1000')
    expect(page.locator('#customPayinPickerInfo')).to_contain_text('Введено $1000.00, в сети $500.00')
    expect(page.locator('#customPayinTxHash')).to_have_value('synthetic-flow-sole-hash')
    page.locator('#customPayinTxHash').fill('manual-flow-sole-hash')
    expect(page.locator('#customPayinTxHash')).to_have_value('manual-flow-sole-hash')
    assert not errors, errors


def test_flow_sole_custom_reopens_draft_usdt_and_profit(ui):
    page, errors, server_errors, base = ui
    response = page.request.post(base + '/api/deals', data={
        'client_name': 'Synthetic Flow draft', 'deal_type': 'pay_in',
        'status': 'pending', 'is_custom': True,
        'payin_method': 'sber_reqs', 'payin_account_key': 'flow_sole',
        'payin_amount_rub': 99300, 'payin_amount_usdt': 1000,
        'payin_rate_rub_usdt': 99.3, 'custom_payin_currency': 'RUB',
        'custom_payin_amount': 99300, 'custom_payin_rate': 99.3,
        'custom_payout_currency': 'USDT', 'custom_payout_amount': 970,
        'payout_amount_usdt': 970, 'payout_method': 'transfer',
    })
    assert response.status == 201, response.text()
    deal_id = response.json()['deal']['id']
    page.evaluate('(id) => openDealEditor(id)', deal_id)
    expect(page.locator('#customPayinUsdt')).to_have_value('1000')
    expect(page.locator('#customPayinRate')).to_have_value('99.3000')
    expect(page.locator('#customProfitUsdt')).to_have_value('$30.00')
    expect(page.locator('#flowSoleCustomStatus')).to_contain_text('не подтверждено в сети')
    assert not errors and not server_errors, (errors, server_errors)


def test_selected_acquiring_keeps_client_paid_hint_in_main_and_extra(ui):
    page, errors, _, _ = ui
    page.locator('.nav-create-btn').click()
    expect(page.locator('#create')).to_be_visible()
    page.wait_for_load_state('networkidle')
    page.evaluate('''() => {
        sberIncomesCache = ['main', 'extra'].map(uuid => ({
            uuid, kind: 'acquiring', amount_rub: 98000, gross_rub: 98700,
            fee_rub: 700, operation_date: '2026-10-20'
        }));
        sberAddIncome('main');
        payinExtraAdd();
        payinExtraSetMethod(0, 'sber_wl');
        payinExtraSberAdd(0, 'extra');
    }''')
    expect(page.locator('#sberPartsList')).to_contain_text('Клиент заплатил')
    expect(page.locator('#sberPartsList')).to_contain_text('Комиссия банка')
    expect(page.locator('#payinExtraList')).to_contain_text('Клиент заплатил')
    expect(page.locator('#payinExtraList')).to_contain_text('Комиссия банка')
    expect(page.locator('[name="payin_amount_rub"]')).to_have_value('98000.00')

    page.evaluate('''() => {
        sberReset();
        sberIncomesCache = [{uuid: 'unknown', kind: 'acquiring',
            amount_rub: 98000, gross_rub: null, fee_rub: null}];
        sberAddIncome('unknown');
    }''')
    expect(page.locator('#sberPartsList')).to_contain_text('Комиссия неизвестна')
    expect(page.locator('#sberPartsList')).not_to_contain_text('Клиент заплатил')
    assert not errors, errors


def test_custom_deal_create_edit_reload_preserves_money(ui):
    page, errors, _, base = ui
    page.locator('.nav-create-btn').click()
    expect(page.locator('#create')).to_be_visible()
    page.wait_for_load_state('networkidle')
    page.locator('#clientSearchInput').fill('QA Browser Client')
    choose(page, '#dealProductSelect', 'Кастомная — нестандартные валюты')
    expect(page.locator('#customDealSection')).to_be_visible()
    page.locator('#customPayinAmount').fill('1000')
    choose(page, '#customPayoutCurrency', 'USDT')
    page.locator('#customPayoutAmount').fill('970')
    with page.expect_response(lambda r: urlsplit(r.url).path == '/api/deals'
                              and r.request.method == 'POST') as saved:
        page.locator('#customDealSubmit').click()
    result = saved.value.json()
    assert saved.value.status == 201, result
    deal = result['deal']
    assert deal['profit_usdt'] == 30
    assert deal['client_name'] == 'QA Browser Client'
    page.locator('.nav-tab[data-section="deals"]').click()
    page.wait_for_load_state('networkidle')
    row = page.locator('#dealsTable tr').filter(has_text='QA Browser Client')
    expect(row).to_have_count(1)
    row.get_by_role('button', name='Детали', exact=True).click()
    expect(page.locator('#dealModal')).to_be_visible()
    page.locator('#dealModal').get_by_role('button', name='Редактировать', exact=True).click()
    expect(page.locator('#customPayoutAmount')).to_have_value('970')
    page.locator('#customPayoutAmount').fill('960')
    with page.expect_response(lambda r: urlsplit(r.url).path == f'/api/deals/{deal["id"]}'
                              and r.request.method == 'PUT') as edited:
        page.locator('#customDealSubmit').click()
    assert edited.value.status == 200, edited.value.text()
    page.reload()
    state = page.request.get(base + f'/api/deals/{deal["id"]}').json()['deal']
    assert state['profit_usdt'] == 40
    assert state['custom_payout_amount'] == 960
    db = A.get_session()
    try:
        assert db.query(A.Deal).filter_by(client_name='QA Browser Client').count() == 1
    finally:
        db.close()
    assert not errors, errors


def _seed_reimbursement_deals(monkeypatch, count=2):
    """Реальные строки временной БД, без исходящих уведомлений."""
    monkeypatch.setattr(A, '_notify_reimbursed', lambda *a, **kw: None)
    db = A.get_session()
    try:
        rows = [A.Deal(client_name=f'QA Возмещение {i}',
                       deal_type=A.DealType.PAY_IN,
                       payin_method=A.PayInMethod.CRYPTO_DIRECT,
                       payin_amount_usdt=120, payout_amount_thb=3000,
                       payout_source=A.PayOutSource.FOUNDER_PERSONAL,
                       payout_founder_name='QA Founder', needs_reimbursement=True,
                       status=A.DealStatus.PENDING) for i in range(count)]
        db.add_all(rows)
        db.commit()
        return [row.id for row in rows]
    finally:
        db.close()


@pytest.mark.parametrize('lost_response', [False, True])
def test_reimbursement_partial_allocation_and_repeat_preserve_money(ui, monkeypatch, lost_response):
    """Форма 80+пусто: двойной клик или повтор после потери ответа не удваивает расход."""
    page, errors, _, _ = ui
    ids = _seed_reimbursement_deals(monkeypatch)
    page.locator('.nav-tab[data-section="reimbursements"]').click()
    amount = page.locator('.reimburse-amount[data-founder="QA Founder"]')
    expect(amount).to_be_visible()
    amount.fill('100')
    page.locator(f'.reimburse-alloc[data-deal-id="{ids[1]}"]').fill('')
    page.locator(f'.reimburse-alloc[data-deal-id="{ids[0]}"]').fill('80')
    expect(page.locator('.reimburse-alloc-summary[data-founder="QA Founder"]')).to_contain_text(
        'распределится автоматически')
    button = page.locator('.reimburse-btn[data-founder="QA Founder"]')
    expect(button).to_be_enabled()
    if lost_response:
        committed = []

        def lose_first_response(route):
            if route.request.method == 'POST' and not committed:
                response = route.fetch()
                committed.append(response.status)
                route.abort('failed')
            else:
                route.continue_()

        page.route('**/api/reimbursements', lose_first_response)
        button.click()
        expect(page.locator('.toast-container')).to_contain_text('Ошибка сети')
        assert committed == [200]
        expect(button).to_be_enabled()
        with page.expect_response(lambda r: urlsplit(r.url).path == '/api/reimbursements'
                                  and r.request.method == 'POST') as retried:
            button.click()
        assert retried.value.status == 409
    else:
        with page.expect_response(lambda r: urlsplit(r.url).path == '/api/reimbursements'
                                  and r.request.method == 'POST') as saved:
            button.dblclick()
        assert saved.value.status == 200, saved.value.text()
    expect(page.locator('#pendingReimbursementsList')).to_contain_text('Нет сделок')
    page.reload()
    page.locator('.nav-tab[data-section="reimbursements"]').click()
    expect(page.locator('#pendingReimbursementsList')).to_contain_text('Нет сделок')
    expect(page.locator('#reimbursementsList')).to_contain_text('QA Founder')
    db = A.get_session()
    try:
        assert db.query(A.Reimbursement).count() == 1
        assert [db.get(A.Deal, deal_id).payout_amount_usdt for deal_id in ids] == [80, 20]
        assert len({db.get(A.Deal, deal_id).reimbursement_id for deal_id in ids}) == 1
    finally:
        db.close()
    assert not errors, errors


def test_reimbursement_prefill_rounding_and_shortfall_validation(ui, monkeypatch):
    """100 USDT на три сделки сохраняются целиком; неполный ручной разнос блокируется."""
    page, errors, _, _ = ui
    ids = _seed_reimbursement_deals(monkeypatch, count=3)
    page.locator('.nav-tab[data-section="reimbursements"]').click()
    amount = page.locator('.reimburse-amount[data-founder="QA Founder"]')
    expect(amount).to_be_visible()
    amount.fill('100')
    for deal_id, share in zip(ids, ('33.34', '33.33', '33.33')):
        expect(page.locator(f'.reimburse-alloc[data-deal-id="{deal_id}"]')).to_have_value(share)
    button = page.locator('.reimburse-btn[data-founder="QA Founder"]')
    first = page.locator(f'.reimburse-alloc[data-deal-id="{ids[0]}"]')
    first.fill('33.33')
    expect(button).to_be_disabled()
    expect(page.locator('.reimburse-alloc-summary[data-founder="QA Founder"]')).to_contain_text(
        'распределите всю сумму')
    first.fill('33.34')
    with page.expect_response(lambda r: urlsplit(r.url).path == '/api/reimbursements'
                              and r.request.method == 'POST') as saved:
        button.click()
    assert saved.value.status == 200, saved.value.text()
    db = A.get_session()
    try:
        assert sum(db.get(A.Deal, deal_id).payout_amount_usdt for deal_id in ids) == pytest.approx(100)
    finally:
        db.close()
    assert not errors, errors


def test_manual_payin_hashes_autofill_and_sum(ui):
    page, errors, _, _ = ui
    def lookup(route):
        h = route.request.url.split('hash=')[1].split('&')[0]
        route.fulfill(json={'success': True, 'amount_usdt': 125 if h.startswith('a') else 75})
    page.route('**/api/tx/lookup?*', lookup)
    page.route('**/api/payin-txs/*', lambda route: route.fulfill(status=404, json={'success': False}))
    page.evaluate("showSection('create')")
    field = page.locator('#payinManualHash')
    field.fill('a' * 64)
    field.dispatch_event('change')
    expect(page.locator('#payinTxPoolBox')).to_contain_text('125.00')
    field.fill('b' * 64)
    field.dispatch_event('change')
    expect(page.locator('#payinTxPoolBox')).to_contain_text('200.00')
    expect(page.locator('[name=payin_amount_usdt]')).to_have_value('200.00')
    assert not errors


@pytest.mark.parametrize('width', [1440, 390])
def test_reclassifies_old_founder_payout_through_existing_editor(ui, monkeypatch, tmp_path, width):
    from tests.test_leasehold_reclassification import seed_direct, snapshot

    page, errors, server_errors, _ = ui
    export_results = iter(({'ok': False}, {'ok': True}, {'ok': True}, {'ok': False}))
    monkeypatch.setattr(A, '_sync_reclassified_deal_gsheet', lambda deal: next(export_results))
    page.set_viewport_size({'width': width, 'height': 900})
    with A.get_session() as db:
        deal = seed_direct(db, reimbursed=True)
        deal.manager_name = 'QA Manager'
        deal.client_name = 'QA Leasehold'
        deal_id = deal.id
        db.commit()
        before = snapshot(db, deal_id)
    path = f'/api/deals/{deal_id}'
    writes = []
    page.on('request', lambda request: writes.append(request.post_data_json)
            if request.method == 'PUT' and request.url.endswith(path) else None)
    page.evaluate('id => openDealEditor(id)', deal_id)
    product = page.locator('#dealProductSelect')
    route = page.locator('#leaseholdPayoutRoute')
    drop = product.locator('..')
    drop_button = drop.locator('.custom-select-btn')
    notes = page.locator('#createDealForm [name=notes]')
    dialog = page.get_by_role('dialog')
    leasehold_label = 'Недвижимость лизхолд через личный счёт'
    expected_types = {'deal_kind': 'personal_realty', 'reclassify': True}

    def choose_visible(select, label):
        wrapper = select.locator('..')
        wrapper.locator('.custom-select-btn').click()
        choice = wrapper.locator('.custom-select-opt').get_by_text(label, exact=True)
        expect(choice).not_to_have_class(re.compile(r'\bdisabled\b'))
        choice.click()

    expect(page.locator('#payoutSource')).to_have_value('founder_personal')
    expect(drop_button).to_have_text('Обычная (обмен)')
    expect(product.locator('option[value=mf_freehold]')).to_be_disabled()
    expect(page.locator('#create .card-title').get_by_text('Изменить тип сделки', exact=True)).to_have_count(0)
    expect(page.locator('#leaseholdTypeHint')).to_be_visible()
    choose_visible(product, 'Обычная (обмен)')
    expect(dialog).to_have_count(0)
    assert not writes


    notes.fill('Несохранённое уточнение')
    choose_visible(product, leasehold_label)
    expect(page.get_by_text('Сначала сохраните изменения в полях сделки.', exact=True)).to_be_visible()
    expect(notes).to_have_value('Несохранённое уточнение')
    expect(drop_button).to_have_text('Обычная (обмен)')
    expect(dialog).to_have_count(0)
    assert not writes
    notes.clear()

    choose_visible(product, leasehold_label)
    expect(dialog).to_contain_text('Недвижимость лизхолд через личный счёт')
    expect(product).to_have_value('exchange')
    expect(drop_button).to_have_text('Обычная (обмен)')
    assert not writes
    dialog.get_by_role('button', name='Отмена', exact=True).click()
    expect(dialog).to_have_count(0)
    expect(drop_button).to_have_text('Обычная (обмен)')
    assert not writes

    def reject_put(intercept):
        if intercept.request.method == 'PUT':
            return intercept.fulfill(status=409, json={'success': False, 'error': 'Проверка отказа'})
        return intercept.fallback()

    page.route('**' + path, reject_put)
    choose_visible(product, leasehold_label)
    dialog.get_by_role('button', name='Изменить тип', exact=True).click()
    expect(page.get_by_text('Проверка отказа', exact=True)).to_be_visible()
    expect(drop_button).to_have_text('Обычная (обмен)')
    page.unroute('**' + path, reject_put)
    with A.get_session() as db:
        assert db.get(A.Deal, deal_id).deal_kind == 'exchange'
        assert snapshot(db, deal_id) == before

    def abort_put(intercept):
        if intercept.request.method == 'PUT':
            return intercept.abort()
        return intercept.fallback()

    page.route('**' + path, abort_put)
    choose_visible(product, leasehold_label)
    dialog.get_by_role('button', name='Изменить тип', exact=True).click()
    expect(page.get_by_text('Не удалось подтвердить смену типа. Повторите попытку.', exact=True)).to_be_visible()
    expect(drop_button).to_have_text('Обычная (обмен)')
    page.unroute('**' + path, abort_put)

    choose_visible(product, leasehold_label)
    with page.expect_response(lambda r: r.request.method == 'PUT' and r.url.endswith(path)) as change:
        dialog.get_by_role('button', name='Изменить тип', exact=True).click()
    assert change.value.json()['export_pending'] is True
    assert change.value.request.post_data_json == expected_types
    retry_export = page.locator('#leaseholdExportNotice').get_by_role('button', name='Повторить выгрузку')
    expect(retry_export).to_be_visible()
    expect(drop_button).to_have_text(leasehold_label)
    choose_visible(product, leasehold_label)
    expect(dialog).to_have_count(0)
    assert writes == [expected_types] * 3
    with page.expect_response(lambda r: r.request.method == 'PUT' and r.url.endswith(path)) as retry:
        retry_export.click()
    expect(retry_export).to_be_hidden()
    assert retry.value.json()['deal']['id'] == deal_id
    assert retry.value.request.post_data_json == expected_types
    assert writes == [expected_types] * 4

    expect(drop_button).to_have_text(leasehold_label)
    expect(drop_button).to_be_enabled()
    expect(product.locator('option[value=leasehold]')).to_be_enabled()
    expect(route.locator('option[value=personal_realty]')).to_be_enabled()
    expect(route.locator('option[value=ipps_realty]')).to_be_disabled()
    expect(route.locator('option[value=mf_realty]')).to_be_disabled()
    expect(route).to_have_value('personal_realty')
    expect(page.locator('#personalPayoutMode')).to_have_value('direct_conversion')
    expect(page.locator('#personalPayoutThb')).to_have_value('1125699')
    expect(page.locator('#personalCostUsdt')).to_have_value('34636.91')
    expect(page.locator('#payoutSettledByPayin')).to_be_checked()
    expect(page.locator('#create .card-title')).to_contain_text(f'#{deal_id}')
    page.screenshot(path=str(tmp_path / f'reclassified-{width}.png'), full_page=True)

    notes.fill('Уточнение по договору')
    save = page.get_by_role('button', name='Сохранить изменения', exact=True)
    with page.expect_response(lambda r: r.request.method == 'PUT' and r.url.endswith(path)) as edit:
        save.click()
    assert edit.value.status == 200, edit.value.text()
    assert edit.value.request.post_data_json == {'notes': 'Уточнение по договору'}
    page.locator('#dealModal').get_by_role('button', name='Редактировать', exact=True).click()
    expect(page.locator('#create .card-title')).to_contain_text(f'Редактировать сделку #{deal_id}')
    choose_visible(product, 'Обычная (обмен)')
    expect(dialog).to_contain_text('Обмен')
    expect(drop_button).to_have_text(leasehold_label)
    with page.expect_response(lambda r: r.request.method == 'PUT' and r.url.endswith(path)) as reverse:
        dialog.get_by_role('button', name='Изменить тип', exact=True).click()
    assert reverse.value.json()['deal']['id'] == deal_id
    assert reverse.value.request.post_data_json == {'deal_kind': 'exchange', 'reclassify': True}
    expect(drop_button).to_have_text('Обычная (обмен)')
    with A.get_session() as db:
        assert snapshot(db, deal_id) == before
        assert db.get(A.Deal, deal_id).notes == 'Уточнение по договору'
        assert db.get(A.Deal, deal_id).deal_kind == 'exchange'

    choose_visible(product, leasehold_label)
    with page.expect_response(lambda r: r.request.method == 'PUT' and r.url.endswith(path)) as pending:
        dialog.get_by_role('button', name='Изменить тип', exact=True).click()
    assert pending.value.json()['export_pending'] is True
    expect(retry_export).to_be_visible()
    with A.get_session() as db:
        # Another editor has already changed the saved type while this page shows the retry.
        db.get(A.Deal, deal_id).deal_kind = 'exchange'
        db.commit()
    previous_writes = writes.copy()
    retry_export.click()
    expect(retry_export).to_be_hidden()
    expect(drop_button).to_have_text('Обычная (обмен)')
    expect(page.get_by_text('Тип сделки уже изменился. Проверьте текущий тип.', exact=True)).to_be_visible()
    assert writes == previous_writes

    previous_writes = writes.copy()
    page.locator('#create .card-title').get_by_role('button', name='Отмена', exact=True).click()
    if width == 390:
        page.locator('#bottomNav').get_by_text('Создать', exact=True).click()
    else:
        page.locator('.nav-create-btn').first.click()
    choose_visible(product, 'Недвижимость лизхолд')
    expect(route).to_have_value('mf_realty')
    expect(page.locator('#mfDealSection')).to_be_visible()
    choose_visible(route, 'ИППС')
    expect(page.locator('#ippsDealSection')).to_be_visible()
    choose_visible(route, 'Личный счёт')
    expect(page.locator('#personalDealSection')).to_be_visible()
    mode = page.locator('#personalPayoutMode')
    expect(mode).to_have_value('direct_conversion')
    choose_visible(mode, 'Из остатка карты')
    expect(mode).to_have_value('bank_card')
    choose_visible(mode, 'Оплата по хэшу')
    expect(page.locator('#founderGroup')).to_be_visible()
    expect(dialog).to_have_count(0)
    assert writes == previous_writes
    assert not errors, errors
    assert not server_errors, server_errors


@pytest.mark.parametrize('width', [1440, 390])
def test_deal_details_show_unique_proofs_and_keep_channel_amounts(ui, width):
    page, errors, server_errors, _ = ui
    page.set_viewport_size({'width': width, 'height': 844})
    # Capture clipboard writes inside the page instead of using the host pasteboard.
    page.evaluate("""() => Object.defineProperty(navigator, 'clipboard', {
        configurable: true, value: {writeText: async value => {window.__qaCopiedProof = value;}}
    })""")
    first_hash = '1' * 64
    extra_hash = '0x' + '2' * 64
    payout_hash = '0x' + '3' * 64
    legacy_hash = '4' * 64
    shared_raw_hash = '5' * 64
    legacy_extra_hash = '6' * 64

    def transfer(hash_value, network, amount):
        return {'hash': hash_value, 'network': network, 'amount_usdt': amount}

    def channel(amount, *proofs):
        return {'method': 'crypto_direct', 'amount_usdt': amount, 'tx_hashes': list(proofs)}

    def saved_deal(db, *, total=100, scalar=None, proofs=(), extra=(), verified=False, payout=None):
        record = A.Deal(
            deal_type=A.DealType.PAY_IN, deal_kind='personal_realty' if payout else 'exchange',
            status=A.DealStatus.COMPLETED, payin_method=A.PayInMethod.CRYPTO_DIRECT,
            payin_amount_usdt=total, payin_tx_hash=scalar, payin_tx_verified=verified,
            payin_tx_hashes=json.dumps(proofs) if proofs else None,
            payin_extra=json.dumps(extra) if extra else None,
            payout_source=A.PayOutSource.FOUNDER_PERSONAL if payout else None,
            payout_method=A.PayOutMethod.TRANSFER,
            payout_amount_thb=1170544.91 if payout else 3300,
            payout_amount_usdt=34636.91 if payout else 100,
            payout_founder_name='Теодор' if payout else None,
            payout_tx_hash=payout['hash'] if payout else None,
            payout_tx_hashes=json.dumps([payout]) if payout else None,
            needs_reimbursement=False,
        )
        db.add(record)
        db.flush()
        return record.id

    with A.get_session() as db:
        separated = saved_deal(
            db, total=35675.17, scalar=first_hash, verified=True,
            proofs=[transfer(first_hash, 'trc20', 35028.20), transfer(extra_hash, 'erc20', 646.97)],
            extra=[channel(646.97, transfer(extra_hash, 'erc20', 646.97))],
            payout=transfer(payout_hash, 'erc20', 34636.91))
        multi_main = saved_deal(
            db, scalar=first_hash,
            proofs=[transfer(first_hash, 'trc20', 60), transfer(extra_hash, 'erc20', 40)])
        same_hash_shares = saved_deal(
            db, scalar=extra_hash, verified=True,
            proofs=[transfer(first_hash, 'trc20', 40), transfer(extra_hash, 'erc20', 60)],
            extra=[channel(35, transfer(extra_hash, 'erc20', 35)),
                   channel(25, transfer(extra_hash, 'erc20', 25))])
        legacy_only = saved_deal(db, scalar=legacy_hash)
        legacy_distinct = saved_deal(
            db, scalar=legacy_hash, verified=True,
            proofs=[transfer(first_hash, 'trc20', 60)],
            extra=[channel(40, transfer(extra_hash, 'erc20', 40))])
        mixed_same_raw_hash = saved_deal(
            db, scalar=first_hash,
            proofs=[transfer(first_hash, 'trc20', 30), transfer(shared_raw_hash, 'trc20', 45)],
            extra=[channel(25, transfer(shared_raw_hash, 'erc20', 25))])
        canonical_proof = 'ab' * 32
        legacy_alias = saved_deal(
            db, scalar=canonical_proof.upper(), verified=True,
            proofs=[transfer(canonical_proof, 'trc20', 100)])
        structured_only = saved_deal(db, proofs=[transfer(extra_hash, 'erc20', 100)])
        legacy_extra = saved_deal(
            db, scalar=first_hash,
            proofs=[transfer(first_hash, 'trc20', 60), transfer(extra_hash, 'erc20', 25)],
            extra=[{'method': 'crypto_direct', 'amount_usdt': 15, 'tx_hash': legacy_extra_hash},
                   {'method': 'crypto_direct', 'amount_usdt': 25, 'tx_hash': extra_hash}])
        legacy_extra_only = saved_deal(
            db, scalar=legacy_extra_hash, proofs=[legacy_extra_hash],
            extra=[{'method': 'crypto_direct', 'amount_usdt': 100, 'tx_hash': legacy_extra_hash}])
        without_hash = saved_deal(db)
        db.commit()

    modal = page.locator('#dealModal')
    content = page.locator('#dealModalContent')
    tron = 'https://tronscan.org/#/transaction/'
    eth = 'https://etherscan.io/tx/'

    def show(deal_id):
        page.evaluate('id => showDealDetails(id)', deal_id)
        expect(modal).to_be_visible()
        expect(content).to_contain_text(f'#{deal_id}')

    show(separated)
    expect(content).to_contain_text('Приход по каналам (2)')
    expect(content).to_contain_text(re.compile(r'35[\s,]?675[.,]17'))
    expect(content).to_contain_text(re.compile(r'35[\s,]?028[.,]20'))
    expect(content).to_contain_text(re.compile(r'646[.,]97'))
    expect(content).to_contain_text('Конвертация для выплаты · исходящий USDT')
    expect(content).to_contain_text(re.compile(r'−\$?34[\s,]?636[.,]91 USDT'))
    expect(content.locator(f'a[href="{tron + first_hash}"]')).to_have_count(1)
    expect(content.locator(f'a[href="{eth + extra_hash}"]')).to_have_count(1)
    expect(content.locator(f'a[href="{eth + payout_hash}"]')).to_have_count(1)
    expect(content.locator('[title="Подтверждено"]')).to_have_count(1)
    for source_hash in (first_hash, extra_hash, payout_hash):
        copy_button = content.locator(f'button[data-proof-hash="{source_hash}"]')
        expect(copy_button).to_be_visible()
        copy_button.click()
        assert page.evaluate('window.__qaCopiedProof') == source_hash
    assert content.evaluate("""el => [...el.querySelectorAll('button[data-proof-hash]')]
        .every(button => button.parentElement.scrollWidth <= button.parentElement.clientWidth + 1)""")

    show(multi_main)
    expect(content).to_contain_text('Хэши прихода')
    expect(content.locator(f'a[href="{tron + first_hash}"]')).to_have_count(1)
    expect(content.locator(f'a[href="{eth + extra_hash}"]')).to_have_count(1)
    expect(content.locator('[title="Ожидает подтверждения"]')).to_have_count(1)

    show(same_hash_shares)
    expect(content.locator(f'a[href="{eth + extra_hash}"]')).to_have_count(1)
    expect(content).to_contain_text(re.compile(r'\+\$35[.,]00'))
    expect(content).to_contain_text(re.compile(r'\+\$25[.,]00 · Тот же перевод, что в приходе 2'))
    expect(content).to_contain_text('Приход по каналам (3)')
    expect(content.locator('[title="Подтверждено"]')).to_have_count(1)

    show(legacy_only)
    expect(content.locator(f'a[href="{tron + legacy_hash}"]')).to_have_count(1)
    expect(content.locator('button[data-proof-hash]')).to_have_count(1)

    show(legacy_distinct)
    expect(content.locator(f'a[href="{tron + first_hash}"]')).to_have_count(1)
    expect(content.locator(f'a[href="{eth + extra_hash}"]')).to_have_count(1)
    expect(content.locator(f'a[href="{tron + legacy_hash}"]')).to_have_count(1)

    show(mixed_same_raw_hash)
    expect(content.locator(f'a[href="{tron + shared_raw_hash}"]')).to_have_count(1)
    expect(content.locator(f'a[href="{eth + shared_raw_hash}"]')).to_have_count(1)
    expect(content).to_contain_text(re.compile(r'\+\$45[.,]00'))
    expect(content).to_contain_text(re.compile(r'\+\$25[.,]00'))

    show(legacy_alias)
    expect(content.locator(f'a[href="{tron + canonical_proof}"]')).to_have_count(1)
    expect(content.locator(f'a[href="{tron + canonical_proof.upper()}"]')).to_have_count(0)
    expect(content.locator('[title="Подтверждено"]')).to_have_count(1)

    show(structured_only)
    expect(content.locator(f'a[href="{eth + extra_hash}"]')).to_have_count(1)

    show(without_hash)
    expect(content.locator('button[data-proof-hash]')).to_have_count(0)
    expect(content).not_to_contain_text('Хэш прихода')

    show(legacy_extra)
    expect(content).to_contain_text('Приход по каналам (3)')
    expect(content.locator(f'a[href="{tron + legacy_extra_hash}"]').locator('..')).to_contain_text('+$15.00')
    expect(content.locator(f'a[href="{eth + extra_hash}"]')).to_have_count(1)
    expect(content.locator(f'a[href="{eth + extra_hash}"]').locator('..')).to_contain_text('+$25.00')
    modal.get_by_role('button', name='Редактировать', exact=True).click()
    expect(page.locator('#pe-1-usdt')).to_have_value('25')
    payload = page.evaluate("serializeStandardDeal(document.getElementById('createDealForm'))")
    assert payload['payin_tx_hashes'] == [transfer(first_hash, 'trc20', 60)]
    assert [part['tx_hashes'] for part in payload['payin_extra']] == [
        [transfer(legacy_extra_hash, 'trc20', 15)], [transfer(extra_hash, 'erc20', 25)],
    ]

    show(legacy_extra_only)
    expect(content.locator(f'a[href="{tron + legacy_extra_hash}"]')).to_have_count(1)
    modal.get_by_role('button', name='Редактировать', exact=True).click()
    expect(page.locator('#pe-0-usdt')).to_have_value('100')
    page.locator('#payinExtraList button[onclick="payinExtraRemove(0)"]').click()
    payload = page.evaluate("serializeStandardDeal(document.getElementById('createDealForm'))")
    assert payload['payin_extra'] == []
    assert payload['payin_tx_hashes'] == []
    assert payload['payin_tx_hash'] is None
    assert not errors, errors
    assert not server_errors, server_errors


@pytest.mark.parametrize('width', [1440, 390, 375])
def test_exchange_deal_details_and_editor_use_all_transfers(ui, width, tmp_path):
    page, errors, server_errors, _ = ui
    page.set_viewport_size({'width': width, 'height': 844})
    page.evaluate("""() => Object.defineProperty(navigator, 'clipboard', {
        configurable: true, value: {writeText: async value => {window.__qaCopiedProof = value;}}
    })""")

    incoming = [
        {'hash': 'a' * 64, 'network': 'trc20', 'amount_usdt': 800},
        {'hash': '0x' + 'b' * 64, 'network': 'erc20', 'amount_usdt': 100},
    ]
    payout_amounts = ['40.00', '55.00', '104.00', '589.00', '4.351249', '4.385673', '4.327359']
    outgoing = [
        {'hash': ('0x' if i == 7 else '') + str(i) * 64,
         'network': 'erc20' if i == 7 else 'trc20', 'amount_usdt': float(amount)}
        for i, amount in enumerate(payout_amounts, 1)
    ]
    legacy_hash = '8' * 64
    legacy_erc_hash = '0x' + '9' * 64

    with A.get_session() as db:
        def saved_deal(name, **fields):
            deal = A.Deal(
                deal_type=A.DealType.PAY_IN, deal_kind='exchange', client_name=name,
                status=A.DealStatus.COMPLETED, payin_method=A.PayInMethod.CRYPTO_DIRECT,
                payout_method=A.PayOutMethod.TRANSFER, payout_source=A.PayOutSource.FOUNDER_PERSONAL,
                payout_founder_name='Андрей', payout_amount_thb=27000, payout_amount_usdt=801.06, **fields,
            )
            db.add(deal)

        saved_deal(
            'QA Multiple Transfers', payin_amount_usdt=900, payin_tx_hash=incoming[0]['hash'],
            profit_usdt=98.94, net_profit_usdt=98.94, profit_percent=12.35,
            payin_tx_hashes=json.dumps(incoming),
            payin_extra=json.dumps([{'method': 'crypto_direct', 'amount_usdt': 100, 'tx_hashes': [incoming[1]]}]),
            payout_tx_hash=outgoing[0]['hash'], payout_tx_hashes=json.dumps(outgoing),
        )
        saved_deal('QA Legacy Payout TRC', payout_tx_hash=legacy_hash)
        saved_deal('QA Legacy Payout ERC', payout_tx_hash=legacy_erc_hash)
        saved_deal('QA No Conversion', payout_tx_hash=legacy_hash, payout_no_conversion=True)
        saved_deal('QA Custom Payout', is_custom=True, custom_payin_currency='USDT', custom_payin_amount=900,
                   custom_payout_currency='THB', custom_payout_amount=27000,
                   payout_tx_hashes=json.dumps([outgoing[0], outgoing[-1]]))
        db.commit()

    if width < 641:
        page.locator('#bottomNav').get_by_role('button', name='Сделки').click()
    else:
        page.locator('.nav-tab[data-section="deals"]').click()
    modal = page.locator('#dealModal')
    content = modal.locator('#dealModalContent')
    tron = 'https://tronscan.org/#/transaction/'
    eth = 'https://etherscan.io/tx/'

    def show(name):
        page.locator('#dealsTable tr').filter(has_text=name).get_by_role('button', name='Детали').click()
        expect(modal).to_be_visible()

    def proof_link(transfer):
        explorer = eth if transfer['network'] == 'erc20' else tron
        return content.locator(f'a[href="{explorer + transfer["hash"]}"]')

    for network, explorer, tx_hash in [('TRC', tron, legacy_hash), ('ERC', eth, legacy_erc_hash)]:
        show(f'QA Legacy Payout {network}')
        expect(content.locator(f'a[href="{explorer + tx_hash}"]')).to_have_count(1)
        expect(content.locator('button[data-proof-hash]')).to_have_count(1)
        modal.locator('.modal-close').click()

    show('QA No Conversion')
    expect(content).to_contain_text('Выдано своими батами')
    expect(content.locator('button[data-proof-hash]')).to_have_count(0)
    modal.locator('.modal-close').click()

    show('QA Custom Payout')
    expect(proof_link(outgoing[0])).to_have_count(1)
    expect(proof_link(outgoing[-1])).to_have_count(1)
    modal.locator('.modal-close').click()

    show('QA Multiple Transfers')
    expect(content).to_contain_text('Приход по каналам (2)')
    expect(content).to_contain_text('Хэши выплаты (7)')
    expect(content).to_contain_text('Стоимость USDT: $801.06')
    expect(content.locator('button[data-proof-hash]')).to_have_count(9)
    for transfer in incoming:
        expect(proof_link(transfer)).to_have_count(1)
        expect(proof_link(transfer).locator('..')).to_contain_text(f'+${transfer["amount_usdt"]:.2f}')
    for transfer, amount in zip(outgoing, payout_amounts):
        link = proof_link(transfer)
        expect(link).to_have_count(1)
        expect(link.locator('xpath=../..')).to_contain_text(f'−${amount} USDT')
    assert content.evaluate("""el => el.scrollWidth <= el.clientWidth + 1 &&
        [...el.querySelectorAll('.outgoing-proof-link')].every(group => {
            const link = group.querySelector('a').getBoundingClientRect();
            const copy = group.querySelector('button').getBoundingClientRect();
            return Math.abs(link.top - copy.top) < 8 && group.scrollWidth <= group.clientWidth + 1;
        })""")
    proof_link(outgoing[-1]).scroll_into_view_if_needed()
    page.screenshot(path=str(tmp_path / 'deal-payout-proofs.png'))

    for transfer in outgoing:
        proof_link(transfer).locator('..').get_by_role('button', name='Скопировать хэш').click()
        assert page.evaluate('window.__qaCopiedProof') == transfer['hash']

    modal.get_by_role('button', name='Редактировать', exact=True).click()
    profit = page.locator('#profitUsdt')
    cost = page.locator('#cashBatchCostUsdt')
    payouts = page.locator('#payoutTxPoolBox')
    expect(payouts.get_by_title('сколько из перевода идёт в эту сделку')).to_have_count(7)
    expect(cost).to_have_value('$801.06')
    expect(profit).to_have_value('98.94')
    serialized_proofs = page.evaluate("serializeStandardDeal(document.getElementById('createDealForm')).payout_tx_hashes")
    assert [(tx['hash'], tx['network']) for tx in serialized_proofs] == [(tx['hash'], tx['network']) for tx in outgoing]
    page.locator('#pe-0-usdt').fill('125')
    expect(page.locator('#payinExtraSummary')).to_contain_text('$925.00')
    expect(profit).to_have_value('123.94')
    payouts.get_by_title('сколько из перевода идёт в эту сделку').last.fill('5.33')
    expect(cost).to_have_value('$802.07')
    expect(profit).to_have_value('122.93')
    page.locator('#payinExtraList button[onclick="payinExtraRemove(0)"]').click()
    expect(page.locator('#payinExtraSummary')).to_be_empty()
    expect(profit).to_have_value('-2.07')
    payouts.get_by_role('button', name='✕').last.click()
    expect(cost).to_have_value('$796.74')
    expect(profit).to_have_value('3.26')
    assert not errors, errors
    assert not server_errors, server_errors


@pytest.mark.parametrize('width', [1440, 390])
def test_saved_shared_payin_hydration_preserves_editor_values(ui, monkeypatch, width):
    from tests.test_leasehold_reclassification import seed_direct, snapshot

    page, errors, server_errors, _ = ui
    monkeypatch.setattr(A, '_sync_reclassified_deal_gsheet', lambda deal: {'ok': True})
    page.set_viewport_size({'width': width, 'height': 900})
    with A.get_session() as db:
        deal = seed_direct(db)
        deal.manager_name = 'QA Manager'
        deal.payin_method = A.PayInMethod.SPP_DOVERKA
        deal.payin_amount_rub = 280188.11
        deal.payin_amount_usdt = 3137.64
        deal.payin_rate_rub_usdt = 89.31
        deal.payout_amount_thb = 100000
        deal.payout_amount_usdt = 2997.15
        db.flush()
        outgoing = db.query(A.PayoutTxUse).filter_by(deal_id=deal.id).one()
        outgoing.amount_usdt = 2997.15
        deal.payout_tx_hashes = json.dumps([
            {'hash': outgoing.tx.tx_hash, 'network': 'erc20', 'amount_usdt': 2997.15},
        ])
        incoming = db.query(A.PayinTxUse).filter_by(deal_id=deal.id).order_by(A.PayinTxUse.id).all()
        first_use, second_use = incoming
        payin_hash = first_use.tx.tx_hash
        first_use.amount_usdt = 3137.64
        first_use.tx.amount_usdt = 4200
        first_use.tx.source = 'tronscan'
        db.delete(second_use)
        deal.payin_tx_hashes = json.dumps([
            {'hash': payin_hash, 'network': 'trc20', 'amount_usdt': 3137.64},
        ])
        other = A.Deal(deal_type=A.DealType.PAY_IN, deal_kind='exchange',
                       payin_method=A.PayInMethod.SPP_DOVERKA, payin_amount_usdt=712.36,
                       payin_tx_hash=payin_hash, payin_tx_hashes=json.dumps([
                           {'hash': payin_hash, 'network': 'trc20', 'amount_usdt': 712.36},
                       ]), manager_name='QA Manager')
        db.add(other)
        db.flush()
        db.add(A.PayinTxUse(tx=first_use.tx, deal_id=other.id, amount_usdt=712.36))
        deal_id, other_id = deal.id, other.id
        db.commit()
        before = snapshot(db, deal_id)

    payin_path = '/api/payin-txs/' + payin_hash
    held = []
    page.route('**' + payin_path, lambda intercept: held.append(intercept))
    writes = []
    page.on('request', lambda request: writes.append(request.post_data_json)
            if request.method == 'PUT' and request.url.endswith(f'/api/deals/{deal_id}') else None)
    rate = page.locator('#createDealForm [name=payin_rate_rub_usdt]')
    rub = page.locator('#createDealForm [name=payin_amount_rub]')
    usdt = page.locator('#createDealForm [name=payin_amount_usdt]')
    pool = page.locator('#payinTxPoolBox')
    share = pool.locator('input')
    product = page.locator('#dealProductSelect').locator('..')
    manual_hash = page.locator('#payinManualHash')
    dialog = page.get_by_role('dialog')

    def select_leasehold():
        product.locator('.custom-select-btn').click()
        product.locator('.custom-select-opt').get_by_text(
            'Недвижимость лизхолд через личный счёт', exact=True
        ).click()

    def open_editor(record_id=deal_id):
        with page.expect_request(lambda r: r.url.endswith(payin_path)):
            page.evaluate('id => openDealEditor(id)', record_id)

    def finish_ledger_request(intercept):
        with page.expect_event('requestfinished', lambda r: r.url.endswith(payin_path)):
            intercept.continue_()

    open_editor()
    expect(rate).to_have_value('89.31')
    finish_ledger_request(held.pop(0))
    expect(pool).to_contain_text(re.compile(r'остаток \$350[.,]00'))
    expect(pool).to_contain_text(f'сделки #{other_id}')
    expect(rate).to_have_value('89.31')
    expect(rub).to_have_value('280188.11')
    expect(usdt).to_have_value('3137.64')
    expect(share).to_have_value('3137.64')
    manual_requests = []
    page.route('**/api/tx/lookup?hash=a1b2c3*', lambda intercept: manual_requests.append(intercept))
    saved_manual_hash = manual_hash.input_value()
    manual_hash.fill('a1b2c3')
    select_leasehold()
    expect(dialog).to_have_count(0)
    expect(manual_hash).to_have_value('a1b2c3')
    assert not writes
    manual_hash.fill(saved_manual_hash)
    for request in manual_requests:
        request.abort()
    page.wait_for_function("() => typeof pendingManualPayinHash === 'undefined' || !pendingManualPayinHash")

    select_leasehold()
    expect(dialog).to_be_visible()
    manual_hash.evaluate("input => { input.value = 'a1b2c3'; }")
    dialog.get_by_role('button', name='Изменить тип', exact=True).click()
    expect(dialog).to_have_count(0)
    expect(manual_hash).to_have_value('a1b2c3')
    assert not writes
    manual_hash.fill(saved_manual_hash)

    select_leasehold()
    expect(dialog).to_contain_text('Недвижимость лизхолд через личный счёт')
    dialog.get_by_role('button', name='Отмена', exact=True).click()
    assert not writes

    open_editor()
    rate.fill('90.91')
    expect(rate).to_have_value('90.91')
    edited_amount = usdt.input_value()
    finish_ledger_request(held.pop(0))
    expect(pool).to_contain_text(re.compile(r'остаток \$350[.,]00'))
    expect(rate).to_have_value('90.91')
    expect(usdt).to_have_value(edited_amount)
    select_leasehold()
    expect(page.get_by_text('Сначала сохраните изменения в полях сделки.', exact=True).last).to_be_visible()
    expect(dialog).to_have_count(0)

    open_editor()
    share.fill('3120,50')
    finish_ledger_request(held.pop(0))
    page.wait_for_function('hash => Boolean(payinTxLedger[hash])', arg=payin_hash)
    expect(share).to_be_focused()
    expect(share).to_have_value('3120,50')
    expect(usdt).to_have_value('3120.50')
    rate.focus()
    expect(pool).to_contain_text(re.compile(r'остаток \$350[.,]00'))
    expect(usdt).to_have_value('3120.50')

    open_editor()
    share.focus()
    finish_ledger_request(held.pop(0))
    page.wait_for_function('hash => Boolean(payinTxLedger[hash])', arg=payin_hash)
    pool.get_by_role('button', name='✕', exact=True).click()
    expect(share).to_have_count(0)

    open_editor()
    open_editor(other_id)
    finish_ledger_request(held.pop(0))
    expect(pool).not_to_contain_text(re.compile(r'остаток \$350[.,]00'))
    expect(usdt).to_have_value('712.36')
    finish_ledger_request(held.pop(0))
    expect(pool).to_contain_text(re.compile(r'остаток \$350[.,]00'))

    open_editor()
    page.locator('#create .card-title').get_by_role('button', name='Отмена', exact=True).click()
    page.evaluate("showSection('create')")
    finish_ledger_request(held.pop(0))
    expect(share).to_have_count(0)
    expect(usdt).to_have_value('')
    assert not writes

    open_editor()
    finish_ledger_request(held.pop(0))
    expect(pool).to_contain_text(re.compile(r'остаток \$350[.,]00'))
    select_leasehold()
    expect(dialog).to_contain_text('Недвижимость лизхолд через личный счёт')
    with page.expect_response(lambda r: r.request.method == 'PUT'
                              and r.url.endswith(f'/api/deals/{deal_id}')) as reply:
        dialog.get_by_role('button', name='Изменить тип', exact=True).click()
    assert reply.value.status == 200
    assert writes == [{'deal_kind': 'personal_realty', 'reclassify': True}]
    with A.get_session() as db:
        assert db.get(A.Deal, deal_id).deal_kind == 'personal_realty'
        assert snapshot(db, deal_id) == before
    assert not errors, errors
    assert not server_errors, server_errors
