"""
ДДС по кассовому методу — /api/finance/cashflow и /api/finance/summary.

Главное, что проверяем, — отсутствие двойного счёта. Одни и те же деньги
проходят через несколько сущностей (приход Сбера → пачка → перевод USDT →
закупка батов → выдача клиенту), и наивная выгрузка посчитала бы их трижды.
Плюс граница «перекладывание между своими счетами» vs «операционные деньги»
и честная пометка приблизительных дат.

Запуск: cd Dev/CalcCRM && python -m pytest tests/test_finance_cashflow.py -v
"""
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('SECRET_KEY', 'test-secret-key-for-pytest')
os.environ['REESTR_SYNC_ENABLED'] = '0'

import pytest

import app as A
from app import (AdminUser, BankCard, CardAllocation, CardTopup, CashAllocation,
                 CashBatch, Client, Conversion, ConversionTx, Deal, DealAgent,
                 DealStatus, DealType, PayInMethod, PayOutMethod, PayOutSource,
                 PayinTx, PayinTxUse, Reimbursement, SberDebit, SberIncome,
                 get_session)


@pytest.fixture(autouse=True)
def clean_db():
    s = get_session()
    try:
        for model in (ConversionTx, Conversion, PayinTxUse, PayinTx, SberIncome,
                      SberDebit, CashAllocation, CardAllocation, CardTopup,
                      CashBatch, BankCard, DealAgent, Reimbursement, Deal, Client):
            s.query(model).delete()
        s.commit()
    finally:
        s.close()
    yield


@pytest.fixture
def tc():
    A.app.config['TESTING'] = True
    s = get_session()
    try:
        a = s.query(AdminUser).first()
        if not a:
            a = AdminUser(username='fin_admin', display_name='T',
                          password_hash=AdminUser.hash_password('x'))
            s.add(a)
            s.commit()
        aid = a.id
    finally:
        s.close()
    with A.app.test_client() as c:
        with c.session_transaction() as sess:
            sess['user_id'] = aid
        yield c


def add(*objs):
    s = get_session()
    try:
        for o in objs:
            s.add(o)
        s.commit()
        for o in objs:
            try:
                s.refresh(o)
            except Exception:
                pass
    finally:
        s.close()


def deal(**over):
    d = Deal(id=1, client_name='Иван', deal_type=DealType.PAY_OUT,
             status=DealStatus.COMPLETED, created_at=datetime(2026, 8, 10, 12, 0),
             payin_method=PayInMethod.SBER_WL, payin_amount_rub=100000,
             payin_amount_usdt=1000, payout_method=PayOutMethod.OFFICE,
             payout_source=PayOutSource.CASH_BATCH, payout_amount_thb=32000,
             payout_amount_usdt=950, profit_usdt=50, net_profit_usdt=50)
    for k, v in over.items():
        setattr(d, k, v)
    return d


def events(tc, qs=''):
    return tc.get('/api/finance/cashflow' + qs).get_json()['events']


def by_article(tc, qs=''):
    out = {}
    for e in events(tc, qs):
        out.setdefault(e['article'], []).append(e)
    return out


class TestSources:
    def test_sber_income_is_operating_in(self, tc):
        add(SberIncome(uuid='u1', operation_date='2026-08-05T10:00:00',
                       amount_rub=250000, payer='Петров П.П.', purpose='перевод'))
        e = by_article(tc)['payin_client_rub'][0]
        assert e['date'] == '2026-08-05'
        assert (e['flow'], e['amount'], e['currency']) == ('in', 250000, 'RUB')
        assert e['account'] == 'sber_rub'
        assert e['counterparty'] == 'Петров П.П.'
        assert e['date_estimated'] is False

    def test_sber_debits_split_broker_and_fee(self, tc):
        add(SberDebit(uuid='d1', operation_date='2026-08-06T10:00:00',
                      amount_rub=240000, payee='БРАЙТУМ', kind='broker'),
            SberDebit(uuid='d2', operation_date='2026-08-06T10:05:00',
                      amount_rub=760, payee='Сбербанк', kind='fee'))
        arts = by_article(tc)
        assert arts['broker_rub_out'][0]['flow'] == 'transfer'
        assert arts['bank_fee_rub'][0]['flow'] == 'out'

    def test_broker_usdt_is_transfer_not_revenue(self, tc):
        """USDT от брокера — вторая нога обмена рублей, а не выручка."""
        tx = PayinTx(tx_hash='hb', amount_usdt=2700, tx_time=datetime(2026, 8, 7, 9, 0))
        add(tx)
        conv = Conversion(broker='Azia Capital')
        add(conv)
        add(ConversionTx(conversion_id=conv.id, payin_tx_id=tx.id, amount_usdt=2700))
        e = by_article(tc)['broker_usdt_in'][0]
        assert e['flow'] == 'transfer'
        assert e['counterparty'] == 'Azia Capital'
        # В операционный итог не попал
        t = tc.get('/api/finance/cashflow').get_json()['totals']['all']
        assert t['in'].get('USDT') is None

    def test_direct_client_usdt_is_revenue(self, tc):
        d = deal(payin_method=PayInMethod.CRYPTO_DIRECT)
        add(d)
        tx = PayinTx(tx_hash='hc', amount_usdt=1000, tx_time=datetime(2026, 8, 8, 9, 0))
        add(tx)
        add(PayinTxUse(tx_id=tx.id, deal_id=d.id, amount_usdt=1000))
        e = by_article(tc)['payin_client_usdt'][0]
        assert e['flow'] == 'in' and e['deal_id'] == d.id
        assert e['product'] == 'exchange'

    def test_payin_tx_without_time_falls_back_to_deal_date(self, tc):
        """Таблицу payin_txs наполняли задним числом: created_at у 110 переводов
        это день бэкфилла. Ставить его в ДДС нельзя — квартал схлопнется в сутки."""
        d = deal(created_at=datetime(2026, 6, 3, 12, 0))
        add(d)
        tx = PayinTx(tx_hash='hn', amount_usdt=1000, tx_time=None,
                     created_at=datetime(2026, 8, 14, 9, 0))
        add(tx)
        add(PayinTxUse(tx_id=tx.id, deal_id=d.id, amount_usdt=1000))
        e = by_article(tc)['payin_client_usdt'][0]
        assert e['date'] == '2026-06-03'
        assert e['date_estimated'] is True

    def test_payin_tx_with_time_is_exact(self, tc):
        d = deal(created_at=datetime(2026, 6, 3, 12, 0))
        add(d)
        tx = PayinTx(tx_hash='he', amount_usdt=1000,
                     tx_time=datetime(2026, 6, 4, 9, 0),
                     created_at=datetime(2026, 8, 14, 9, 0))
        add(tx)
        add(PayinTxUse(tx_id=tx.id, deal_id=d.id, amount_usdt=1000))
        e = by_article(tc)['payin_client_usdt'][0]
        assert e['date'] == '2026-06-04'
        assert e['date_estimated'] is False

    def test_cash_purchase_and_card_topup_are_transfers(self, tc):
        card = BankCard(bank_name='SCB')
        add(card)
        add(CashBatch(amount_thb=100000, cost_usdt=3000, purchase_rate=33.3,
                      remaining_thb=100000, founder_name='Андрей',
                      created_at=datetime(2026, 8, 9, 10, 0)),
            CardTopup(card_id=card.id, amount_thb=50000, cost_usdt=1500,
                      purchase_rate=33.3, created_at=datetime(2026, 8, 9, 11, 0)))
        arts = by_article(tc)
        cp = arts['cash_purchase'][0]
        assert cp['flow'] == 'transfer'
        assert (cp['amount'], cp['currency'], cp['account']) == (3000, 'USDT', 'usdt')
        assert (cp['to_amount'], cp['to_currency'], cp['to_account']) == (100000, 'THB', 'cash_thb')
        assert arts['card_topup'][0]['to_account'] == 'card_thb'

    def test_referral_payout_uses_paid_date(self, tc):
        d = deal()
        d.agents.append(DealAgent(name='Теодор', tier=1, payout_usdt=15, paid=True,
                                  paid_at=datetime(2026, 8, 20, 15, 0)))
        add(d)
        e = by_article(tc)['referral_payout'][0]
        assert e['date'] == '2026-08-20'
        assert (e['flow'], e['amount']) == ('out', 15)
        assert e['counterparty'] == 'Теодор'

    def test_unpaid_referral_not_in_cashflow(self, tc):
        d = deal()
        d.agents.append(DealAgent(name='Теодор', tier=1, payout_usdt=15, paid=False))
        add(d)
        assert 'referral_payout' not in by_article(tc)


class TestNoDoubleCounting:
    def test_founder_payout_counted_once_at_reimbursement(self, tc):
        """Фаундер выдал свои баты: с наших счетов ушло только возмещение."""
        d = deal(payout_source=PayOutSource.FOUNDER_PERSONAL, payout_founder_name='Андрей',
                 cash_batch_id=None)
        add(d)
        add(Reimbursement(founder_name='Андрей', amount_usdt=950, kind='manual',
                          created_at=datetime(2026, 8, 15, 10, 0)))
        arts = by_article(tc)
        assert arts['payout_client_thb'][0]['flow'] == 'external'
        assert arts['payout_client_thb'][0]['account'] == 'founder'
        assert arts['founder_reimbursement'][0]['flow'] == 'out'
        # Операционный отток — только возмещение, баты фаундера в итог не идут
        t = tc.get('/api/finance/cashflow').get_json()['totals']['all']
        assert t['out'].get('THB') is None
        assert t['out']['USDT'] == 950

    def test_auto_reimbursement_excluded(self, tc):
        """Автозачёт долга: приход упал на тот же кошелёк, деньги не двигались."""
        add(Reimbursement(founder_name='Андрей', amount_usdt=500, kind='auto',
                          created_at=datetime(2026, 8, 15, 10, 0)))
        assert 'founder_reimbursement' not in by_article(tc)

    def test_allocation_wins_over_flat_deal_amount(self, tc):
        """У сделки с аллокацией выдача берётся из неё — не дважды."""
        d = deal()
        add(d)
        add(CashAllocation(deal_id=d.id, batch_id=1, amount_thb=32000,
                           cost_usdt=950, batch_rate=33.6,
                           created_at=datetime(2026, 8, 11, 10, 0)))
        rows = by_article(tc)['payout_client_thb']
        assert len(rows) == 1
        assert rows[0]['date'] == '2026-08-11'
        assert rows[0]['date_estimated'] is False

    def test_flat_amount_used_when_no_allocation(self, tc):
        add(deal())
        rows = by_article(tc)['payout_client_thb']
        assert len(rows) == 1
        assert rows[0]['date_estimated'] is True
        assert rows[0]['date'] == '2026-08-10'

    def test_transfers_excluded_from_operating_total(self, tc):
        add(SberIncome(uuid='u1', operation_date='2026-08-05T10:00:00',
                       amount_rub=250000, payer='П'),
            SberDebit(uuid='d1', operation_date='2026-08-06T10:00:00',
                      amount_rub=240000, payee='БРАЙТУМ', kind='broker'))
        t = tc.get('/api/finance/cashflow').get_json()['totals']['all']
        assert t['in']['RUB'] == 250000
        assert t['out'].get('RUB') is None      # рубли брокеру — перекладывание
        assert t['net']['RUB'] == 250000


class TestRealty:
    def test_leasehold_two_legs(self, tc):
        d = deal(id=2, deal_kind='mf_realty', invoice_amount_thb=16742400,
                 payout_amount_thb=None, realty_purpose='Clover B22',
                 payout_tx_hashes=json.dumps([
                     {'hash': 'abc', 'amount_usdt': 508827.76, 'date': '2026-08-04T10:00:00'}]))
        add(d)
        arts = by_article(tc)
        send = arts['realty_send'][0]
        assert send['date'] == '2026-08-04'
        assert (send['flow'], send['account'], send['to_account']) == ('transfer', 'usdt', 'mf_corp')
        dev = arts['payout_developer'][0]
        assert (dev['flow'], dev['amount'], dev['currency']) == ('out', 16742400, 'THB')
        assert dev['product'] == 'mf_realty'

    def test_freehold_developer_in_usd(self, tc):
        add(deal(id=3, deal_kind='mf_freehold', transfer_sent_usd=98500,
                 payout_amount_thb=None, realty_purpose='Layan A5'))
        dev = by_article(tc)['payout_developer'][0]
        assert (dev['amount'], dev['currency'], dev['product']) == (98500, 'USD', 'mf_freehold')

    def test_realty_has_no_client_thb_payout(self, tc):
        """У недвижимости баты клиенту не выдают — строки быть не должно."""
        add(deal(id=2, deal_kind='mf_realty', invoice_amount_thb=1000,
                 payout_amount_thb=32000))
        assert 'payout_client_thb' not in by_article(tc)


class TestBreakdownsAndFilters:
    def _seed(self):
        add(SberIncome(uuid='u1', operation_date='2026-07-05T10:00:00',
                       amount_rub=100000, payer='П'),
            SberIncome(uuid='u2', operation_date='2026-08-05T10:00:00',
                       amount_rub=250000, payer='П'),
            deal(), deal(id=2, deal_kind='mf_freehold', transfer_sent_usd=98500,
                         payout_amount_thb=None))

    def test_by_product(self, tc):
        self._seed()
        t = tc.get('/api/finance/cashflow').get_json()['totals']['by_product']
        assert t['mf_freehold']['out']['USD'] == 98500
        assert t['exchange']['out']['THB'] == 32000
        assert t['unassigned']['in']['RUB'] == 350000

    def test_date_range(self, tc):
        self._seed()
        d = tc.get('/api/finance/cashflow?date_from=2026-08-01').get_json()
        assert all(e['date'] >= '2026-08-01' for e in d['events'])
        assert d['totals']['all']['in']['RUB'] == 250000

    def test_product_and_flow_filters(self, tc):
        self._seed()
        d = tc.get('/api/finance/cashflow?product=mf_freehold').get_json()
        assert {e['product'] for e in d['events']} == {'mf_freehold'}
        d = tc.get('/api/finance/cashflow?flow=in').get_json()
        assert {e['flow'] for e in d['events']} == {'in'}

    def test_estimated_dates_reported(self, tc):
        self._seed()
        t = tc.get('/api/finance/cashflow').get_json()['totals']
        assert t['events_date_estimated'] >= 1
        assert t['events_total'] == len(tc.get('/api/finance/cashflow').get_json()['events'])

    def test_coverage_shows_unassigned_money(self, tc):
        """Счёт Сбера общий с другими потоками компании: приход без привязки
        к сделке — не выручка продукта, и это должно быть видно сразу."""
        self._seed()
        cov = tc.get('/api/finance/cashflow').get_json()['totals']['coverage']
        assert cov['unassigned']['in']['RUB'] == 350000
        assert cov['events_total'] > cov['unassigned']['events']

    def test_bad_params(self, tc):
        assert tc.get('/api/finance/cashflow?date_from=05.08.2026').status_code == 400
        assert tc.get('/api/finance/cashflow?product=zzz').status_code == 400
        assert tc.get('/api/finance/cashflow?flow=zzz').status_code == 400
        assert tc.get('/api/finance/cashflow?article=zzz').status_code == 400

    def test_summary_by_month(self, tc):
        self._seed()
        d = tc.get('/api/finance/summary').get_json()
        periods = {p['period']: p for p in d['periods']}
        assert periods['2026-07']['all']['in']['RUB'] == 100000
        assert periods['2026-08']['all']['in']['RUB'] == 250000

    def test_summary_by_day(self, tc):
        self._seed()
        d = tc.get('/api/finance/summary?group=day').get_json()
        assert {p['period'] for p in d['periods']} >= {'2026-07-05', '2026-08-05'}
        assert tc.get('/api/finance/summary?group=year').status_code == 400

    def test_csv(self, tc):
        self._seed()
        resp = tc.get('/api/finance/cashflow?format=csv')
        text = resp.get_data(as_text=True)
        assert text.startswith('﻿дата;статья;поток;сумма;валюта;счёт')
        assert 'Приход от клиента, ₽' in text


class TestFinanceKeyScope:
    KEY = 'fin-test-key'

    @pytest.fixture
    def cli(self, monkeypatch):
        A.app.config['TESTING'] = True
        monkeypatch.delenv('LOCAL_NO_AUTH', raising=False)
        monkeypatch.setenv('SERVICE_API_KEY_RO_FINANCE', self.KEY)
        with A.app.test_client() as c:
            yield c

    def get(self, cli, path):
        return cli.get(path, headers={'X-Api-Key': self.KEY})

    def test_finance_and_ledger_allowed(self, cli):
        assert self.get(cli, '/api/finance/cashflow').status_code == 200
        assert self.get(cli, '/api/finance/summary').status_code == 200
        assert self.get(cli, '/api/deals/ledger').status_code == 200

    def test_client_data_out_of_scope(self, cli):
        """Финансисту не нужны клиентская база, KYC и переписка."""
        for path in ('/api/deals', '/api/clients', '/api/kyc/list',
                     '/api/referrers', '/api/wallets'):
            r = self.get(cli, path)
            assert r.status_code == 403, path
            assert r.get_json()['error'] == 'read_only_key_scope'

    def test_write_forbidden(self, cli):
        r = cli.post('/api/deals', headers={'X-Api-Key': self.KEY}, json={})
        assert r.status_code == 403
        assert r.get_json()['error'] == 'read_only_key'

    def test_founder_key_also_sees_finance(self, cli, monkeypatch):
        monkeypatch.setenv('SERVICE_API_KEY_RO', 'ro-founder')
        r = cli.get('/api/finance/cashflow', headers={'X-Api-Key': 'ro-founder'})
        assert r.status_code == 200
