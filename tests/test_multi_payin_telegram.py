"""
Блок «— Приход —» в трёх шаблонах уведомлений.
Спека: docs/specs/2026-08-14-multi-payin.md §7

Запуск: cd Dev/CalcCRM && python -m pytest tests/test_multi_payin_telegram.py -v
"""
import pytest
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ['SECRET_KEY'] = 'test-secret-key-for-pytest'

from app import (app, get_session, Deal, Client, PayInMethod, DealType, DealStatus,
                 _payin_parts_block, _mf_freehold_telegram_text,
                 _mf_realty_telegram_text, MF_FREEHOLD_KIND, MF_REALTY_KIND)

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


def make_deal(**over):
    kw = dict(client_name='elena imaikina', deal_type=DealType.PAY_IN,
              status=DealStatus.PENDING, payin_method=PayInMethod.PARTNERS_CASH,
              payin_partner_name='FOEX', payin_amount_rub=800000,
              payin_amount_usdt=9285.362, payin_rate_rub_usdt=86.1571,
              payin_extra=json.dumps(EXTRA, ensure_ascii=False))
    kw.update(over)
    return Deal(**kw)


def test_block_absent_for_single_channel():
    d = make_deal(payin_extra=None, payin_amount_rub=600000, payin_amount_usdt=6920.0)
    assert _payin_parts_block(d) == ''


def test_block_lists_every_channel():
    text = _payin_parts_block(make_deal())
    assert '— Приход (2) —' in text
    assert 'наличные FOEX · 600,000 ₽ @ 86.7052 → $6,920.00' in text
    assert 'сбер реквизиты · 200,000 ₽ @ 84.5537 → $2,365.36' in text


def test_crypto_part_without_rate():
    """У крипты рублей нет — курс не печатаем, а не рисуем ноль."""
    d = make_deal(payin_amount_rub=600000, payin_amount_usdt=7420.0,
                  payin_extra=json.dumps([{
                      'method': 'crypto_direct', 'amount_rub': None,
                      'rate_rub_usdt': None, 'amount_usdt': 500.0,
                      'partner_name': None, 'tx_hashes': [],
                      'sber_uuids': [], 'note': ''}], ensure_ascii=False))
    text = _payin_parts_block(d)
    assert '• крипта → $500.00' in text
    assert '@' not in text.split('крипта')[1]


def test_freehold_message_contains_block():
    d = make_deal(deal_kind=MF_FREEHOLD_KIND, transfer_sent_usd=8669.0,
                  transfer_arrive_usd=8491.63, transfer_fee_usd=177.37,
                  profit_usdt=616.36, net_profit_usdt=430.65,
                  referrer_payout_usdt=185.71)
    msg = _mf_freehold_telegram_text(d)
    assert '— Приход (2) —' in msg
    assert msg.index('Приход: $9,285.36') < msg.index('— Приход (2) —')
    assert msg.index('— Приход (2) —') < msg.index('Отправлено:')


def test_realty_message_contains_block():
    d = make_deal(deal_kind=MF_REALTY_KIND, company_sent_thb=295800.0,
                  invoice_amount_thb=290000.0, company_fee_thb=5800.0,
                  company_fee_usdt=176.83, company_percent=2.0,
                  crypto_remainder_usdt=81.36, net_profit_usdt=258.19)
    msg = _mf_realty_telegram_text(d)
    assert '— Приход (2) —' in msg
    assert msg.index('— Приход (2) —') < msg.index('Отправлено в MF Corp:')


def test_freehold_single_channel_unchanged():
    """Сделка с одним каналом — сообщение как было, без лишних строк."""
    d = make_deal(deal_kind=MF_FREEHOLD_KIND, payin_extra=None,
                  payin_amount_rub=600000, payin_amount_usdt=6920.0,
                  transfer_sent_usd=6500.0, transfer_arrive_usd=6350.0,
                  transfer_fee_usd=150.0, profit_usdt=420.0, net_profit_usdt=420.0)
    msg = _mf_freehold_telegram_text(d)
    assert '— Приход' not in msg
    assert 'Приход: $6,920.00\nОтправлено: $6,500.00' in msg
