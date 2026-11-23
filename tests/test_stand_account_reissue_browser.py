"""Click through the RUB account change with the real stand routes and generator."""

from urllib.parse import urlsplit

import pytest

from tests.test_stand_docs import _deal, _fields, stand


@pytest.mark.browser
@pytest.mark.parametrize('legacy', [False, True])
def test_reissue_rub_freehold_from_sber_to_flow_sole(stand, pytestconfig, legacy):
    from playwright.sync_api import expect, sync_playwright

    deal_id = 986
    old_account = None if legacy else {'mode': 'sber'}
    stand.put_board([_deal(
        deal_id, step='s11' if legacy else 's11b', kind='Фрихолд', curBase='fhusd',
        invoiceCurrency='usd', invoiceUsd=30000, amountRub=2880000,
        rates={'client': '96', 'rubUsdt': '90'}, rubReceivingAccount=old_account,
    )])
    first = stand.post('/api/stand/docs/issue', json={
        'dealId': deal_id, 'docFields': _fields(
            kind='Фрихолд', amountThb='30000', amountPay='2880000', rate='96',
        ),
    })
    assert first.status_code == 200, first.json
    first_docs = first.json['issued']
    original = stand.get('/api/docs/file/' + str(first_docs[-1]['docId'])).data
    browser_errors = []
    issue_requests = []
    # Requests from Playwright run in a different greenlet than pytest's preserved Flask context.
    browser_client = stand.application.test_client()
    browser_client.set_cookie('session', stand.get_cookie('session').value)

    def mock_other_requests(route):
        request = route.request
        url = urlsplit(request.url)
        if url.hostname != 'calccrm.test':
            route.abort()
            return
        if url.path.startswith('/api/') and url.path not in {
            '/api/auth/me', '/api/stand/state', '/api/stand/docs/issue',
        }:
            route.fulfill(json={'success': False})
            return
        if url.path == '/api/stand/docs/issue':
            issue_requests.append(request.post_data_json)
        headers = {name: value for name, value in request.headers.items()
                   if name in {'content-type', 'content-encoding'}}
        response = browser_client.open(
            url.path + ('?' + url.query if url.query else ''),
            method=request.method, headers=headers, data=request.post_data_buffer,
        )
        route.fulfill(status=response.status_code, content_type=response.content_type,
                      body=response.data)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True, executable_path=pytestconfig.getoption('--chromium-executable'),
        )
        context = browser.new_context()
        context.route('**/*', mock_other_requests)
        page = context.new_page()
        page.set_default_timeout(8000)
        page.on('pageerror', lambda error: browser_errors.append(str(error)))
        page.goto(f'http://calccrm.test/tasks?deal={deal_id}')
        reissue = page.get_by_role('button', name='Перевыпустить пакет', exact=True)
        if not legacy:
            reissue.click()
        receiving = page.get_by_label('Куда клиент переводит рубли')
        if not legacy:
            expect(receiving).to_have_value('sber')
        receiving.select_option('flowsole')
        expect(page.locator('#df_agent')).to_have_value('Flow Sole Company Limited')
        expect(page.locator('#df_purpose')).to_have_value('')

        page.evaluate('standSave()')
        before = stand.get('/api/stand/state').json['data']['deals'][0]
        assert before.get('rubReceivingAccount') == old_account
        assert before['docPack']['agent'] == 'mf_corp'
        with page.expect_response(lambda r: r.url.endswith('/api/stand/docs/issue')) as result:
            reissue.click()
        assert result.value.ok, result.value.json()
        assert issue_requests[0]['receivingAccountMode'] == 'flowsole'
        page.wait_for_function(
            "(id) => deal(id)?.step === 's11b' && !standBusy && !standSaveScheduled", arg=deal_id,
        )
        reissue = page.get_by_role('button', name='Перевыпустить пакет', exact=True)
        expect(reissue).to_be_visible()
        assert not browser_errors, browser_errors
        browser.close()

    after = stand.get('/api/stand/state').json['data']['deals'][0]
    assert after['rubReceivingAccount'] == {'mode': 'flowsole'}
    assert after['docVersion'] == 2 and after['docPack']['agent'] == 'flow_sole'
    assert '40807810819000000261' in after['issuedDocPayTo']
    assert after['docPack']['agreementNumber'] in after['docFields']['purpose']
    assert stand.get('/api/docs/file/' + str(first_docs[-1]['docId'])).data == original
