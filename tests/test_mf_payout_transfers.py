"""
Фактические переводы в MF Corp: куда и сколько реально ушло.

Расчёт по курсу — модель, она всегда ровная. Реальность даёт другое: комиссии
сети, округление курса, отправка частями (кейс Clover — 5×100 000 + 8 828).
Если себестоимость остаётся модельной, расхождение растворяется и сверить
отправку с блокчейном нечем. Поэтому отмеченные переводы становятся
себестоимостью, а разница показывается явно.

Запуск: cd Dev/CalcCRM && python -m pytest tests/test_mf_payout_transfers.py -v
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ['SECRET_KEY'] = 'test-secret-key-for-pytest'

import json
import app as A
from app import (compute_mf_realty, _normalize_payout_transfers, _payout_hash_list,
                 _payout_transfers_total, get_session, Deal, Client, DealAgent,
                 AdminUser, get_used_transaction_hashes)

# Числа сделки #458 (Clover Residence B22)
INVOICE = 16742400
BUY = 33.20
PAYIN = 512000
# 5 переводов по 100 000 + остаток
CLOVER_PARTS = [{'hash': f'h{i}', 'amount_usdt': 100000, 'to_address': 'TMFcorp1234567890',
                 'date': '04.08.2026'} for i in range(5)]
CLOVER_PARTS.append({'hash': 'h5', 'amount_usdt': 8828, 'to_address': 'TMFcorp1234567890',
                     'date': '04.08.2026'})


# ── Нормализация ─────────────────────────────────────────────────────────

class TestNormalize:
    def test_keeps_address_and_date(self):
        """Адрес и дата нужны в UI — иначе видно «сколько», но не «куда»."""
        out = _normalize_payout_transfers([
            {'hash': 'aa', 'amount_usdt': 100, 'to_address': 'TAddr', 'date': '04.08.2026'}])
        assert out == [{'hash': 'aa', 'amount_usdt': 100.0,
                        'to_address': 'TAddr', 'date': '04.08.2026'}]

    def test_accepts_tx_hash_key(self):
        out = _normalize_payout_transfers([{'tx_hash': 'bb', 'amount_usdt': '50'}])
        assert out[0]['hash'] == 'bb' and out[0]['amount_usdt'] == 50.0

    def test_plain_strings(self):
        assert _normalize_payout_transfers(['aa', ' bb ']) == [
            {'hash': 'aa', 'amount_usdt': None, 'to_address': '', 'date': ''},
            {'hash': 'bb', 'amount_usdt': None, 'to_address': '', 'date': ''}]

    def test_duplicates_dropped(self):
        assert len(_normalize_payout_transfers([{'hash': 'aa'}, {'hash': 'aa'}])) == 1

    def test_garbage_ignored(self):
        assert _normalize_payout_transfers([None, 42, {'hash': ''}, {}]) == []

    def test_bad_amount_becomes_none(self):
        assert _normalize_payout_transfers([{'hash': 'aa', 'amount_usdt': 'много'}])[0]['amount_usdt'] is None

    def test_empty_input(self):
        assert _normalize_payout_transfers(None) == []


# ── Сумма и хэши ─────────────────────────────────────────────────────────

class TestTotals:
    def test_total_of_clover_parts(self):
        d = Deal(payout_tx_hashes=json.dumps(CLOVER_PARTS))
        assert _payout_transfers_total(d) == 508828.00

    def test_total_none_without_transfers(self):
        assert _payout_transfers_total(Deal()) is None

    def test_total_none_when_amounts_missing(self):
        """Хэши без сумм — считать нечего, остаёмся на расчёте по курсу."""
        d = Deal(payout_tx_hashes=json.dumps([{'hash': 'aa'}, {'hash': 'bb'}]))
        assert _payout_transfers_total(d) is None

    def test_broken_json_does_not_crash(self):
        assert _payout_transfers_total(Deal(payout_tx_hashes='{{')) is None
        assert _payout_hash_list(Deal(payout_tx_hashes='{{')) == []

    def test_hash_list(self):
        d = Deal(payout_tx_hashes=json.dumps(CLOVER_PARTS))
        assert _payout_hash_list(d) == ['h0', 'h1', 'h2', 'h3', 'h4', 'h5']


# ── Расчёт ───────────────────────────────────────────────────────────────

class TestCompute:
    def test_actual_becomes_cost(self):
        r = compute_mf_realty(INVOICE, BUY, PAYIN, company_percent=0.9, agents=[],
                              actual_cost_usdt=508828.00)
        assert r['cost_usdt'] == 508828.00
        assert r['computed_cost_usdt'] == 508827.76
        assert r['cost_diff_usdt'] == 0.24

    def test_crypto_profit_uses_actual(self):
        """$0.24 разницы съедают крипту, а не растворяются в модели."""
        model = compute_mf_realty(INVOICE, BUY, PAYIN, company_percent=0.9, agents=[])
        fact = compute_mf_realty(INVOICE, BUY, PAYIN, company_percent=0.9, agents=[],
                                 actual_cost_usdt=508828.00)
        assert round(model['crypto_profit_usdt'] - fact['crypto_profit_usdt'], 2) == 0.24

    def test_without_transfers_diff_is_zero(self):
        r = compute_mf_realty(INVOICE, BUY, PAYIN, company_percent=0.9, agents=[])
        assert r['cost_diff_usdt'] == 0
        assert r['cost_usdt'] == r['computed_cost_usdt']

    def test_company_fee_untouched_by_fact(self):
        """Комиссия компании живёт в батах — сетевые потери её не меняют."""
        r = compute_mf_realty(INVOICE, BUY, PAYIN, company_percent=0.9, agents=[],
                              actual_cost_usdt=508828.00)
        assert abs(r['company_fee_usdt'] - 4538.60) < 0.02

    def test_overpay_visible_as_negative_crypto(self):
        """Ушло сильно больше расчёта — прибыль в крипте уходит в минус, а не молчит."""
        r = compute_mf_realty(INVOICE, BUY, PAYIN, company_percent=0.9, agents=[],
                              actual_cost_usdt=513000)
        assert r['crypto_profit_usdt'] < 0
        assert r['cost_diff_usdt'] > 0


# ── Сохранение сделки ────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clean_db():
    s = get_session()
    try:
        s.query(DealAgent).delete(); s.query(Deal).delete(); s.query(Client).delete()
        s.commit()
    finally:
        s.close()
    yield


@pytest.fixture
def tc(monkeypatch):
    A.app.config['TESTING'] = True
    monkeypatch.setattr(A, 'sync_realty_deal_to_gsheet', lambda d: {'ok': False})
    monkeypatch.setattr(A, '_send_deal_telegram', lambda d: None)
    s = get_session()
    try:
        a = s.query(AdminUser).first()
        if not a:
            a = AdminUser(username='test_admin', display_name='T',
                          password_hash=AdminUser.hash_password('x'))
            s.add(a); s.commit()
        aid = a.id
    finally:
        s.close()
    with A.app.test_client() as c:
        with c.session_transaction() as sess:
            sess['user_id'] = aid
        yield c


def create_payload(**over):
    p = {'client_name': 'Clover Client', 'deal_kind': 'mf_realty',
         'deal_type': 'pay_in', 'payin_method': 'crypto_direct',
         'payin_amount_usdt': PAYIN, 'invoice_amount_thb': INVOICE,
         'buy_rate_thb_usdt': BUY, 'company_percent': 0.9,
         'payout_tx_hashes': CLOVER_PARTS}
    p.update(over)
    return p


class TestDealSave:
    def test_cost_from_transfers(self, tc):
        r = tc.post('/api/deals', json=create_payload())
        assert r.json['success']
        d = r.json['deal']
        assert d['payout_amount_usdt'] == 508828.00
        assert len(d['payout_tx_hashes']) == 6
        assert d['payout_tx_hashes'][0]['to_address'] == 'TMFcorp1234567890'

    def test_first_hash_mirrored_to_single_field(self, tc):
        """Карточка и выгрузка читают payout_tx_hash — не оставляем его пустым."""
        d = tc.post('/api/deals', json=create_payload()).json['deal']
        assert d['payout_tx_hash'] == 'h0'

    def test_hashes_become_used(self, tc):
        """Один перевод нельзя привязать к двум сделкам."""
        tc.post('/api/deals', json=create_payload())
        s = get_session()
        try:
            assert 'h5' in get_used_transaction_hashes(s)
        finally:
            s.close()

    def test_edit_replaces_transfers(self, tc):
        did = tc.post('/api/deals', json=create_payload()).json['deal']['id']
        r = tc.put(f'/api/deals/{did}', json={
            'payout_tx_hashes': [{'hash': 'z1', 'amount_usdt': 508000, 'to_address': 'TOther'}]})
        assert r.json['success']
        d = tc.get(f'/api/deals/{did}').json['deal']
        assert _payout_hash_list(Deal(payout_tx_hashes=json.dumps(d['payout_tx_hashes']))) == ['z1']
        assert d['payout_amount_usdt'] == 508000

    def test_clearing_transfers_returns_to_model(self, tc):
        did = tc.post('/api/deals', json=create_payload()).json['deal']['id']
        tc.put(f'/api/deals/{did}', json={'payout_tx_hashes': []})
        d = tc.get(f'/api/deals/{did}').json['deal']
        assert d['payout_tx_hashes'] is None
        assert abs(d['payout_amount_usdt'] - 508827.76) < 0.02

    def test_untouched_field_survives_other_edits(self, tc):
        """Правка процента не должна стирать отмеченные переводы."""
        did = tc.post('/api/deals', json=create_payload()).json['deal']['id']
        tc.put(f'/api/deals/{did}', json={'company_percent': 1.0})
        d = tc.get(f'/api/deals/{did}').json['deal']
        assert len(d['payout_tx_hashes']) == 6


# ── Превью и выгрузка ────────────────────────────────────────────────────

class TestPreviewAndExport:
    def test_preview_accounts_for_transfers(self, tc):
        r = tc.post('/api/deals/mf-realty/preview', json={
            'invoice_amount_thb': INVOICE, 'buy_rate_thb_usdt': BUY,
            'payin_amount_usdt': PAYIN, 'company_percent': 0.9,
            'payout_tx_hashes': CLOVER_PARTS})
        res = r.json['result']
        assert res['cost_usdt'] == 508828.00
        assert res['cost_diff_usdt'] == 0.24

    def test_preview_without_transfers(self, tc):
        r = tc.post('/api/deals/mf-realty/preview', json={
            'invoice_amount_thb': INVOICE, 'buy_rate_thb_usdt': BUY,
            'payin_amount_usdt': PAYIN, 'company_percent': 0.9})
        assert r.json['result']['cost_diff_usdt'] == 0

    def test_export_hash_column_shows_payout(self):
        """В колонку «хеш транзакции» идёт отправка — сверяют именно её."""
        d = Deal(id=1, client_name='x', deal_kind='mf_realty',
                 invoice_amount_thb=INVOICE, buy_rate_thb_usdt=BUY,
                 payin_amount_usdt=PAYIN, company_percent=0.9,
                 company_sent_thb=16893081.60, company_fee_thb=150681.60,
                 company_fee_usdt=4538.60, payout_amount_usdt=508828.00,
                 profit_usdt=3172.00, crypto_remainder_usdt=551.02,
                 net_profit_usdt=5089.62,
                 payin_tx_hashes=json.dumps([{'hash': 'in1', 'amount_usdt': PAYIN}]),
                 payout_tx_hashes=json.dumps(CLOVER_PARTS))
        row = dict(zip(A.GSHEET_REALTY_HEADERS, A.build_realty_rows(d)[0]))
        assert row['хеш транзакции'].startswith('h0, h1')
        assert 'in1' not in row['хеш транзакции']

    def test_export_falls_back_to_payin_hashes(self):
        d = Deal(id=2, client_name='x', deal_kind='mf_realty',
                 invoice_amount_thb=INVOICE, buy_rate_thb_usdt=BUY,
                 payin_amount_usdt=PAYIN, company_percent=0.9,
                 company_sent_thb=16893081.60, company_fee_thb=150681.60,
                 company_fee_usdt=4538.60, payout_amount_usdt=508827.76,
                 payin_tx_hashes=json.dumps([{'hash': 'in1', 'amount_usdt': PAYIN}]))
        row = dict(zip(A.GSHEET_REALTY_HEADERS, A.build_realty_rows(d)[0]))
        assert row['хеш транзакции'] == 'in1'


class TestTelegram:
    def test_transfers_listed(self):
        d = Deal(id=458, client_name='igor', deal_kind='mf_realty',
                 invoice_amount_thb=INVOICE, payin_amount_usdt=PAYIN,
                 company_sent_thb=16893081.60, company_fee_thb=150681.60,
                 company_fee_usdt=4538.60, company_percent=0.9,
                 payout_amount_usdt=508828.00, crypto_remainder_usdt=551.02,
                 net_profit_usdt=5089.62, payout_tx_hashes=json.dumps(CLOVER_PARTS))
        t = A._mf_realty_telegram_text(d)
        assert 'Переводы (6)' in t
        assert 'Итого ушло: $508,828.00' in t
        assert 'TMFcorp123' in t

    def test_no_transfers_no_block(self):
        d = Deal(id=459, client_name='igor', deal_kind='mf_realty',
                 invoice_amount_thb=INVOICE, payin_amount_usdt=PAYIN,
                 company_sent_thb=16893081.60, company_fee_usdt=4538.60,
                 net_profit_usdt=5089.62)
        assert 'Переводы (' not in A._mf_realty_telegram_text(d)
