"""
Сделки по недвижимости во фрихолде (оплата застройщику SWIFT-ом из-за рубежа).

Спека: docs/specs/2026-08-06-mf-freehold.md
Эталон — пример из §8 спеки лизхолда: получено 39 533.77, отправлено 39 373,
доход 160.77 (комиссия 0.8% + $50 внутри отправки).

Отличие от лизхолда: карман ОДИН — тайская компания в платеже не участвует,
поэтому вся прибыль в USDT, и она уже после расходов на перевод.

Запуск: cd Dev/CalcCRM && python -m pytest tests/test_mf_freehold.py -v
"""
import pytest
import sys
import os
import json
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ['SECRET_KEY'] = 'test-secret-key-for-pytest'

import app as A
from app import (app, get_session, Deal, DealType, Client, AdminUser, DealAgent, Referrer,
                 compute_mf_freehold, freehold_month_sheet_name,
                 GSHEET_FREEHOLD_HEADERS, sync_realty_deal_to_gsheet,
                 _mf_freehold_telegram_text)


def approx(a, b, eps=0.02):
    return abs((a or 0) - b) < eps


# ── Фикстуры ──────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clean_db():
    s = get_session()
    try:
        s.query(DealAgent).delete()
        s.query(Deal).delete()
        s.query(Client).delete()
        s.query(Referrer).delete()
        s.commit()
    finally:
        s.close()
    yield


@pytest.fixture
def tc():
    app.config['TESTING'] = True
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
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess['user_id'] = aid
        yield c


# ── Расчёт против эталонного примера ─────────────────────────────────────

class TestAgainstExample:
    """Пример §8: получено 39 533.77, отправлено 39 373, доход 160.77."""

    def test_by_fact_of_transfer(self):
        r = compute_mf_freehold(39533.77, sent_usd=39373, fee_percent=0.8,
                                fee_fixed_usd=50, agents=[])
        assert approx(r['fee_usd'], 364.98)
        assert approx(r['arrive_usd'], 39008.02), 'комиссия снимается С отправки'
        assert approx(r['gross_profit_usdt'], 160.77)
        assert approx(r['net_profit_usdt'], 160.77), 'без агентов чистый = валовый'

    def test_by_invoice_gives_same_transfer(self):
        """Обратная сторона: знаем, сколько должно дойти → сколько отправить."""
        r = compute_mf_freehold(39533.77, invoice_usd=39008.02, fee_percent=0.8,
                                fee_fixed_usd=50, agents=[])
        assert approx(r['sent_usd'], 39373.00)
        assert approx(r['arrive_usd'], 39008.02)
        assert approx(r['gross_profit_usdt'], 160.77)

    def test_round_trip(self):
        """Инвойс → отправка → сколько дойдёт: возвращаемся к инвойсу."""
        fwd = compute_mf_freehold(50000, invoice_usd=45000, fee_percent=1.2,
                                  fee_fixed_usd=100, agents=[])
        back = compute_mf_freehold(50000, sent_usd=fwd['sent_usd'], fee_percent=1.2,
                                   fee_fixed_usd=100, agents=[])
        assert approx(back['arrive_usd'], 45000)

    def test_fee_is_deducted_not_added_on_top(self):
        """Регресс на коррекцию 05.08: комиссия НЕ докладывается сверх отправки.

        Иначе застройщику обещают больше, чем до него дойдёт.
        """
        r = compute_mf_freehold(40000, sent_usd=39373, fee_percent=0.8,
                                fee_fixed_usd=50, agents=[])
        assert r['arrive_usd'] < r['sent_usd']
        assert approx(r['sent_usd'] - r['arrive_usd'], r['fee_usd'])

    def test_invoice_gap_flags_underpayment(self):
        """Отправили меньше, чем нужно, — видно, сколько не хватает застройщику."""
        r = compute_mf_freehold(40000, invoice_usd=39008.02, sent_usd=39000,
                                fee_percent=0.8, fee_fixed_usd=50, agents=[])
        assert r['invoice_gap_usd'] < 0
        assert approx(r['invoice_gap_usd'], r['arrive_usd'] - 39008.02)

    def test_no_fee_means_transfer_equals_invoice(self):
        r = compute_mf_freehold(40000, invoice_usd=39000, agents=[])
        assert approx(r['sent_usd'], 39000)
        assert approx(r['fee_usd'], 0)

    def test_empty_inputs_do_not_crash(self):
        r = compute_mf_freehold(None, agents=[])
        assert r['sent_usd'] == 0 and r['net_profit_usdt'] == 0


# ── Выплаты агентам: база = прибыль ПОСЛЕ расходов ───────────────────────

class TestAgentsBase:
    def test_revshare_from_profit_after_expenses(self):
        """Решение 06.08: агент делит то, что осталось после расходов на перевод.

        Иначе на тонкой марже фрихолда (0.4%) партнёр забирает больше, чем
        заработала сделка: 10% от валовой «приход − инвойс» = $52 при доходе $160.
        """
        r = compute_mf_freehold(39533.77, sent_usd=39373, fee_percent=0.8,
                                fee_fixed_usd=50,
                                agents=[{'tier': 1, 'comp_model': 'revshare', 'percent': 10}])
        assert approx(r['agents'][0]['_payout'], 16.08)
        assert approx(r['net_profit_usdt'], 144.69)
        assert approx(r['agents'][0]['_base'], r['gross_profit_usdt'])

    def test_payout_before_expenses_would_be_bigger(self):
        """Контроль величины: без учёта расходов та же ставка стоила бы дороже."""
        after = compute_mf_freehold(39533.77, sent_usd=39373, fee_percent=0.8,
                                    fee_fixed_usd=50,
                                    agents=[{'tier': 1, 'comp_model': 'revshare', 'percent': 10}])
        naive = (39533.77 - 39008.02) * 0.10      # 10% от «приход − инвойс»
        assert naive > after['agents'][0]['_payout'] * 3

    def test_cascade_markup_then_revshare(self):
        r = compute_mf_freehold(39533.77, sent_usd=39373, fee_percent=0.8, fee_fixed_usd=50,
                                agents=[
                                    {'tier': 1, 'comp_model': 'markup', 'percent': 0.1},
                                    {'tier': 2, 'comp_model': 'revshare', 'percent': 10},
                                ])
        first, second = r['agents']
        assert approx(first['_payout'], 39533.77 * 0.001)
        assert approx(second['_payout'], round(max(r['gross_profit_usdt'] - first['_payout'], 0) * 0.1, 2))

    def test_markup_priced_into_rate_keeps_our_profit(self):
        """Наценка партнёра заложена в курс → наш чистый доход не меняется.

        Markup считается от ОБЪЁМА, а не от прибыли: 0.5% от $39 500 = $197.67
        при заработке сделки $160.77. Работает это только когда наценку оплатил
        клиент (калькулятор её закладывает: курс → наша прибыль → markup → комиссия).
        """
        ag = [{'tier': 1, 'comp_model': 'markup', 'percent': 0.5}]
        alone = compute_mf_freehold(39533.77, invoice_usd=39008.02, fee_percent=0.8,
                                    fee_fixed_usd=50, agents=[])
        priced_in = compute_mf_freehold(round(39533.77 / (1 - 0.005), 2),
                                        invoice_usd=39008.02, fee_percent=0.8,
                                        fee_fixed_usd=50, agents=ag)
        assert approx(priced_in['net_profit_usdt'], alone['net_profit_usdt'])

    def test_markup_not_priced_in_eats_profit(self):
        """Наценку в курс не заложили — она вычитается из нашего заработка, в минус."""
        r = compute_mf_freehold(39533.77, invoice_usd=39008.02, fee_percent=0.8,
                                fee_fixed_usd=50,
                                agents=[{'tier': 1, 'comp_model': 'markup', 'percent': 0.5}])
        assert approx(r['agents'][0]['_payout'], 197.67)
        assert approx(r['net_profit_usdt'], -36.90)
        assert r['net_shortfall_usdt'] < 0, 'дефицит должен быть виден, а не тихо съеден'

    def test_payout_over_profit_flags_shortfall(self):
        """Фикс больше заработка сделки → явный признак, а не тихий минус."""
        r = compute_mf_freehold(39533.77, sent_usd=39373, fee_percent=0.8, fee_fixed_usd=50,
                                agents=[{'tier': 1, 'comp_model': 'fixed', 'fixed_usdt': 300}])
        assert r['net_profit_usdt'] < 0
        assert approx(r['net_shortfall_usdt'], r['net_profit_usdt'])


# ── API ───────────────────────────────────────────────────────────────────

def _fh_payload(**extra):
    data = {
        'client_name': 'Freehold Client',
        'deal_kind': 'mf_freehold',
        'deal_type': 'pay_in',
        'payin_method': 'crypto_direct',
        'payin_amount_usdt': 39533.77,
        'realty_purpose': 'Layan Green Park B12',
        'invoice_amount_usd': 39008.02,
        'transfer_fee_percent': 0.8,
        'transfer_fee_fixed_usd': 50,
    }
    data.update(extra)
    return data


class TestApi:
    def test_create_computes_transfer_and_profit(self, tc):
        deal = tc.post('/api/deals', json=_fh_payload()).json['deal']
        assert deal['deal_kind'] == 'mf_freehold'
        assert approx(deal['transfer_sent_usd'], 39373.00)
        assert approx(deal['transfer_fee_usd'], 364.98)
        assert approx(deal['transfer_arrive_usd'], 39008.02)
        assert approx(deal['profit_usdt'], 160.77)
        assert approx(deal['net_profit_usdt'], 160.77)
        assert approx(deal['payout_amount_usdt'], 39373.00), 'с кошелька ушла вся отправка'

    def test_not_queued_for_reimbursement(self, tc):
        deal = tc.post('/api/deals', json=_fh_payload()).json['deal']
        assert deal['needs_reimbursement'] is False

    def test_create_with_agent(self, tc):
        deal = tc.post('/api/deals', json=_fh_payload(agents=[
            {'tier': 1, 'comp_model': 'revshare', 'percent': 10, 'name': 'Агент'},
        ])).json['deal']
        assert approx(deal['agents'][0]['payout_usdt'], 16.08)
        assert approx(deal['net_profit_usdt'], 144.69)

    def test_payin_from_rub_uses_broker_rate(self, tc):
        """Приход в рублях: USDT считаем по курсу брокера, как в лизхолде."""
        deal = tc.post('/api/deals', json=_fh_payload(
            payin_method='spp_doverka', payin_amount_usdt=None,
            payin_amount_rub=3200000, payin_rate_rub_usdt=80.3)).json['deal']
        assert approx(deal['payin_amount_usdt'], 39850.56)

    def test_update_fee_recalculates(self, tc):
        did = tc.post('/api/deals', json=_fh_payload()).json['deal']['id']
        deal = tc.put(f'/api/deals/{did}', json={'transfer_fee_percent': 1.5}).json['deal']
        assert approx(deal['sent_usd'] if 'sent_usd' in deal else deal['transfer_sent_usd'],
                      (39008.02 + 50) / (1 - 0.015))
        assert deal['profit_usdt'] < 160.77, 'дороже перевод — меньше прибыль'

    def test_update_by_fact_of_transfer(self, tc):
        """Прислали фактическую отправку — она приоритетнее расчёта из инвойса."""
        did = tc.post('/api/deals', json=_fh_payload()).json['deal']['id']
        deal = tc.put(f'/api/deals/{did}', json={'transfer_sent_usd': 39500}).json['deal']
        assert approx(deal['transfer_sent_usd'], 39500)
        assert approx(deal['transfer_arrive_usd'], 39500 * 0.992 - 50)
        assert deal['transfer_arrive_usd'] > 39008.02, 'переотправили сверх инвойса'

    def test_update_keeps_agents(self, tc):
        did = tc.post('/api/deals', json=_fh_payload(agents=[
            {'tier': 1, 'comp_model': 'revshare', 'percent': 10, 'name': 'Агент'},
        ])).json['deal']['id']
        deal = tc.put(f'/api/deals/{did}', json={'realty_purpose': 'Layan B13'}).json['deal']
        assert len(deal['agents']) == 1
        assert approx(deal['net_profit_usdt'], 144.69)

    def test_leasehold_untouched(self, tc):
        """Регресс: лизхолд считается как раньше и не подхватывает поля фрихолда."""
        deal = tc.post('/api/deals', json={
            'client_name': 'MF Realty', 'deal_kind': 'mf_realty', 'deal_type': 'pay_in',
            'payin_method': 'crypto_direct', 'payin_amount_usdt': 19929.17,
            'invoice_amount_thb': 622370, 'buy_rate_thb_usdt': 33.22, 'company_percent': 1,
        }).json['deal']
        assert approx(deal['net_profit_usdt'], 1194.37)
        assert deal['transfer_sent_usd'] is None

    def test_ordinary_deal_untouched(self, tc):
        deal = tc.post('/api/deals', json={
            'client_name': 'Ordinary', 'deal_type': 'pay_in', 'payin_method': 'crypto_direct',
            'payin_amount_usdt': 1000, 'payout_amount_usdt': 970, 'payout_method': 'transfer',
        }).json['deal']
        assert deal['deal_kind'] == 'exchange'
        assert deal['transfer_fee_usd'] is None
        assert approx(deal['profit_usdt'], 30)

    def test_preview_endpoint(self, tc):
        r = tc.post('/api/deals/mf-freehold/preview', json={
            'payin_amount_usdt': 39533.77, 'invoice_amount_usd': 39008.02,
            'transfer_fee_percent': 0.8, 'transfer_fee_fixed_usd': 50,
        }).json
        assert r['success']
        assert approx(r['result']['sent_usd'], 39373.00)
        assert approx(r['result']['net_profit_usdt'], 160.77)

    def test_preview_bad_input(self, tc):
        r = tc.post('/api/deals/mf-freehold/preview', json={'invoice_amount_usd': 'abc'})
        assert r.status_code == 400


# ── Выгрузка в «Cделки недвижимость» ─────────────────────────────────────

class FakeWS:
    def __init__(self, title, rows=None):
        self.title = title
        self.rows = rows if rows is not None else []

    def col_values(self, col):
        return [(r[col - 1] if len(r) >= col else '') for r in self.rows]

    def row_values(self, idx):
        return self.rows[idx - 1] if len(self.rows) >= idx else []

    def append_row(self, row, value_input_option=None):
        self.rows.append([str(x) for x in row])

    def update(self, rng, values, value_input_option=None):
        i = int(''.join(c for c in rng.split(':')[0] if c.isdigit()))
        self.rows[i - 1] = [str(x) for x in values[0]]


class FakeSheet:
    def __init__(self, sheets=()):
        self.sheets = list(sheets)
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


def _make_freehold_deal(**extra):
    s = get_session()
    d = Deal(client_name='Freehold Client', deal_kind='mf_freehold', deal_type=DealType.PAY_IN,
             created_at=datetime(2026, 8, 6), realty_purpose='Layan Green Park B12',
             payin_amount_usdt=39533.77, invoice_amount_usd=39008.02,
             transfer_sent_usd=39373.00, transfer_fee_percent=0.8,
             transfer_fee_fixed_usd=50, transfer_fee_usd=364.98,
             transfer_arrive_usd=39008.02, profit_usdt=160.77, net_profit_usdt=160.77)
    for k, v in extra.items():
        setattr(d, k, v)
    s.add(d); s.commit(); s.refresh(d)
    return s, d


class TestExport:
    def test_sheet_name_by_deal_month(self):
        assert freehold_month_sheet_name(datetime(2026, 8, 6)) == 'август freehold'

    def test_creates_month_sheet_with_headers(self, monkeypatch):
        sheet = FakeSheet()
        monkeypatch.setattr(A, 'get_gsheet_client', lambda: FakeClient(sheet))
        s, deal = _make_freehold_deal()
        try:
            res = sync_realty_deal_to_gsheet(deal)
        finally:
            s.close()
        assert res['ok'] and res['sheet'] == 'август freehold'
        ws = sheet.worksheet('август freehold')
        assert ws.rows[0] == GSHEET_FREEHOLD_HEADERS
        row = ws.rows[1]
        assert row[0] == 'Layan Green Park B12'
        assert row[7] == '39008.02'          # инвойс застройщику
        assert row[8] == '39373.0'           # отправлено
        assert row[-1] == str(deal.id)       # CRM ID — якорь upsert

    def test_upsert_by_crm_id(self, monkeypatch):
        sheet = FakeSheet()
        monkeypatch.setattr(A, 'get_gsheet_client', lambda: FakeClient(sheet))
        s, deal = _make_freehold_deal()
        try:
            sync_realty_deal_to_gsheet(deal)
            deal.realty_purpose = 'Layan Green Park B13'
            s.commit()
            sync_realty_deal_to_gsheet(deal)
        finally:
            s.close()
        ws = sheet.worksheet('август freehold')
        assert len(ws.rows) == 2, 'правка перезаписывает строку, а не плодит дубли'
        assert ws.rows[1][0] == 'Layan Green Park B13'

    def test_manual_sheet_with_other_header_is_not_touched(self, monkeypatch):
        """«май freehold» заполнен руками по своей разметке — дописывать туда нельзя."""
        manual = FakeWS('май freehold', rows=[['дата', 'сумма', 'коммент'], ['01.05', '1', 'x']])
        sheet = FakeSheet([manual])
        monkeypatch.setattr(A, 'get_gsheet_client', lambda: FakeClient(sheet))
        s, deal = _make_freehold_deal(created_at=datetime(2026, 5, 20))
        try:
            res = sync_realty_deal_to_gsheet(deal)
        finally:
            s.close()
        assert res['sheet'] == 'май freehold CRM'
        assert len(manual.rows) == 2, 'ручной лист остался как был'

    def test_leasehold_still_goes_to_its_sheet(self, monkeypatch):
        """Регресс: лизхолд по-прежнему уходит в «<месяц> leasehold»."""
        sheet = FakeSheet()
        monkeypatch.setattr(A, 'get_gsheet_client', lambda: FakeClient(sheet))
        s = get_session()
        d = Deal(client_name='Lease', deal_kind='mf_realty', deal_type=DealType.PAY_IN,
                 created_at=datetime(2026, 8, 6),
                 payin_amount_usdt=19929.17, invoice_amount_thb=622370,
                 buy_rate_thb_usdt=33.22, company_percent=1)
        s.add(d); s.commit(); s.refresh(d)
        try:
            res = sync_realty_deal_to_gsheet(d)
        finally:
            s.close()
        assert res['sheet'] == 'август leasehold'


# ── Telegram ─────────────────────────────────────────────────────────────

class TestTelegram:
    def test_text_shows_transfer_cost(self):
        s, deal = _make_freehold_deal()
        try:
            text = _mf_freehold_telegram_text(deal)
        finally:
            s.close()
        assert 'Фрихолд' in text
        assert 'дойдёт застройщику: $39,008.02' in text
        assert 'комиссия за перевод: $364.98' in text
        assert 'Чистый доход: $160.77' in text

    def test_warns_when_invoice_not_covered(self):
        s, deal = _make_freehold_deal(transfer_arrive_usd=38000)
        try:
            text = _mf_freehold_telegram_text(deal)
        finally:
            s.close()
        assert 'не хватает' in text


# ── Фактические переводы: чем ушли деньги ────────────────────────────────

class TestActualTransfers:
    def test_marked_transfers_become_the_fact(self, tc):
        """Отметили переводы — их сумма и есть отправка, поле можно не заполнять."""
        deal = tc.post('/api/deals', json=_fh_payload(payout_tx_hashes=[
            {'hash': 'aa' * 16, 'amount_usdt': 20000, 'to_address': 'TX1', 'date': '06.08.2026'},
            {'hash': 'bb' * 16, 'amount_usdt': 19373, 'to_address': 'TX1', 'date': '06.08.2026'},
        ])).json['deal']
        assert approx(deal['transfer_sent_usd'], 39373.00)
        assert approx(deal['transfer_arrive_usd'], 39008.02)
        assert approx(deal['profit_usdt'], 160.77)
        assert len(deal['payout_tx_hashes']) == 2
        assert deal['payout_tx_hashes'][0]['to_address'] == 'TX1', 'адрес храним — видно КУДА ушло'

    def test_manual_fact_wins_over_transfers(self, tc):
        """Ввели отправку руками — она приоритетнее суммы переводов."""
        deal = tc.post('/api/deals', json=_fh_payload(
            transfer_sent_usd=39500,
            payout_tx_hashes=[{'hash': 'cc' * 16, 'amount_usdt': 39373}])).json['deal']
        assert approx(deal['transfer_sent_usd'], 39500)

    def test_preview_counts_transfers(self, tc):
        r = tc.post('/api/deals/mf-freehold/preview', json={
            'payin_amount_usdt': 39533.77, 'invoice_amount_usd': 39008.02,
            'transfer_fee_percent': 0.8, 'transfer_fee_fixed_usd': 50,
            'payout_tx_hashes': [{'hash': 'dd' * 16, 'amount_usdt': 39373}],
        }).json
        assert r['success'] and approx(r['result']['sent_usd'], 39373.00)

    def test_telegram_lists_transfers(self):
        s, deal = _make_freehold_deal(payout_tx_hashes=json.dumps([
            {'hash': 'ee' * 16, 'amount_usdt': 39373, 'to_address': 'TXaddress', 'date': '06.08.2026'}]))
        try:
            text = _mf_freehold_telegram_text(deal)
        finally:
            s.close()
        assert 'Переводы (1)' in text and 'TXaddress' in text

    def test_export_uses_payout_hashes(self, monkeypatch):
        """В выгрузку идут хэши отправки — по ним сверяют платёж."""
        sheet = FakeSheet()
        monkeypatch.setattr(A, 'get_gsheet_client', lambda: FakeClient(sheet))
        s, deal = _make_freehold_deal(payout_tx_hashes=json.dumps([
            {'hash': 'ff' * 16, 'amount_usdt': 39373}]))
        try:
            sync_realty_deal_to_gsheet(deal)
        finally:
            s.close()
        assert 'ff' * 16 in sheet.worksheet('август freehold').rows[1][19]
