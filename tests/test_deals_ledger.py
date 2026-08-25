"""
Сводный леджер сделок — /api/deals/ledger.

Проверяем то, ради чего ручка сделана: приход и выдача с подписанными методами,
разделение обмен / лизхолд / фрихолд, траты на рефералов без двойного счёта,
итоги в разрезах и CSV-выгрузка.

Запуск: cd Dev/CalcCRM && python -m pytest tests/test_deals_ledger.py -v
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('SECRET_KEY', 'test-secret-key-for-pytest')
os.environ['REESTR_SYNC_ENABLED'] = '0'

import pytest

import app as A
from app import (AdminUser, BankCard, Deal, DealAgent, DealStatus, DealType,
                 Client, PayInMethod, PayOutMethod, PayOutSource, get_session)


@pytest.fixture(autouse=True)
def clean_db():
    s = get_session()
    try:
        s.query(DealAgent).delete()
        s.query(Deal).delete()
        s.query(Client).delete()
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
            a = AdminUser(username='ledger_admin', display_name='T',
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


def add(*deals):
    s = get_session()
    try:
        for d in deals:
            s.add(d)
        s.commit()
    finally:
        s.close()


def exchange_deal(**over):
    """Обычный обмен: рубли по СБП → баты наличными в офисе."""
    d = Deal(
        id=1, client_name='Иван', manager_name='Валера',
        deal_type=DealType.PAY_OUT, status=DealStatus.COMPLETED,
        created_at=datetime(2026, 8, 10, 12, 0),
        payin_method=PayInMethod.SBER_WL,
        payin_amount_rub=100000, payin_amount_usdt=1000, payin_rate_rub_usdt=100,
        payout_method=PayOutMethod.OFFICE, payout_source=PayOutSource.CASH_BATCH,
        cash_batch_id=7, payout_amount_thb=32000, payout_amount_usdt=950,
        profit_usdt=50, profit_percent=5.26, net_profit_usdt=35,
    )
    for k, v in over.items():
        setattr(d, k, v)
    return d


def leasehold_deal(**over):
    d = Deal(
        id=2, client_name='Игорь', deal_kind='mf_realty',
        deal_type=DealType.PAY_IN, status=DealStatus.COMPLETED,
        created_at=datetime(2026, 8, 11, 12, 0),
        payin_method=PayInMethod.CRYPTO_DIRECT, payin_amount_usdt=512000,
        realty_purpose='Clover Residence B22',
        invoice_amount_thb=16742400, buy_rate_thb_usdt=33.20,
        sell_rate_thb_usdt=32.702, company_percent=0.9,
        company_sent_thb=16893081.60, company_fee_thb=150681.60,
        company_fee_usdt=4538.60, payout_amount_usdt=508827.76,
        profit_usdt=3172.24, crypto_remainder_usdt=551.02, net_profit_usdt=5089.62,
    )
    for k, v in over.items():
        setattr(d, k, v)
    return d


def freehold_deal(**over):
    d = Deal(
        id=3, client_name='Пётр', deal_kind='mf_freehold',
        deal_type=DealType.PAY_IN, status=DealStatus.COMPLETED,
        created_at=datetime(2026, 8, 12, 12, 0),
        payin_method=PayInMethod.CRYPTO_DIRECT, payin_amount_usdt=100000,
        realty_purpose='Layan Verde A5',
        invoice_amount_usd=98000, transfer_sent_usd=98500,
        transfer_fee_percent=0.5, transfer_fee_fixed_usd=30,
        transfer_fee_usd=522.5, transfer_arrive_usd=97977.5,
        payout_amount_usdt=98500, profit_usdt=1500, net_profit_usdt=1500,
    )
    for k, v in over.items():
        setattr(d, k, v)
    return d


def rows_by_id(payload):
    return {r['id']: r for r in payload['deals']}


class TestLedgerRows:
    def test_payin_and_payout_are_labeled(self, tc):
        add(exchange_deal())
        data = tc.get('/api/deals/ledger').get_json()
        r = rows_by_id(data)[1]
        assert r['kind'] == 'exchange'
        assert r['kind_label'] == 'обычный обмен'
        assert r['pay_in']['method'] == 'sber_wl'
        assert r['pay_in']['method_label'] == 'СБП'
        assert r['pay_in']['amount_rub'] == 100000
        assert r['pay_in']['amount_usdt'] == 1000
        assert r['pay_out']['method_label'] == 'офис'
        assert r['pay_out']['source_label'] == 'касса (партия налички)'
        assert r['pay_out']['source_name'] == 'партия наличных #7'
        assert r['pay_out']['amount_thb'] == 32000
        assert r['pay_out']['cost_usdt'] == 950
        assert r['pay_out']['rate_thb_usdt'] == pytest.approx(33.6842, abs=1e-3)

    def test_card_payout_named_by_bank(self, tc):
        s = get_session()
        try:
            card = BankCard(bank_name='SCB', card_name='основная', balance_thb=0)
            s.add(card)
            s.commit()
            card_id = card.id
        finally:
            s.close()
        add(exchange_deal(payout_source=PayOutSource.BANK_CARD, bank_card_id=card_id,
                          cash_batch_id=None))
        r = rows_by_id(tc.get('/api/deals/ledger').get_json())[1]
        assert r['pay_out']['source_name'] == 'SCB основная'

    def test_leasehold_leg(self, tc):
        add(leasehold_deal())
        r = rows_by_id(tc.get('/api/deals/ledger').get_json())[2]
        assert r['kind_label'].startswith('недвижимость: лизхолд')
        assert r['realty']['invoice_thb'] == 16742400
        assert r['realty']['company_fee_thb'] == 150681.60
        assert r['realty']['purpose'] == 'Clover Residence B22'
        # Валовая прибыль лизхолда = крипта + комиссия батами
        assert r['money']['gross_profit_usdt'] == pytest.approx(3172.24 + 4538.60, abs=0.01)

    def test_freehold_leg(self, tc):
        add(freehold_deal())
        r = rows_by_id(tc.get('/api/deals/ledger').get_json())[3]
        assert r['kind_label'].startswith('недвижимость: фрихолд')
        assert r['realty']['invoice_usd'] == 98000
        assert r['realty']['transfer_arrive_usd'] == 97977.5
        assert 'invoice_thb' not in r['realty']

    def test_exchange_has_no_realty_block(self, tc):
        add(exchange_deal())
        assert rows_by_id(tc.get('/api/deals/ledger').get_json())[1]['realty'] is None

    def test_multi_method_payin_listed(self, tc):
        """Доплата другим методом — в леджере видны оба метода."""
        import json as _json
        add(exchange_deal(
            payin_amount_rub=120000, payin_amount_usdt=1200,
            payin_extra=_json.dumps([{'method': 'partners_cash', 'amount_rub': 20000,
                                      'amount_usdt': 200, 'rate_rub_usdt': 100}]),
        ))
        r = rows_by_id(tc.get('/api/deals/ledger').get_json())[1]
        assert r['pay_in']['methods'] == ['sber_wl', 'partners_cash']
        assert r['pay_in']['methods_label'] == 'СБП + наличные'
        assert [p['amount_usdt'] for p in r['pay_in']['parts']] == [1000, 200]


class TestReferralCost:
    def test_single_referrer_counted_once(self, tc):
        """Одиночный реферер зеркалится в deal_agents — считаем один раз."""
        d = exchange_deal(referrer_name='Теодор', referrer_percent=30,
                          referrer_payout_usdt=15, net_profit_usdt=35)
        d.agents.append(DealAgent(name='Теодор', tier=1, comp_model='revshare',
                                  percent=30, payout_usdt=15, paid=False))
        add(d)
        r = rows_by_id(tc.get('/api/deals/ledger').get_json())[1]
        assert r['money']['referral_cost_usdt'] == 15
        assert r['referral']['unpaid_usdt'] == 15
        assert len(r['referral']['agents']) == 1

    def test_cascade_agents_summed(self, tc):
        d = exchange_deal(referrer_name='Теодор', referrer_payout_usdt=15)
        d.agents.append(DealAgent(name='Теодор', tier=1, percent=30, payout_usdt=15, paid=True))
        d.agents.append(DealAgent(name='Андрей', tier=2, percent=10, payout_usdt=1.5, paid=False))
        add(d)
        r = rows_by_id(tc.get('/api/deals/ledger').get_json())[1]
        assert r['money']['referral_cost_usdt'] == 16.5
        assert r['referral']['unpaid_usdt'] == 1.5

    def test_legacy_deal_without_agents(self, tc):
        add(exchange_deal(referrer_name='Старый', referrer_payout_usdt=20, referrer_paid=True))
        r = rows_by_id(tc.get('/api/deals/ledger').get_json())[1]
        assert r['money']['referral_cost_usdt'] == 20
        assert r['referral']['unpaid_usdt'] == 0


class TestTotalsAndFilters:
    def test_totals_by_kind(self, tc):
        add(exchange_deal(), leasehold_deal(), freehold_deal())
        t = tc.get('/api/deals/ledger').get_json()['totals']
        assert t['all']['deals'] == 3
        assert set(t['by_kind']) == {'exchange', 'mf_realty', 'mf_freehold'}
        assert t['by_kind']['exchange']['deals'] == 1
        assert t['by_payout_method']['office']['deals'] == 1
        assert t['by_payin_method']['crypto_direct']['deals'] == 2

    def test_referral_unpaid_total(self, tc):
        d = exchange_deal(referrer_name='Т', referrer_payout_usdt=15)
        d.agents.append(DealAgent(name='Т', tier=1, payout_usdt=15, paid=False))
        add(d, leasehold_deal())
        t = tc.get('/api/deals/ledger').get_json()['totals']
        assert t['referral_unpaid_usdt'] == 15
        assert t['all']['referral_cost_usdt'] == 15

    def test_kind_filter(self, tc):
        add(exchange_deal(), leasehold_deal(), freehold_deal())
        assert tc.get('/api/deals/ledger?deal_kind=realty').get_json()['total'] == 2
        assert tc.get('/api/deals/ledger?deal_kind=exchange').get_json()['total'] == 1
        assert tc.get('/api/deals/ledger?deal_kind=mf_freehold').get_json()['total'] == 1

    def test_pending_excluded_by_default(self, tc):
        add(exchange_deal(), leasehold_deal(id=2, status=DealStatus.PENDING))
        assert tc.get('/api/deals/ledger').get_json()['total'] == 1
        assert tc.get('/api/deals/ledger?status=all').get_json()['total'] == 2

    def test_test_deals_hidden(self, tc):
        add(exchange_deal(is_test=True))
        assert tc.get('/api/deals/ledger').get_json()['total'] == 0
        assert tc.get('/api/deals/ledger?include_test=1').get_json()['total'] == 1

    def test_date_range(self, tc):
        add(exchange_deal(), leasehold_deal())
        data = tc.get('/api/deals/ledger?date_from=2026-08-11&date_to=2026-08-11').get_json()
        assert [r['id'] for r in data['deals']] == [2]

    def test_bad_params_rejected(self, tc):
        assert tc.get('/api/deals/ledger?deal_kind=zzz').status_code == 400
        assert tc.get('/api/deals/ledger?date_from=10.08.2026').status_code == 400
        assert tc.get('/api/deals/ledger?status=zzz').status_code == 400

    def test_limit_does_not_break_totals(self, tc):
        add(exchange_deal(), leasehold_deal(), freehold_deal())
        data = tc.get('/api/deals/ledger?limit=1').get_json()
        assert data['count'] == 1 and data['total'] == 3
        assert data['totals']['all']['deals'] == 3


class TestCsv:
    def test_csv_export(self, tc):
        add(exchange_deal(), leasehold_deal())
        resp = tc.get('/api/deals/ledger?format=csv')
        assert resp.status_code == 200
        text = resp.get_data(as_text=True)
        assert text.startswith('﻿')
        lines = text.strip().split('\r\n')
        assert lines[0].startswith('﻿id;дата;статус;тип сделки')
        assert len(lines) == 3
        assert 'обычный обмен' in text and 'Clover Residence B22' in text


class TestAccess:
    def test_readonly_key_allowed(self, tc, monkeypatch):
        monkeypatch.delenv('LOCAL_NO_AUTH', raising=False)
        monkeypatch.setenv('SERVICE_API_KEY_RO', 'ro-ledger-key')
        with A.app.test_client() as c:
            r = c.get('/api/deals/ledger', headers={'X-Api-Key': 'ro-ledger-key'})
            assert r.status_code == 200

    def test_anonymous_denied(self, monkeypatch):
        monkeypatch.delenv('LOCAL_NO_AUTH', raising=False)
        with A.app.test_client() as c:
            assert c.get('/api/deals/ledger').status_code == 401
