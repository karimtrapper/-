"""
Выгрузка мульти-Pay-In сделки: строки по частям, нумерация, поиск и удаление.
Спека: docs/specs/2026-08-14-multi-payin.md §8

Запуск: cd Dev/CalcCRM && python -m pytest tests/test_multi_payin_export.py -v
"""
import pytest
import sys
import os
import json
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ['SECRET_KEY'] = 'test-secret-key-for-pytest'

from app import (app, get_session, Deal, Client, PayInMethod, PayOutMethod,
                 DealType, DealStatus, build_deal_rows)

EXTRA = [{'method': 'sber_reqs', 'amount_rub': 200000.0, 'rate_rub_usdt': 84.5537,
          'amount_usdt': 2365.362, 'partner_name': None,
          'tx_hashes': [], 'sber_uuids': [], 'note': ''}]


@pytest.fixture(autouse=True)
def clean_db():
    s = get_session()
    try:
        s.query(Deal).delete()
        s.query(Client).delete()
        s.commit()
    finally:
        s.close()
    yield


def _deal(**over):
    kw = dict(id=512, client_name='elena imaikina',
              deal_type=DealType.PAY_IN, status=DealStatus.COMPLETED,
              created_at=datetime(2026, 8, 14),
              payin_method=PayInMethod.PARTNERS_CASH, payin_partner_name='FOEX',
              payin_amount_rub=800000, payin_amount_usdt=9285.362,
              payin_rate_rub_usdt=86.1571,
              payout_method=PayOutMethod.TRANSFER,
              payout_amount_thb=282600, payout_amount_usdt=8669.0,
              profit_usdt=616.36, referrer_name='FOEX',
              referrer_payout_usdt=185.71, net_profit_usdt=430.65,
              payin_extra=json.dumps(EXTRA, ensure_ascii=False))
    kw.update(over)
    return Deal(**kw)


def _money(s):
    return float(str(s).replace('$', '').replace(',', '') or 0)


def test_single_channel_gives_one_row():
    """Сделка с одним каналом — ровно одна строка и «1/1» в колонке части."""
    rows = build_deal_rows(_deal(payin_extra=None, payin_amount_rub=600000,
                                 payin_amount_usdt=6920.0), 187)
    assert len(rows) == 1
    assert rows[0][0] == 187
    assert rows[0][18] == '1/1'


def test_single_channel_row_unchanged():
    """Одночастная строка — как до появления частей: приход целиком,
    выдача целиком, партнёру целиком."""
    rows = build_deal_rows(_deal(payin_extra=None, payin_amount_rub=600000,
                                 payin_amount_usdt=6920.0), 187)
    r = rows[0]
    assert r[4] == '600,000.00'
    assert r[5] == 'rub'
    assert r[6] == '$6,920.00'
    assert r[7] == 282600
    assert r[9] == '$8,669.00'
    assert r[12] == '$185.71'
    assert r[15] == 'наличные'


def test_two_parts_give_two_rows_with_numbering():
    rows = build_deal_rows(_deal(), 187)
    assert len(rows) == 2
    assert rows[0][0] == 187
    assert rows[1][0] == '187.2'
    assert [r[18] for r in rows] == ['1/2', '2/2']


def test_method_column_is_per_row():
    """Ради этого задача и делалась: способ пополнения честен построчно."""
    rows = build_deal_rows(_deal(), 187)
    assert rows[0][15] == 'наличные'
    assert rows[1][15] == 'сбер реквизиты'


def test_payin_columns_are_per_part():
    rows = build_deal_rows(_deal(), 187)
    assert rows[0][4] == '600,000.00'
    assert rows[1][4] == '200,000.00'
    assert rows[0][6] == '$6,920.00'
    assert rows[1][6] == '$2,365.36'


def test_divisible_columns_sum_to_deal_total():
    """Инвариант листа: сумма строк равна сделке."""
    rows = build_deal_rows(_deal(), 187)
    assert sum(_money(r[9]) for r in rows) == pytest.approx(8669.0, abs=0.01)
    assert sum(_money(r[12]) for r in rows) == pytest.approx(185.71, abs=0.01)
    assert sum(_money(r[13]) for r in rows) == pytest.approx(430.65, abs=0.01)
    assert sum(int(r[7]) for r in rows) == 282600


def test_deal_id_anchor_repeats_in_every_row():
    """Якорь upsert — обычный deal.id во всех строках блока."""
    rows = build_deal_rows(_deal(), 187)
    assert [r[17] for r in rows] == ['512', '512']


def test_crypto_part_row_uses_usdt_currency():
    """У крипто-части рублей нет — в колонке валюты usdt, а не пустой rub."""
    d = _deal(payin_amount_rub=600000, payin_amount_usdt=7420.0,
              payin_extra=json.dumps([{
                  'method': 'crypto_direct', 'amount_rub': None,
                  'rate_rub_usdt': None, 'amount_usdt': 500.0,
                  'partner_name': None, 'tx_hashes': [],
                  'sber_uuids': [], 'note': ''}], ensure_ascii=False))
    rows = build_deal_rows(d, 187)
    assert rows[1][5] == 'usdt'
    assert rows[1][4] == '500.00'
    assert rows[1][15] == 'крипта'


# ============ Task 8: поиск и удаление всех строк сделки ============

from app import find_deal_rows_in_gsheet


def _sheet_rows():
    """Лист: соседняя сделка 511 плюс сделка 512 в двух строках."""
    blank = [''] * 19
    r511 = list(blank); r511[0] = '186'; r511[1] = 'другой клиент'
    r511[3] = '13.08.2026'; r511[6] = '$9,285.36'; r511[17] = '511'
    a = list(blank); a[0] = '187'; a[1] = 'elena imaikina'
    a[3] = '14.08.2026'; a[6] = '$6,920.00'; a[17] = '512'; a[18] = '1/2'
    b = list(blank); b[0] = '187.2'; b[1] = 'elena imaikina'
    b[3] = '14.08.2026'; b[6] = '$2,365.36'; b[17] = '512'; b[18] = '2/2'
    return [r511, a, b]


def test_finds_all_rows_of_deal():
    assert find_deal_rows_in_gsheet(_sheet_rows(), _deal()) == [2, 3]


def test_finds_single_row_by_anchor():
    d = _deal(id=511, client_name='другой клиент', payin_extra=None)
    assert find_deal_rows_in_gsheet(_sheet_rows(), d) == [1]


def test_fallback_disabled_for_multipart_deal():
    """Фолбэк «дата + сумма USDT» сравнивает с ИТОГОМ, а в строках лежат части:
    своё не найдёт, зато мог бы снести чужую сделку с той же суммой."""
    sheet = _sheet_rows()
    for r in sheet[1:]:
        r[17] = ''          # у своих строк якорь потерян
    assert find_deal_rows_in_gsheet(sheet, _deal()) == []


def test_fallback_allowed_for_single_part_deal():
    """Легаси-строка без якоря у одночастной сделки по-прежнему находится
    по «имя + дата» — этот путь ломать нельзя, старых строк в листе много."""
    legacy = [''] * 19
    legacy[1] = 'elena imaikina'
    legacy[3] = '14.08.2026'
    legacy[6] = '$6,920.00'
    single = _deal(id=999, payin_extra=None, payin_amount_rub=600000,
                   payin_amount_usdt=6920.0)
    assert find_deal_rows_in_gsheet([legacy], single) == [1]
