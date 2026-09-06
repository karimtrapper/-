"""Реальный Chromium + Flask + временная SQLite. Внешние сервисы — фикстуры.

Запуск: python3 -m pytest tests/test_browser_crm.py --browser -v
Без --browser явно SKIPPED, отсутствие Chromium при --browser — ERROR.
"""
import json
import threading
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server

import app as A

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
        browser = p.chromium.launch()
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


def test_custom_deal_create_edit_reload_preserves_money(ui):
    page, errors, _, base = ui
    page.locator('.nav-create-btn').click()
    expect(page.locator('#create')).to_be_visible()
    page.wait_for_load_state('networkidle')
    page.locator('#clientSearchInput').fill('QA Browser Client')
    choose(page, '#dealKindSelect', 'Кастомная — нестандартные валюты')
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
