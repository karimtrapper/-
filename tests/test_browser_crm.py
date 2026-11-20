"""Реальный Chromium + Flask + временная SQLite. Внешние сервисы — фикстуры.

Запуск: python3 -m pytest tests/test_browser_crm.py --browser -v
Без --browser явно SKIPPED, отсутствие Chromium при --browser — ERROR.
"""
import json
import re
import threading
from pathlib import Path
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
    A.Base.metadata.create_all(A.engine)
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
def chromium(pytestconfig):
    with sync_playwright() as p:
        executable = pytestconfig.getoption('--chromium-executable')
        browser = (p.chromium.launch(executable_path=executable) if executable else
                   p.chromium.launch() if Path(p.chromium.executable_path).exists()
                   else p.chromium.launch(channel='chrome'))
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


SHELL_SECTIONS = [
    ('deals', 'loadDeals', '#dealsTable'),
    ('documents', 'loadDocuments', '#docsList'),
    ('closing', 'loadBitrixDeals', '#bitrixDealsList'),
    ('exchangers', 'rxLoad', '#rxSummary'),
    ('balance', 'switchBalanceSubTab', '#walletsSummaryGrid'),
    ('incomes', 'loadIncomes', '#incomesTable'),
    ('conversions', 'loadConversions', '#conversionsTable'),
    ('reimbursements', 'loadReimbursements', '#reimbursementsList'),
    ('transactions', 'loadTransactions', '#walletsInfo'),
    ('managers', 'loadManagers', '#managersList'),
    ('verification', 'loadVerificationSummary', '#verificationSummary'),
    ('kyc', 'loadKYCSection', '#kycPendingList'),
    ('partners', 'loadPartners', '#partnersList'),
    ('referrers', 'loadReferrers', '#referrersList'),
    ('payoutRequests', 'loadPayoutRequests', '#payoutRequestsList'),
    ('admins', 'loadStandRoles', '#adminsList'),
]


@pytest.fixture
def stand_ui(chromium, crm_server, monkeypatch):
    """Настоящая панель стенда и реальные локальные API на SQLite."""
    monkeypatch.setattr(A, 'STAND_MODE', True)
    monkeypatch.setattr(A, '_tronscan_fetch_incoming', lambda *a, **k: ([], [], []))
    monkeypatch.setattr(A.stand_notify, 'notify_profile', lambda: 'disabled')
    monkeypatch.setattr(A.stand_notify, 'mode', lambda: 'all')
    db = A.get_session()
    db.add(A.Deal(client_name='QA Deal Client', deal_type=A.DealType.PAY_IN,
                  payin_amount_usdt=100, payout_amount_usdt=97))
    db.add(A.Wallet(address='TQA_LOCAL_WALLET', label='QA Wallet', is_balance=True))
    db.add(A.Agreement(client_name='QA Document Client', client_key='991122',
                       route_key='RUB_THB:bank', deal_type='leasehold',
                       number='MF-QA-1', status='signed'))
    db.commit()
    db.close()
    base, cookie = crm_server
    context = chromium.new_context(viewport={'width': 1440, 'height': 900})
    context.add_cookies([{'name': 'session', 'value': cookie, 'url': base,
                         'httpOnly': True, 'sameSite': 'Lax'}])
    context.route('**/*', lambda route: route.continue_()
                  if urlsplit(route.request.url).hostname == '127.0.0.1'
                  else route.abort())
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(base + '/crm?section=deals')
    expect(page.locator('.site-shell-section-list')).to_be_visible()
    yield page, errors
    context.close()


@pytest.mark.parametrize('section,loader,rendered', SHELL_SECTIONS)
def test_shared_section_click_loads_and_renders(stand_ui, section, loader, rendered):
    page, errors = stand_ui
    # Observe the real loader while leaving its fetch and rendering intact.
    page.evaluate('''loader => {
        window.__sectionLoaderCalls = 0;
        const original = window[loader];
        if (typeof original !== 'function') throw Error('Missing loader: ' + loader);
        window[loader] = function(...args) {
            window.__sectionLoaderCalls++;
            return original.apply(this, args);
        };
    }''', loader)
    responses = []
    page.on('response', lambda response: responses.append(response)
            if '/api/' in response.url else None)
    page.locator(f'.site-shell-section-list [data-shell-section="{section}"]').click()
    expect(page.locator(f'#{section}')).to_be_visible()
    page.wait_for_load_state('networkidle')
    assert page.evaluate('window.__sectionLoaderCalls') == 1, section
    assert responses, f'{section}: loader made no API request'
    assert not [r for r in responses if r.status >= 500], [
        (r.status, r.url) for r in responses if r.status >= 500]
    assert page.locator(rendered).inner_text().strip(), f'{section}: no rendered data or empty state'
    assert not errors, errors
    if section == 'documents':
        assert any(urlsplit(r.url).path == '/api/docs/agreements' and r.status == 200
                   for r in responses)
        expect(page.locator('#docsList')).to_contain_text('QA Document Client')
        assert not page.locator('#docsList').get_by_text('Загрузка…').count()
    if section == 'deals':
        expect(page.locator('#dealsTable')).to_contain_text('QA Deal Client')
    if section == 'managers':
        expect(page.locator('#managersList')).to_contain_text('QA Manager')
    if section == 'verification':
        expect(page.locator('#verificationSummary')).to_contain_text('Всего сделок')
        expect(page.locator('#verificationSummary .stat-value').first).to_have_text('1')


@pytest.mark.parametrize('section,path', [('tasks', '/tasks'),
                                          ('analytics', '/tasks?section=analytics')])
def test_shared_section_click_opens_task_pages(stand_ui, section, path):
    page, errors = stand_ui
    page.locator(f'.site-shell-section-list [data-shell-section="{section}"]').click()
    expect(page).to_have_url(re.compile(re.escape(path) + '$'))
    expect(page.locator(f'.site-shell-section-list [data-shell-section="{section}"]')).to_have_attribute(
        'aria-current', 'page')
    assert not errors, errors


@pytest.mark.parametrize('section,path', [
    ('documents', '/api/docs/agreements'), ('conversions', '/api/conversions'),
    ('incomes', '/api/sber-incomes'), ('closing', '/api/bitrix/active-deals')])
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
    page.locator('.nav-tab[data-section="deals"]').click()
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
    # Строка — сама ссылка, отдельной кнопки «Детали» больше нет (находка
    # №15 аудита ui-2026-10-17: DESIGN.md запрещает кнопку «Открыть» в строке).
    row.click()
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


@pytest.mark.parametrize('width', [1440, 390])
def test_reclassifies_old_founder_payout_through_existing_editor(ui, monkeypatch, tmp_path, width):
    from tests.test_leasehold_reclassification import seed_direct, snapshot

    page, errors, server_errors, _ = ui
    export_results = iter(({'ok': False}, {'ok': True}, {'ok': True}))
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

    notes.fill('Несохранённое уточнение')
    choose_visible(product, 'Недвижимость лизхолд')
    expect(page.get_by_text('Сначала сохраните изменения в полях сделки.', exact=True)).to_be_visible()
    expect(notes).to_have_value('Несохранённое уточнение')
    expect(drop_button).to_have_text('Обычная (обмен)')
    expect(dialog).to_have_count(0)
    assert not writes
    notes.clear()

    choose_visible(product, 'Недвижимость лизхолд')
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
    choose_visible(product, 'Недвижимость лизхолд')
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
    choose_visible(product, 'Недвижимость лизхолд')
    dialog.get_by_role('button', name='Изменить тип', exact=True).click()
    expect(page.get_by_text('Не удалось подтвердить смену типа. Повторите попытку.', exact=True)).to_be_visible()
    expect(drop_button).to_have_text('Обычная (обмен)')
    page.unroute('**' + path, abort_put)

    choose_visible(product, 'Недвижимость лизхолд')
    with page.expect_response(lambda r: r.request.method == 'PUT' and r.url.endswith(path)) as change:
        dialog.get_by_role('button', name='Изменить тип', exact=True).click()
    assert change.value.json()['export_pending'] is True
    assert change.value.request.post_data_json == expected_types
    expect(page.get_by_role('button', name='Повторить выгрузку')).to_be_visible()
    expect(drop_button).to_have_text('Обычная (обмен)')
    with page.expect_response(lambda r: r.request.method == 'PUT' and r.url.endswith(path)) as retry:
        choose_visible(product, 'Недвижимость лизхолд')
    assert retry.value.json()['deal']['id'] == deal_id
    assert retry.value.request.post_data_json == expected_types
    assert writes == [expected_types] * 4

    expect(drop_button).to_have_text('Недвижимость лизхолд')
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
    expect(drop_button).to_have_text('Недвижимость лизхолд')
    with page.expect_response(lambda r: r.request.method == 'PUT' and r.url.endswith(path)) as reverse:
        dialog.get_by_role('button', name='Изменить тип', exact=True).click()
    assert reverse.value.json()['deal']['id'] == deal_id
    assert reverse.value.request.post_data_json == {'deal_kind': 'exchange', 'reclassify': True}
    expect(drop_button).to_have_text('Обычная (обмен)')
    with A.get_session() as db:
        assert snapshot(db, deal_id) == before
        assert db.get(A.Deal, deal_id).notes == 'Уточнение по договору'
        assert db.get(A.Deal, deal_id).deal_kind == 'exchange'

    previous_writes = writes.copy()
    page.locator('#create .card-title').get_by_role('button', name='Отмена', exact=True).click()
    if width == 390:
        page.locator('#bottomNav').get_by_text('Создать', exact=True).click()
    else:
        page.locator('.nav-tab[data-section="deals"]').click()
        page.locator('#deals .nav-create-btn').click()
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
