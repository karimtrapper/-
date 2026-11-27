"""Role enforcement for the working custom deal form and its existing endpoint."""
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

import app as A
from tests.test_browser_crm import choose, chromium, crm_server  # noqa: F401


@pytest.mark.browser
def test_working_manager_can_create_own_custom_deal(chromium, crm_server, monkeypatch):
    monkeypatch.setattr(A, 'TASKS_ENABLED', True)
    monkeypatch.setattr(A, 'STAND_MODE', False)
    monkeypatch.setitem(A.app.config, 'SESSION_COOKIE_SECURE', False)
    monkeypatch.setattr(A, 'sync_referrer_reward_to_gsheet', lambda *args, **kwargs: None)
    password = 'synthetic-password'
    with A.get_session() as db:
        manager, other, operator = [
            A.AdminUser(username=username, display_name=name, role=role,
                        password_hash=A.AdminUser.hash_password(password))
            for username, name, role in [
                ('qa_custom_manager', 'QA Custom Manager', 'manager'),
                ('qa_other_manager', 'QA Other Manager', 'manager'),
                ('qa_custom_operator', 'QA Custom Operator', 'operator'),
            ]
        ]
        agent = A.Referrer(name='QA Custom Partner', code='QA-CUSTOM', token='qa-custom-token',
                           default_percent=10, comp_model='revshare')
        db.add_all([manager, other, operator, agent])
        db.commit()
        manager_id, other_id, agent_id = manager.id, other.id, agent.id

    base, admin_cookie = crm_server
    endpoint = base + '/api/deals'
    tracked = (A.Deal, A.Client, A.DealAgent, A.WalletOperation, A.StandState)
    with chromium.new_context(viewport={'width': 1440, 'height': 900}) as context:
        assert context.request.post(base + '/api/auth/login', data={
            'username': 'qa_custom_manager', 'password': password,
        }).ok
        context.route('**/*', lambda route: route.continue_()
                      if urlsplit(route.request.url).hostname == '127.0.0.1' else route.abort())
        page = context.new_page()
        page.set_default_timeout(7000)
        page.goto(base + '/crm?section=deals')
        page.locator('.slate-link[data-slate-route="deals"]').click()
        page.locator('#deals .nav-create-btn').click()
        choose(page, '#dealProductSelect', 'Кастомная — нестандартные валюты')
        select = page.locator('#managerSelect')
        expect(select).to_have_value(f'user:{manager_id}')
        expect(select).to_be_disabled()
        choose(page, '#dealSourceChannel', 'Telegram')
        page.locator('#dealChatManualToggle').click()
        page.locator('#dealChatManualInput').fill('Синтетический источник')
        page.locator('#dealClientNew').click()
        page.locator('#clientSearchInput').fill('QA Custom Client')
        choose(page, '#customPayinCurrency', 'THB (баты)')
        page.locator('#customPayinAmount').fill('178000')
        page.locator('#customPayinUsdt').fill('5249')
        choose(page, '#customPayoutCurrency', 'USD (наличные)')
        page.locator('#customPayoutAmount').fill('4933')
        page.locator('#customPayoutUsdt').fill('5022')
        page.locator('#customDealSection').get_by_role('button', name='Добавить агента').click()
        choose(page, '#agentsBlockCustom select[data-agent-directory]', agent.name)
        expect(page.locator('#agentsBlockCustom input[type=number]')).to_have_value('10')

        with page.expect_response(lambda res: res.url == endpoint and res.request.method == 'POST') as result:
            page.locator('#customDealSubmit').click()
        response = result.value
        assert response.ok, response.json()
        payload = response.request.post_data_json
        assert payload['manager_user_id'] == manager_id
        assert payload['payin_method'] == payload['payout_method'] == ''
        deal_id = response.json()['deal']['id']

        with chromium.new_context() as admin:
            admin.add_cookies([{'name': 'session', 'value': admin_cookie, 'url': base}])
            baseline = admin.request.post(endpoint, data={
                **payload, 'client_name': 'QA Admin Baseline',
                'manager_user_id': other_id, 'manager_name': 'QA Other Manager',
            })
            assert baseline.ok, baseline.json()
            baseline_deal_id = baseline.json()['deal']['id']

        implicit_identity = {key: value for key, value in payload.items()
                             if key not in ('manager_user_id', 'manager_name')}
        flow = context.request.post(endpoint, data={
            **implicit_identity, 'client_name': 'QA Flow Sole Client', 'status': 'pending',
            'payin_method': 'sber_reqs', 'payin_account_key': 'flow_sole',
            'custom_payin_currency': 'RUB', 'custom_payin_amount': 178000,
            'custom_payin_rate': 0, 'payin_amount_usdt': 0,
        })
        assert flow.ok, flow.json()
        flow_id = flow.json()['deal']['id']

        with A.get_session() as db:
            deal = db.get(A.Deal, deal_id)
            baseline_deal = db.get(A.Deal, baseline_deal_id)
            assert (deal.manager_user_id, deal.manager_name, deal.is_custom) == (
                manager_id, 'QA Custom Manager', True)
            for record in (deal, baseline_deal):
                assert (record.payin_amount_usdt, record.payout_amount_usdt,
                        record.profit_usdt, record.referrer_payout_usdt, record.net_profit_usdt) == (
                            5249, 5022, 227, 22.70, 204.30)
                assert record.agents[0].referrer_id == agent_id
            flow_deal = db.get(A.Deal, flow_id)
            assert flow_deal.manager_user_id == manager_id
            assert flow_deal.status == A.DealStatus.PENDING
            assert not flow_deal.payin_tx_verified
            assert db.query(A.StandState).count() == 0
            db.add(A.Wallet(address='TA6S3RBEY57jq8fXEVVsU6H9JZ18inenG4', purpose='exchange',
                            blockchain='TRON', active=True, limit_usd=10000,
                            initiator_roles='["operator"]', confirmer_roles='["findir"]'))
            db.commit()
            counts = [db.query(model).count() for model in tracked]

        cases = [
            ({'is_custom': False}, 403),
            ({'is_custom': 1}, 403),
            ({'manager_user_id': other_id}, 403),
            ({'manager_name': 'QA Other Manager'}, 403),
            ({'status': 'verified'}, 400),
            ({'deal_kind': 'exchange', 'payout_owner_approved': True}, 400),
            ({'skip_sync': True, 'payout_wallet_id': 1}, 400),
            ({'agents': [{**payload['agents'][0], 'paid': True}]}, 400),
        ]
        for changes, status in cases:
            rejected = context.request.post(endpoint, data={**payload, 'client_name': 'QA Rejected', **changes})
            assert rejected.status == status, rejected.json()
        over_limit = context.request.post(endpoint, data={
            **payload, 'client_name': 'QA Over Limit',
            'custom_payout_currency': 'USDT', 'custom_payout_amount': 10001,
            'custom_payout_rate': None, 'payout_amount_usdt': 10001,
        })
        assert over_limit.status == 400, over_limit.json()
        assert 'подтверждение владельца' in over_limit.json()['error']
        for row_id in (deal_id, baseline_deal_id):
            assert context.request.put(f'{endpoint}/{row_id}', data={'notes': 'forbidden'}).status == 403
        with chromium.new_context() as denied:
            assert denied.request.post(endpoint, data=payload).status == 401
            assert denied.request.post(base + '/api/auth/login', data={
                'username': 'qa_custom_operator', 'password': password,
            }).ok
            assert denied.request.post(endpoint, data=payload).status == 403
        with A.get_session() as db:
            assert [db.query(model).count() for model in tracked] == counts
