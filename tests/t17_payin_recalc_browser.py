"""Focused CRM/stand RUB input parity. Run only inside the T17 OS fence."""
import runpy
import socket
import threading
import time

from playwright.sync_api import sync_playwright


appmod = runpy.run_path('tests/t17_fenced_smoke.py')['app']
server = threading.Thread(target=lambda: appmod.app.run(
    host='127.0.0.1', port=18917, debug=False, use_reloader=False), daemon=True)
server.start()
for _ in range(50):
    with socket.socket() as sock:
        if sock.connect_ex(('127.0.0.1', 18917)) == 0:
            break
    time.sleep(.1)
else:
    raise RuntimeError('fenced localhost server did not start')


def field(scope, name):
    return scope.locator(f'[name="{name}"]')


def wait_js(page, expression):
    # T26 stage CSP disallows the eval used internally by wait_for_function.
    for _ in range(100):
        if page.evaluate(f'() => ({expression})'):
            return
        time.sleep(.05)
    raise AssertionError(f'timed out waiting for {expression}')


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(service_workers='block')
    external = []
    crm_posts = []

    def local_only(route):
        if route.request.url.startswith('http://127.0.0.1:18917/'):
            route.continue_()
        else:
            external.append(route.request.url.split('?')[0])
            route.abort()

    context.route('**/*', local_only)
    tasks = context.new_page()
    tasks.on('request', lambda request: crm_posts.append(request.url)
             if request.method == 'POST' and request.url.endswith('/api/deals') else None)
    login = tasks.request.post('http://127.0.0.1:18917/api/auth/login',
                               data={'username': 'karim', 'password': 'synthetic-t17'})
    assert login.status == 200, login.text()
    tasks.goto('http://127.0.0.1:18917/tasks', wait_until='domcontentloaded')
    wait_js(tasks, 'standVer !== null && !standBusy')
    tasks.evaluate('startManual()')
    wait_js(tasks, '!standBusy && !standPush')
    draft = tasks.locator('#crmDraftHost')
    draft.locator('#createDealForm').wait_for()

    crm = context.new_page()
    crm.goto('http://127.0.0.1:18917/crm', wait_until='domcontentloaded')
    crm.evaluate('showSection("create")')
    crm.locator('#createDealForm').wait_for()

    def compare(label):
        values = [field(scope, 'payin_amount_usdt').input_value()
                  for scope in (crm, draft)]
        assert values[0] == values[1], (label, values)
        print(label, values[0])
        return values[0]

    # Source CRM oninput=autoCalcUsdt() for RUB; draft delegated listener
    # must call the same source function in both entry orders.
    for scope in (crm, draft):
        field(scope, 'payin_rate_rub_usdt').fill('77.5')
        field(scope, 'payin_amount_rub').fill('180000')
    assert compare('rate_then_rub') == '2322.58'
    for scope in (crm, draft):
        field(scope, 'payin_amount_rub').fill('200000')
    assert compare('rub_changed_with_rate') == '2580.65'

    for scope in (crm, draft):
        field(scope, 'payin_amount_rub').fill('')
        field(scope, 'payin_rate_rub_usdt').fill('')
        field(scope, 'payin_amount_usdt').fill('')
        field(scope, 'payin_amount_rub').fill('180000')
        field(scope, 'payin_rate_rub_usdt').fill('77.5')
    assert compare('rub_then_rate') == '2322.58'
    for scope in (crm, draft):
        field(scope, 'payin_amount_rub').fill('190000')
    assert compare('rub_changed_again') == '2451.61'

    draft.locator('#clientSearchInput').fill('T17 payin recalculation')
    tasks.locator('.card.edit-page > .row > button').first.click()
    wait_js(tasks, '!standBusy && !standPush')
    saved_id = tasks.evaluate('''()=>S.deals.find(
      d=>d.client==='T17 payin recalculation')?.id''')
    assert saved_id is not None
    tasks.reload(wait_until='domcontentloaded')
    wait_js(tasks, 'standVer !== null && !standBusy')
    saved = tasks.evaluate('''id=>{const d=deal(id);return {
      rub:d.amountRub,rate:d.rates.broker,usdt:d.amountUsdt,
      origin:d.originMode};}''', saved_id)
    assert saved == {'rub': 190000, 'rate': 77.5, 'usdt': 2451.61,
                     'origin': 'manual'}, saved
    tasks.evaluate('(id)=>editOpen(id)', saved_id)
    wait_js(tasks, '!standBusy && !standPush')
    draft.locator('#createDealForm').wait_for()
    assert field(draft, 'payin_amount_usdt').input_value() == '2451.61'
    assert not crm_posts, crm_posts
    print('save_reload_reopen', saved, 'early_crm_posts', len(crm_posts))
    print('blocked_external_assets', len(external))
    browser.close()
