"""Real Chromium one-click repro on an isolated QA SQLite backup.

Usage inside the T24 sandbox: python scripts/t24_browser_repro.py baseline|fixed
The source tree and DATABASE_URL are supplied by a clean caller environment.
"""
import asyncio
import json
import os
from pathlib import Path
import sqlite3
import sys
import threading

from playwright.async_api import async_playwright
from werkzeug.serving import make_server


mode = sys.argv[1]
source = Path(os.environ['T24_SOURCE']).resolve()
database = Path(os.environ['T24_DB']).resolve()
assert mode in ('baseline', 'fixed')
assert str(database).startswith('/private/tmp/calccrm-t24-browser/') or str(database).startswith('/tmp/calccrm-t24-browser/')
os.chdir(source)
sys.path.insert(0, str(source))

with sqlite3.connect(database) as conn:
    row = conn.execute('SELECT version, data FROM stand_state WHERE id=1').fetchone()
    state = json.loads(row[1])
    deal = next(d for d in state['deals'] if d.get('id') == 1474)
    deal.update(step='s27', closed=False, crmDealId=None, sentToClient=False,
                closeReason=None, closedAt=None, sentAt=None)
    conn.execute('UPDATE stand_state SET version=?, data=? WHERE id=1',
                 (row[0] + 1, json.dumps(state, ensure_ascii=False)))
    before_count = conn.execute('SELECT count(*) FROM deals').fetchone()[0]

import app as m  # noqa: E402: after sanitized environment and fixture preparation
m.stand_egress.allow_test_target('127.0.0.1', 29991)
async def _synthetic_rates():
    return {'usdt_thb': 32.0, 'rub_usdt': 92.0}
m.ExchangeRateProvider.get_all_rates = _synthetic_rates

if mode == 'fixed':
    # Rebind the copied legacy QA deal to its already confirmed conversion and
    # network payout. The manager's sentToggle below records sent evidence in
    # the same PUT, so the first close click remains the action under test.
    with m.app.test_client() as prepared:
        with prepared.session_transaction() as sess:
            sess['user_id'] = 2
            sess['username'] = 'marina'
            sess['display_name'] = 'Марина'
        current = prepared.get('/api/stand/state').json
        for kind in ('payin', 'payout'):
            admitted = prepared.post('/api/stand/deals/1474/close-evidence',
                json={'version': current['version'], 'kind': kind})
            assert admitted.status_code == 200, (kind, admitted.json)
            current = admitted.json
        print('QA existing verified facts rebound: payin+payout')

server = make_server('127.0.0.1', 29991, m.app, threaded=True)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()


async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=(
            '/Users/karimamirov/Library/Caches/ms-playwright/'
            'chromium_headless_shell-1234/chrome-headless-shell-mac-arm64/chrome-headless-shell'))
        context = await browser.new_context(viewport={'width': 1440, 'height': 900})
        cookie = m.app.session_interface.get_signing_serializer(m.app).dumps({
            'user_id': 2, 'username': 'marina', 'display_name': 'Марина'})
        await context.add_cookies([{'name': 'session', 'value': cookie,
                                    'url': 'http://127.0.0.1:29991', 'httpOnly': True}])
        async def local_only(route):
            if not route.request.url.startswith('http://127.0.0.1:29991/'):
                await route.abort()
            else:
                await route.continue_()
        await context.route('**/*', local_only)
        page = await context.new_page()
        await page.goto('http://127.0.0.1:29991/tasks')
        await page.wait_for_function("typeof S !== 'undefined' && S.deals.some(d=>d.id===1474)")
        await page.wait_for_function('!standBusy && !standPush')
        await page.wait_for_timeout(200)
        await page.evaluate("S.open=1474; S.view='task'; render()")
        button_sent = page.get_by_role('button', name='Отметить — чек отправлен клиенту')
        button_close = page.get_by_role('button', name='Сохранить в CRM и закрыть «Успешно»')
        assert await button_sent.count() == 1
        assert await button_close.is_disabled()

        get_started = asyncio.Event()
        put_done = asyncio.Event()
        crm_done = asyncio.Event()
        release_get = asyncio.Event()
        release_put = asyncio.Event()
        release_crm = asyncio.Event()
        async def controlled(route):
            req = route.request
            if req.url.endswith('/api/stand/state') and req.method == 'GET':
                get_started.set()
                await put_done.wait()
                response = await route.fetch()
                await release_get.wait()
                await route.fulfill(response=response)
            elif req.url.endswith('/api/stand/state') and req.method == 'PUT':
                response = await route.fetch()
                put_done.set()
                await release_put.wait()
                await route.fulfill(response=response)
            elif ((req.url.endswith('/api/deals') if mode == 'baseline' else
                   req.url.endswith('/api/stand/deals/1474/crm-close')) and req.method == 'POST'):
                response = await route.fetch()
                if mode == 'fixed':
                    outcome = await response.json()
                    print('close HTTP', response.status, outcome.get('error'),
                          outcome.get('missing'))
                crm_done.set()
                await release_crm.wait()
                await route.fulfill(response=response)
            else:
                await route.continue_()
        await context.route('**/api/**', controlled)
        await page.evaluate('void standPull(false)')
        await asyncio.wait_for(get_started.wait(), 10)
        await button_sent.click()
        await asyncio.wait_for(put_done.wait(), 5)
        assert await button_close.is_enabled()
        await button_close.click()
        if mode == 'baseline':
            await asyncio.wait_for(crm_done.wait(), 10)
            await page.evaluate('lastPointer=0; window.t24D=S.deals.find(d=>d.id===1474)')
            release_get.set()
            await page.wait_for_function('S.deals.find(d=>d.id===1474)!==window.t24D')
            release_crm.set()
            release_put.set()
        else:
            release_get.set()
            release_put.set()
            await asyncio.wait_for(crm_done.wait(), 10)
            release_crm.set()
        await page.wait_for_timeout(800)
        await page.reload()
        await page.wait_for_function("typeof S !== 'undefined' && S.deals.some(d=>d.id===1474)")
        actual = await page.evaluate("(()=>{const d=S.deals.find(x=>x.id===1474);return {step:d.step,closed:d.closed,crmDealId:d.crmDealId}})()")
        with sqlite3.connect(database) as conn:
            count = conn.execute('SELECT count(*) FROM deals').fetchone()[0]
        print(json.dumps({'mode': mode, 'board': actual, 'crm_rows_added': count - before_count}))
        if mode == 'baseline':
            assert actual['step'] == 's27' and not actual['closed'] and actual['crmDealId'] is None
            assert count == before_count + 1
        else:
            assert actual['step'] == 'done' and actual['closed'] and actual['crmDealId']
            assert count == before_count + 1
        await context.close()
        await browser.close()


try:
    asyncio.run(run())
    ledger = Path(os.environ['CALCCRM_FENCE_LEDGER'])
    entries = [json.loads(line) for line in ledger.read_text().splitlines()] if ledger.exists() else []
    unexpected = [item for item in entries if not item.get('expected')]
    print('NETWORK_FENCE attempts=' + str(len(entries)) +
          ' unexpected=' + str(len(unexpected)))
    assert not unexpected
finally:
    server.shutdown()
    thread.join(timeout=5)
    server.server_close()
