"""Focused T17/T26 draft, extra pay-in and atomic manual close browser probe.

Run only inside the exact-port T17 OS fence with a fresh synthetic SQLite DB.
"""
import json
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


def wait_js(page, expression):
    # T26 CSP blocks the eval used by Playwright wait_for_function.
    for _ in range(100):
        if page.evaluate(f'() => ({expression})'):
            return
        time.sleep(.05)
    raise AssertionError(f'timed out waiting for {expression}')


def choose_native(scope, field, value):
    # The picker hit test has its own T17 QA. For this close-flow fixture,
    # dispatch the same change event on its hidden native select.
    control = scope.locator('#' + field)
    control.evaluate('''(element,value)=>{
      element.value=value;
      element.dispatchEvent(new Event('change',{bubbles:true}));
    }''', value)


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(service_workers='block')
    blocked = []

    def local_only(route):
        if route.request.url.startswith('http://127.0.0.1:18917/'):
            route.continue_()
        else:
            blocked.append(route.request.url.split('?')[0])
            route.abort()

    context.route('**/*', local_only)
    page = context.new_page()
    crm_posts = []
    close_posts = []
    page.on('request', lambda request: crm_posts.append(request.url)
            if request.method == 'POST' and request.url.endswith('/api/deals') else None)
    page.on('request', lambda request: close_posts.append(request.url)
            if request.method == 'POST' and '/crm-close' in request.url else None)
    login = page.request.post('http://127.0.0.1:18917/api/auth/login',
                              data={'username': 'karim', 'password': 'synthetic-t17'})
    assert login.status == 200, login.text()
    page.goto('http://127.0.0.1:18917/tasks', wait_until='domcontentloaded')
    wait_js(page, 'standVer !== null && !standBusy')
    page.evaluate('startManual()')
    wait_js(page, '!standBusy && !standPush')
    draft = page.locator('#crmDraftHost')
    draft.locator('#createDealForm').wait_for()
    draft.locator('#clientSearchInput').fill('T17 T26 main and extra')
    choose_native(draft, 'payinMethod', 'crypto_direct')
    draft.locator('[name="payin_amount_usdt"]').fill('100')
    choose_native(draft, 'payoutSource', 'binance')
    draft.locator('#payoutAmountThb').fill('3200')
    draft.locator('#binanceUsdt').fill('98')
    draft.locator('button[data-crm-call="payinExtraAdd()"]') .click()
    draft.locator('#payinExtraList select').first.select_option('partners_cash')
    draft.locator('#pe-0-rub').fill('2000')
    draft.locator('#pe-0-rate').fill('100')
    page.locator('.card.edit-page > .row > button').first.click()
    wait_js(page, '!standBusy && !standPush')
    page.reload(wait_until='domcontentloaded')
    wait_js(page, 'standVer !== null && !standBusy')
    saved = page.evaluate('''()=>{const d=S.deals.find(
      x=>x.client==='T17 T26 main and extra');
      return {id:d.id,origin:d.originMode,version:standVer,
        payload:crmPayload(d),extra:d.payinExtra};}''')
    print('saved_extra_probe', json.dumps({'extra': saved['extra'],
          'payload_extra': saved['payload']['payin_extra']}, ensure_ascii=False), flush=True)
    assert saved['origin'] == 'manual'
    assert saved['payload']['payin_amount_usdt'] == 100
    assert len(saved['payload']['payin_extra']) == 1
    assert saved['payload']['payin_extra'][0]['amount_usdt'] == 20
    assert not crm_posts, crm_posts
    print('draft_main_extra', saved['payload']['payin_amount_usdt'],
          saved['payload']['payin_extra'][0]['amount_usdt'],
          'early_crm_posts', len(crm_posts))

    deal_id = saved['id']
    page.evaluate('(id)=>openDeal(id)', deal_id)
    assert page.get_by_role('button', name='Сохранить в CRM').is_enabled()
    with page.expect_response(lambda response: response.url.endswith(
            f'/api/stand/deals/{deal_id}/crm-close') and
            response.request.method == 'POST', timeout=20000) as event:
        page.evaluate('(id)=>{crmPushClose(id);crmPushClose(id)}', deal_id)
    first = event.value
    first_body = first.json()
    assert first.status == 201, first_body
    assert len(close_posts) == 1, close_posts
    crm_id = first_body['deal']['id']
    page.reload(wait_until='domcontentloaded')
    wait_js(page, 'standVer !== null && !standBusy')
    closed = page.evaluate('''id=>{const d=deal(id);return {
      closed:d.closed,step:d.step,crmDealId:d.crmDealId};}''', deal_id)
    assert closed == {'closed': True, 'step': 'done', 'crmDealId': crm_id}, closed
    retry = page.evaluate('''async({id,version,crm})=>{
      const response=await fetch(`/api/stand/deals/${id}/crm-close`,{
        method:'POST',credentials:'same-origin',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({version,crm})});
      return {status:response.status,body:await response.json()};
    }''', {'id': deal_id, 'version': saved['version'], 'crm': saved['payload']})
    assert retry['status'] == 200 and retry['body']['deal']['id'] == crm_id, retry
    db = appmod.get_session()
    try:
        assert db.query(appmod.Deal).count() == 1
        row = db.query(appmod.Deal).filter_by(id=crm_id).one()
        extra = json.loads(row.payin_extra) if isinstance(row.payin_extra, str) else row.payin_extra
        assert row.payin_amount_usdt == 120
        assert len(extra) == 1 and extra[0]['amount_usdt'] == 20
        print('final_one_crm', crm_id, row.payin_amount_usdt,
              extra[0]['method'], 'retry', retry['status'])
    finally:
        db.close()
    print('blocked_external_assets', len(blocked))
    browser.close()
