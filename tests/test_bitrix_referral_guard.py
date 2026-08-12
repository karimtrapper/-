"""Реферал из разбора чата и защита от повторного WON.

12.08.2026 две сделки подряд (#495 Olya, #498 Roman) приехали в CRM с партнёром
GR-KARIM, хотя в переписке строки `ref__` не было вообще: модель списала код из
примера в системном промпте. Заодно всплыло, что кнопка «Закрыть WON» после
успешного закрытия оставалась активной и второй клик записывал сделку заново.

Запуск: cd Dev/CalcCRM && python -m pytest tests/test_bitrix_referral_guard.py -v
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('SECRET_KEY', 'test-secret-key-for-pytest')
os.environ['REESTR_SYNC_ENABLED'] = '0'

import pytest

import deal_chat_analyzer as dca
from app import app as flask_app, get_session, Client, Deal, DealAgent


@pytest.fixture
def cli(monkeypatch):
    flask_app.config['TESTING'] = True
    monkeypatch.setenv('LOCAL_NO_AUTH', '1')
    with flask_app.test_client() as c:
        yield c


def _run_analysis(monkeypatch, messages, llm_fields):
    """Прогоняет analyze_chat с замоканной моделью и отдаёт результат."""
    async def _intent(*a, **kw):
        return 'new_payment', 'high', 'оплата подтверждена'

    async def _full(*a, **kw):
        return {'verdict': 'WON', 'confidence': 'high', 'summary': 'ок', **llm_fields}

    monkeypatch.setattr(dca, '_classify_intent', _intent)
    monkeypatch.setattr(dca, '_full_analysis', _full)
    return asyncio.run(dca.analyze_chat(messages, deal_title='Roman - Grusha'))


class TestReferralHallucination:
    CHAT = [
        {'text': 'Оплатил, скинул чек', 'author_id': 55, 'date': '2026-08-12T09:00:00+03:00'},
        {'text': 'Получили, выдаём баты', 'author_id': 967, 'date': '2026-08-12T09:01:00+03:00'},
    ]

    def test_code_absent_from_chat_is_dropped(self, monkeypatch):
        """Кейс 12.08: кода в переписке нет — метка партнёра не ставится."""
        r = _run_analysis(monkeypatch, self.CHAT, {'referral_code': 'GR-KARIM'})
        assert r.referral_code == ''
        assert 'referrer_name' not in r.to_calccrm_payload(client_name='Roman')

    def test_invented_name_is_dropped(self, monkeypatch):
        r = _run_analysis(monkeypatch, self.CHAT, {'referred_by_name': 'Карим'})
        assert r.referred_by_name == ''

    def test_real_code_survives(self, monkeypatch):
        chat = [{'text': '/start ref__GRINSIGH', 'author_id': 55,
                 'date': '2026-08-12T08:00:00+03:00'}] + self.CHAT
        r = _run_analysis(monkeypatch, chat, {'referral_code': 'GR-INSIGH'})
        assert r.referral_code == 'GR-INSIGH'
        assert r.to_calccrm_payload(client_name='Roman')['referrer_name'] == 'GR-INSIGH'

    def test_real_name_survives(self, monkeypatch):
        chat = [{'text': 'Меня Женя посоветовала', 'author_id': 55,
                 'date': '2026-08-12T08:00:00+03:00'}] + self.CHAT
        r = _run_analysis(monkeypatch, chat, {'referred_by_name': 'Женя'})
        assert r.referred_by_name == 'Женя'

    def test_regex_fallback_still_works(self, monkeypatch):
        """Модель промолчала — код всё равно достаётся регуляркой из /start."""
        chat = [{'text': '/start ref__GRINSIGH_calc_RUB_1kk_THB', 'author_id': 55,
                 'date': '2026-08-12T08:00:00+03:00'}] + self.CHAT
        r = _run_analysis(monkeypatch, chat, {})
        assert r.referral_code == 'GR-INSIGH'

    def test_prompt_has_no_real_referral_code(self):
        """Живой код партнёра в примере промпта — источник этой галлюцинации."""
        assert 'GR-KARIM' not in dca.FULL_SYSTEM_PROMPT_BASE


class TestWonIdempotency:
    """Повторный клик «Закрыть WON» не должен плодить сделки."""

    PAYLOAD = {
        'client_name': 'Roman - Grusha', 'status': 'pending', 'bitrix_deal_id': 1041,
        'payin_method': 'spp_doverka', 'payin_amount_rub': 30000,
        'payout_amount_thb': 12000, 'payout_method': 'transfer', 'skip_sync': True,
    }

    @pytest.fixture(autouse=True)
    def clean_db(self):
        """Дедуп идёт по всей базе — тесты должны стартовать с чистой."""
        def _clean():
            session = get_session()
            try:
                session.query(DealAgent).delete()
                session.query(Deal).delete()
                session.query(Client).delete()
                session.commit()
            finally:
                session.close()
        _clean()
        yield
        _clean()

    def test_second_post_returns_same_deal(self, cli):
        first = cli.post('/api/deals', json=self.PAYLOAD).get_json()
        assert first['success'] is True
        second = cli.post('/api/deals', json=self.PAYLOAD).get_json()
        assert second['duplicate'] is True
        assert second['deal']['id'] == first['deal']['id']

    def test_lose_then_won_still_allowed(self, cli):
        """Ошибочный LOSE не должен блокировать перезакрытие в WON."""
        lose = {'client_name': 'Eleni - Grusha', 'status': 'lose',
                'lose_reason': 'не вернулся', 'bitrix_deal_id': 1042}
        cli.post('/api/deals', json=lose)
        won = cli.post('/api/deals', json={**self.PAYLOAD, 'bitrix_deal_id': 1042,
                                           'client_name': 'Eleni - Grusha'}).get_json()
        assert won['success'] is True
        assert not won.get('duplicate')

    def test_deals_without_bitrix_id_are_not_deduped(self, cli):
        """Ручные сделки в CRM дублями не считаются — у них нет ключа Битрикса."""
        manual = {k: v for k, v in self.PAYLOAD.items() if k != 'bitrix_deal_id'}
        a = cli.post('/api/deals', json=manual).get_json()
        b = cli.post('/api/deals', json=manual).get_json()
        assert a['deal']['id'] != b['deal']['id']


class TestNotLead:
    """«Не обращение» — не победа и не отказ, из конверсии выпадает совсем."""

    BASE = {'client_name': 'Случайный - Grusha', 'status': 'not_lead',
            'lose_reason': 'не обращение', 'bitrix_deal_id': 1050}

    @pytest.fixture(autouse=True)
    def clean_db(self):
        def _clean():
            session = get_session()
            try:
                session.query(DealAgent).delete()
                session.query(Deal).delete()
                session.query(Client).delete()
                session.commit()
            finally:
                session.close()
        _clean()
        yield
        _clean()

    def test_client_is_not_created(self, cli):
        """Случайное сообщение не должно заводить клиента в базе."""
        assert cli.post('/api/deals', json=self.BASE).get_json()['success'] is True
        session = get_session()
        try:
            assert session.query(Client).count() == 0
        finally:
            session.close()

    def test_hidden_from_main_list(self, cli):
        cli.post('/api/deals', json=self.BASE)
        ids = [d['id'] for d in cli.get('/api/deals').get_json()['deals']]
        assert ids == []
        by_status = cli.get('/api/deals?status=not_lead').get_json()['deals']
        assert len(by_status) == 1

    def test_not_counted_in_conversion(self, cli):
        """Ради этого всё и делалось: знаменатель CR не растёт."""
        cli.post('/api/deals', json={'client_name': 'Покупатель', 'status': 'completed',
                                     'payin_amount_usdt': 100, 'payout_amount_usdt': 98,
                                     'skip_sync': True})
        before = cli.get('/api/analytics/conversion').get_json()
        cli.post('/api/deals', json=self.BASE)
        after = cli.get('/api/analytics/conversion').get_json()
        assert after['totals'] == before['totals']

    def test_lose_still_counted(self, cli):
        """Контроль: обычный отказ конверсию менять обязан."""
        cli.post('/api/deals', json={'client_name': 'Покупатель', 'status': 'completed',
                                     'payin_amount_usdt': 100, 'payout_amount_usdt': 98,
                                     'skip_sync': True})
        before = cli.get('/api/analytics/conversion').get_json()
        cli.post('/api/deals', json={'client_name': 'Ушедший', 'status': 'lose',
                                     'lose_reason': 'не устроил курс', 'bitrix_deal_id': 1051})
        after = cli.get('/api/analytics/conversion').get_json()
        assert after['totals'] != before['totals']

    def test_not_offered_for_revive(self, cli):
        cli.post('/api/deals', json=self.BASE)
        d = cli.get('/api/deals/lose-candidates?client_name=Случайный - Grusha').get_json()
        assert not (d.get('candidates') or d.get('deals') or [])

    def test_second_click_is_idempotent(self, cli):
        first = cli.post('/api/deals', json=self.BASE).get_json()
        second = cli.post('/api/deals', json=self.BASE).get_json()
        assert second['duplicate'] is True
        assert second['deal']['id'] == first['deal']['id']

    def test_won_after_dismiss_still_possible(self, cli):
        """Ошиблись кнопкой — победу по той же сделке Битрикса завести можно."""
        cli.post('/api/deals', json=self.BASE)
        won = cli.post('/api/deals', json={
            'client_name': 'Случайный - Grusha', 'status': 'pending', 'bitrix_deal_id': 1050,
            'payout_amount_thb': 5000, 'payout_method': 'transfer', 'skip_sync': True,
        }).get_json()
        assert won['success'] is True and not won.get('duplicate')


class TestCloseWonUiContract:
    """Контракт кнопки: после успешной записи она не должна оживать."""

    @pytest.fixture
    def html(self):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            'static', 'crm', 'crm.html')
        with open(path, encoding='utf-8') as f:
            return f.read()

    def test_button_stays_disabled_after_success(self, html):
        body = html[html.index('async function closeBitrixWon'):html.index('async function offerRevive')]
        assert 'if (created)' in body
        # безусловного возврата кнопки в строю быть не должно
        assert body.count("btn.disabled = false") == 1
        assert body.index('} else {') < body.index("btn.disabled = false")

    def test_referrer_field_is_editable(self, html):
        assert 'id="bxReferrer"' in html
        assert "p.referrer_name = val('bxReferrer')" in html

    def test_dismiss_button_wired(self, html):
        assert 'dismissBitrixDeal()' in html
        body = html[html.index('async function dismissBitrixDeal'):html.index('function openAddWalletModal')]
        assert "status: 'not_lead'" in body
        # карточку прячем, иначе кнопку жмут повторно
        assert "getElementById('bitrixAnalysisCard').style.display = 'none'" in body
        assert "'not_lead': 'Не обращение'" in html
