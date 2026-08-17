"""
Выгрузка сделок через MF Corp в таблицу «Cделки недвижимость» и текст в Telegram.

Сеть не трогаем: gspread подменяется фейком, проверяем что именно ушло бы
в лист — порядок колонок, ленивое создание листа месяца, upsert по CRM ID.

Запуск: cd Dev/CalcCRM && python -m pytest tests/test_realty_export.py -v
"""
import pytest
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ['SECRET_KEY'] = 'test-secret-key-for-pytest'

import app as A
from app import (get_session, Deal, Client, DealAgent, AdminUser,
                 GSHEET_REALTY_HEADERS, realty_month_sheet_name)


# ── Фейковый Google Sheets ────────────────────────────────────────────────

class FakeWS:
    def __init__(self, title, rows=None):
        self.title = title
        self.rows = rows if rows is not None else []
        self.updates = []

    def col_values(self, col):
        return [(r[col - 1] if len(r) >= col else '') for r in self.rows]

    def append_row(self, row, value_input_option=None):
        self.rows.append([str(x) for x in row])

    def update(self, rng, values, value_input_option=None):
        idx = int(''.join(c for c in rng.split(':')[0] if c.isdigit()))
        self.rows[idx - 1] = [str(x) for x in values[0]]
        self.updates.append(rng)


class FakeSheet:
    def __init__(self, titles=()):
        self.sheets = [FakeWS(t) for t in titles]
        self.added = []

    def worksheets(self):
        return list(self.sheets)

    def worksheet(self, title):
        for ws in self.sheets:
            if ws.title == title:
                return ws
        raise Exception('not found')

    def add_worksheet(self, title, rows, cols):
        ws = FakeWS(title)
        self.sheets.append(ws)
        self.added.append(title)
        return ws


class FakeClient:
    def __init__(self, sheet):
        self.sheet = sheet

    def open_by_key(self, key):
        return self.sheet


@pytest.fixture
def fake_sheet(monkeypatch):
    sheet = FakeSheet(['июль leasehold'])
    monkeypatch.setattr(A, 'get_gsheet_client', lambda: FakeClient(sheet))
    return sheet


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
def tc():
    A.app.config['TESTING'] = True
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


def make_deal(**over):
    """Сделка Clover Residence — те же числа, что сверены с таблицей."""
    d = Deal(
        id=999, client_name='igor tabachnikov', deal_kind='mf_realty',
        created_at=datetime(2026, 8, 4, 12, 0),
        payin_method=A.PayInMethod.CRYPTO_DIRECT,
        payin_amount_usdt=512000, realty_purpose='Clover Residence B22',
        invoice_amount_thb=16742400, buy_rate_thb_usdt=33.20,
        sell_rate_thb_usdt=32.702, company_percent=0.9,
        company_sent_thb=16893081.60, company_fee_thb=150681.60,
        company_fee_usdt=4538.60, payout_amount_usdt=508827.76,
        profit_usdt=3172.24, crypto_remainder_usdt=551.02,
        net_profit_usdt=5089.62, referrer_payout_usdt=2621.22,
        doc_invoice_url='https://drive/inv',
    )
    for k, v in over.items():
        setattr(d, k, v)
    return d


# ── Имя листа месяца ─────────────────────────────────────────────────────

class TestMonthSheet:
    def test_name_from_deal_date(self):
        assert realty_month_sheet_name(datetime(2026, 7, 15)) == 'июль leasehold'
        assert realty_month_sheet_name(datetime(2026, 1, 2)) == 'январь leasehold'

    def test_existing_typo_sheet_matched(self, monkeypatch):
        """На проде лист мая называется «май leeshold» — новый не создаём."""
        sheet = FakeSheet(['май leeshold'])
        ws = A._realty_find_month_worksheet(sheet, 'май leasehold')
        assert ws is not None and ws.title == 'май leeshold'

    def test_missing_month_not_matched(self):
        sheet = FakeSheet(['июль leasehold'])
        assert A._realty_find_month_worksheet(sheet, 'август leasehold') is None


# ── Строка выгрузки ──────────────────────────────────────────────────────

class TestRow:
    def test_row_length_matches_headers(self):
        assert len(A.build_realty_rows(make_deal())[0]) == len(GSHEET_REALTY_HEADERS)

    def test_key_columns(self):
        row = dict(zip(GSHEET_REALTY_HEADERS, A.build_realty_rows(make_deal())[0]))
        assert row['Назанчение'] == 'Clover Residence B22'
        assert row['дата'] == '04.08.2026'
        assert row['направление'] == 'usdt-thb'
        assert row['сумма thb'] == 16742400
        assert row['курс покупкт'] == 33.20
        assert row['приход usdt '] == 512000
        assert abs(row['cколько потратили на инвойс'] - 504289.16) < 0.02
        assert abs(row['доход Тайской компании usdt'] - 4538.60) < 0.02
        assert row['отправлено на компанию в thb'] == 16893081.60
        assert abs(row['доход'] - 7710.84) < 0.02
        assert abs(row['доход в usdt на кошельке'] - 551.02) < 0.02
        assert abs(row['чистый доход'] - 5089.62) < 0.02
        assert row['CRM ID'] == 999

    def test_percent_as_fraction(self):
        """Процент отдаём долей — лист форматирует его как проценты."""
        row = dict(zip(GSHEET_REALTY_HEADERS, A.build_realty_rows(make_deal())[0]))
        assert abs(row['процент на тайскую компанию'] - 0.009) < 1e-6

    def test_hashes_joined(self):
        d = make_deal(payin_tx_hashes='[{"hash": "aa", "amount_usdt": 1}, {"hash": "bb"}]')
        row = dict(zip(GSHEET_REALTY_HEADERS, A.build_realty_rows(d)[0]))
        assert row['хеш транзакции'] == 'aa, bb'


# ── Ленивое создание листа и upsert ──────────────────────────────────────

class TestSync:
    def test_existing_month_reused(self, fake_sheet):
        r = A.sync_realty_deal_to_gsheet(make_deal(created_at=datetime(2026, 7, 9)))
        assert r['ok'] and r['sheet'] == 'июль leasehold'
        assert r['sheet_created'] is False

    def test_new_month_sheet_created_with_headers(self, fake_sheet):
        r = A.sync_realty_deal_to_gsheet(make_deal())          # август
        assert r['sheet_created'] is True
        ws = fake_sheet.worksheet('август leasehold')
        assert ws.rows[0] == GSHEET_REALTY_HEADERS
        assert ws.rows[1][-2] == '999'
        assert ws.rows[1][-1] == '1/1'

    def test_upsert_updates_instead_of_duplicating(self, fake_sheet):
        A.sync_realty_deal_to_gsheet(make_deal())
        r2 = A.sync_realty_deal_to_gsheet(make_deal(net_profit_usdt=7777.77))
        ws = fake_sheet.worksheet('август leasehold')
        assert r2['inserted'] is False
        assert len(ws.rows) == 2, 'шапка + одна строка, дубля нет'
        assert '7777.77' in ws.rows[1]

    def test_empty_existing_month_sheet_gets_headers(self, monkeypatch):
        """Лист месяца завели руками и не заполнили — шапку дописываем сами."""
        sheet = FakeSheet(['август leasehold'])          # без шапки
        monkeypatch.setattr(A, 'get_gsheet_client', lambda: FakeClient(sheet))
        A.sync_realty_deal_to_gsheet(make_deal())
        ws = sheet.worksheet('август leasehold')
        assert ws.rows[0] == GSHEET_REALTY_HEADERS
        assert ws.rows[1][-2] == '999'
        assert ws.rows[1][-1] == '1/1'

    def test_second_deal_appends(self, fake_sheet):
        A.sync_realty_deal_to_gsheet(make_deal())
        A.sync_realty_deal_to_gsheet(make_deal(id=1000))
        assert len(fake_sheet.worksheet('август leasehold').rows) == 3

    def test_summary_sheet_gets_every_row(self, fake_sheet):
        A.sync_realty_deal_to_gsheet(make_deal(created_at=datetime(2026, 7, 9)))
        A.sync_realty_deal_to_gsheet(make_deal(id=1000, created_at=datetime(2026, 8, 4)))
        all_ws = fake_sheet.worksheet(A.GSHEET_REALTY_ALL)
        assert len(all_ws.rows) == 3, 'шапка + строки обоих месяцев'

    def test_no_credentials_does_not_raise(self, monkeypatch):
        monkeypatch.setattr(A, 'get_gsheet_client', lambda: None)
        assert A.sync_realty_deal_to_gsheet(make_deal())['ok'] is False

    def test_sheet_error_does_not_raise(self, monkeypatch):
        class Boom:
            def open_by_key(self, k): raise RuntimeError('quota')
        monkeypatch.setattr(A, 'get_gsheet_client', lambda: Boom())
        r = A.sync_realty_deal_to_gsheet(make_deal())
        assert r['ok'] is False and 'quota' in r['error']

    def test_create_deal_triggers_export(self, tc, fake_sheet):
        """Сделка через API попадает в лист сразу, без ожидания completed."""
        resp = tc.post('/api/deals', json={
            'client_name': 'Export Client', 'deal_kind': 'mf_realty',
            'deal_type': 'pay_in', 'payin_method': 'crypto_direct',
            'payin_amount_usdt': 512000, 'invoice_amount_thb': 16742400,
            'buy_rate_thb_usdt': 33.20, 'company_percent': 0.9,
        })
        assert resp.json['success']
        titles = [w.title for w in fake_sheet.worksheets()]
        assert any('leasehold' in t for t in titles)


# ── Telegram ─────────────────────────────────────────────────────────────

class TestTelegram:
    def test_text_shows_both_pockets(self):
        t = A._mf_realty_telegram_text(make_deal())
        assert 'Чистый доход: $5,089.62' in t
        assert 'на кошельке $551.02' in t
        # Доход компании — первично в батах (они и лежат на MF Corp), $ в скобках
        assert 'в компании 150,682 ฿ ($4,538.60)' in t

    def test_text_shows_invoice_not_zero_thb(self):
        """Регресс: общий шаблон писал «Выдано: 0 THB» — инвойс в другом поле."""
        t = A._mf_realty_telegram_text(make_deal())
        assert '16,742,400 ฿' in t
        assert 'Выдано: 0' not in t

    def test_agent_models_in_russian(self):
        d = make_deal()
        d.agents = [
            DealAgent(name='Lidia SID', tier=1, comp_model='markup', percent=0.5, payout_usdt=2560),
            DealAgent(name='Valera', tier=2, comp_model='crypto_share', percent=10, payout_usdt=61.22),
        ]
        t = A._mf_realty_telegram_text(d)
        assert 'от курса' in t and 'от прибыли в крипте' in t
        assert 'crypto_share' not in t

    def test_router_picks_realty_template(self, monkeypatch):
        sent = []
        monkeypatch.setattr(A, 'send_telegram_notification', lambda text, thread_id=None: sent.append(text))
        A._send_deal_telegram(make_deal())
        assert sent and sent[0].startswith('🏠')
