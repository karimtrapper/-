"""Закрытие сделок Bitrix из CRM (перенос из бота DealCloser).

Бот выключается, поэтому весь путь — список активных сделок, разбор чата,
WON/LOSE — должен жить в CalcCRM. Здесь проверяется контракт эндпоинтов:
Bitrix и LLM замоканы, важна логика вокруг них.

Запуск: cd Dev/CalcCRM && python -m pytest tests/test_bitrix_closing.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('SECRET_KEY', 'test-secret-key-for-pytest')
os.environ['REESTR_SYNC_ENABLED'] = '0'

import pytest

import app as appmod
import bitrix_deals
from app import app as flask_app
from deal_chat_analyzer import AnalysisResult


@pytest.fixture
def cli(monkeypatch):
    flask_app.config['TESTING'] = True
    monkeypatch.setenv('LOCAL_NO_AUTH', '1')
    with flask_app.test_client() as c:
        yield c


class TestActiveDeals:
    def test_lists_deals(self, cli, monkeypatch):
        monkeypatch.setattr(bitrix_deals, 'get_active_deals',
                            lambda *a, **kw: [{'ID': '1009', 'TITLE': 'Артём', 'STAGE_ID': 'NEW'}])
        body = cli.get('/api/bitrix/active-deals').get_json()
        assert body['success'] is True
        assert body['deals'][0]['ID'] == '1009'

    def test_bitrix_down_gives_502(self, cli, monkeypatch):
        def _boom(*a, **kw):
            raise bitrix_deals.BitrixError('портал недоступен')
        monkeypatch.setattr(bitrix_deals, 'get_active_deals', _boom)
        resp = cli.get('/api/bitrix/active-deals')
        assert resp.status_code == 502
        assert resp.get_json()['success'] is False


class TestAnalyze:
    def _mock(self, monkeypatch, verdict='WON', prev=None):
        monkeypatch.setattr(bitrix_deals, 'get_deal',
                            lambda did: {'ID': str(did), 'TITLE': 'Мария - exgreen.pro', 'CONTACT_ID': '77'})
        monkeypatch.setattr(bitrix_deals, 'get_deal_chat_messages', lambda *a, **kw: [{'text': 'оплатил'}])
        monkeypatch.setattr(bitrix_deals, 'get_last_closed_deal_by_contact', lambda *a, **kw: (prev, 1 if prev else 0))

        async def _analyze(*a, **kw):
            r = AnalysisResult()
            r.verdict = verdict
            r.payin_amount_usdt = 1238.8
            r.payout_amount_thb = 40000
            r.summary = 'Клиент оплатил, баты выданы'
            return r
        monkeypatch.setattr(appmod, 'asyncio', appmod.asyncio)
        import deal_chat_analyzer
        monkeypatch.setattr(deal_chat_analyzer, 'analyze_chat', _analyze)

    def test_returns_payload_for_crm(self, cli, monkeypatch):
        self._mock(monkeypatch)
        body = cli.get('/api/bitrix/deals/1009/analyze').get_json()
        assert body['success'] is True
        assert body['analysis']['verdict'] == 'WON'
        p = body['deal_payload']
        # имя клиента чистится от хвоста старого бота, bitrix_deal_id нужен для идемпотентности LOSE
        assert p['client_name'] == 'Мария'
        assert p['bitrix_deal_id'] == 1009
        assert p['payout_amount_thb'] == 40000
        assert p['status'] == 'pending'

    def test_pulls_prev_lose_chat_for_soft_cutoff(self, cli, monkeypatch):
        """Прошлый отказ читаем целиком: клиент мог вернуться к тому же намерению."""
        calls = []
        self._mock(monkeypatch, prev={'ID': '900', 'STAGE_ID': 'LOSE', 'CLOSEDATE': '2026-08-01T10:00:00'})
        orig = bitrix_deals.get_deal_chat_messages
        monkeypatch.setattr(bitrix_deals, 'get_deal_chat_messages',
                            lambda did, **kw: (calls.append(int(did)), [])[1])
        cli.get('/api/bitrix/deals/1009/analyze')
        assert 1009 in calls and 900 in calls

    def test_missing_deal_404(self, cli, monkeypatch):
        monkeypatch.setattr(bitrix_deals, 'get_deal', lambda did: {})
        assert cli.get('/api/bitrix/deals/1/analyze').status_code == 404


class TestClose:
    def test_won_passes_fields(self, cli, monkeypatch):
        got = {}
        monkeypatch.setattr(bitrix_deals, 'close_won',
                            lambda did, data: (got.update({'id': did, 'data': data}), (True, ''))[1])
        monkeypatch.setattr(bitrix_deals, 'set_deal_utm', lambda *a, **kw: True)
        body = cli.post('/api/bitrix/deals/1009/close-won',
                        json={'payin_amount_usdt': 1238.8, 'payout_amount_thb': 40000}).get_json()
        assert body['success'] is True
        assert got['id'] == 1009 and got['data']['payout_amount_thb'] == 40000

    def test_won_bitrix_error_is_502(self, cli, monkeypatch):
        monkeypatch.setattr(bitrix_deals, 'close_won', lambda did, data: (False, 'поле обязательно'))
        resp = cli.post('/api/bitrix/deals/1009/close-won', json={})
        assert resp.status_code == 502
        assert 'обязательно' in resp.get_json()['error']

    def test_lose_default_reason(self, cli, monkeypatch):
        got = {}
        monkeypatch.setattr(bitrix_deals, 'close_lose',
                            lambda did, reason: (got.update({'reason': reason}), (True, ''))[1])
        cli.post('/api/bitrix/deals/1009/close-lose', json={})
        assert got['reason'] == ''  # дефолт подставляет сам клиент Bitrix

    def test_lose_passes_reason(self, cli, monkeypatch):
        got = {}
        monkeypatch.setattr(bitrix_deals, 'close_lose',
                            lambda did, reason: (got.update({'reason': reason}), (True, ''))[1])
        cli.post('/api/bitrix/deals/1009/close-lose', json={'reason': 'не устроил курс'})
        assert got['reason'] == 'не устроил курс'


class TestPortalWiring:
    """Портал только один и только из env.

    До 10.08.2026 дефолт вёл на реверс-прокси старого портала МаксФина, а
    воронка бралась нулевая — CRM показывала чужие корпоративные сделки
    (ООО/ЧОО) вместо клиентов Grusha. Фоллбэка быть не должно.
    """

    def test_no_webhook_fails_loudly(self, monkeypatch):
        monkeypatch.setattr(bitrix_deals, 'BITRIX_WEBHOOK', '')
        with pytest.raises(bitrix_deals.BitrixError, match='BITRIX_WEBHOOK'):
            bitrix_deals.get_active_deals()

    def test_requests_go_to_env_webhook(self, monkeypatch):
        seen = {}

        class _Resp:
            @staticmethod
            def json():
                return {'result': []}

        def _fake_post(url, data=None, timeout=None):
            seen['url'] = url
            seen['data'] = data
            return _Resp()

        monkeypatch.setattr(bitrix_deals, 'BITRIX_WEBHOOK', 'https://portal.example/rest/1/key/')
        monkeypatch.setattr(bitrix_deals.requests, 'post', _fake_post)
        bitrix_deals.get_active_deals()
        assert seen['url'] == 'https://portal.example/rest/1/key/crm.deal.list'
        assert seen['data']['filter[CATEGORY_ID]'] == 0
        # Закрытые отсекает портал: страница из 50 свежих WON/LOSE иначе
        # съедала выборку и оператор видел пустой список
        assert seen['data']['filter[!STAGE_ID][0]'] == 'WON'
        assert seen['data']['filter[!STAGE_ID][1]'] == 'LOSE'

    def test_contacts_search_uses_grusha_pipeline(self, cli, monkeypatch):
        seen = {}

        def _fake(method, data=None):
            seen['method'], seen['data'] = method, data
            return {'result': [{'ID': '1', 'TITLE': 'Артём - Grusha', 'CONTACT_ID': '77'}]}

        monkeypatch.setattr(bitrix_deals, '_post', _fake)
        body = cli.get('/api/bitrix/contacts/search?q=Артём').get_json()
        assert seen['data']['filter[CATEGORY_ID]'] == bitrix_deals.BITRIX_PIPELINE_ID == 0
        assert body['contacts'] == [{'id': '77', 'name': 'Артём'}]
