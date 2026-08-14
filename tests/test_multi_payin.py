"""
Мульти-Pay-In: несколько способов прихода в одной сделке.
Спека: docs/specs/2026-08-14-multi-payin.md

Запуск: cd Dev/CalcCRM && python -m pytest tests/test_multi_payin.py -v
"""
import pytest
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ['SECRET_KEY'] = 'test-secret-key-for-pytest'

from app import (app, get_session, Deal, Client, AdminUser,
                 PayInMethod, DealType, DealStatus,
                 _normalize_payin_extra, _payin_extra_list, _payin_all_parts)

H_EXTRA = 'cc11dd22ee33ff44aa55bb66cc77dd88ee99ff00aa11bb22cc33dd44ee55ff66'


def make_deal(**over):
    """Сделка с обязательными полями. deal_type и status NOT NULL в схеме."""
    kw = dict(client_name='T', deal_type=DealType.PAY_IN,
              status=DealStatus.PENDING, payin_method=PayInMethod.PARTNERS_CASH)
    kw.update(over)
    return Deal(**kw)


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


@pytest.fixture
def db():
    s = get_session()
    yield s
    s.close()


def test_payin_extra_column_roundtrip(db):
    """Колонка есть, JSON сохраняется и читается через to_dict."""
    extra = [{'method': 'sber_reqs', 'amount_rub': 200000.0,
              'rate_rub_usdt': 84.5537, 'amount_usdt': 2365.362,
              'partner_name': None, 'tx_hashes': [], 'sber_uuids': [], 'note': ''}]
    d = make_deal(payin_extra=json.dumps(extra, ensure_ascii=False))
    db.add(d)
    db.commit()

    got = db.query(Deal).filter(Deal.id == d.id).first()
    assert json.loads(got.payin_extra)[0]['amount_usdt'] == 2365.362
    assert got.to_dict()['payin_extra'][0]['method'] == 'sber_reqs'


def test_payin_extra_defaults_to_none(db):
    """Сделка с одним каналом: колонка пустая, to_dict отдаёт None."""
    d = make_deal()
    db.add(d)
    db.commit()
    assert d.payin_extra is None
    assert d.to_dict()['payin_extra'] is None


# ==================== Task 2: нормализация и чтение частей ====================

def test_normalize_drops_parts_without_money():
    """Часть без суммы USDT ничего не описывает — выбрасываем."""
    out = _normalize_payin_extra([
        {'method': 'crypto_direct', 'amount_usdt': 500},
        {'method': 'crypto_direct'},
        {'method': 'crypto_direct', 'amount_usdt': 0},
        {'method': 'crypto_direct', 'amount_usdt': 'абв'},
        'мусор',
    ])
    assert len(out) == 1
    assert out[0]['amount_usdt'] == 500


def test_normalize_rejects_unknown_method():
    """Метода нет в PayInMethod — часть не сохраняем, иначе упадёт лейбл в выгрузке."""
    assert _normalize_payin_extra([{'method': 'bitcoin_atm', 'amount_usdt': 100}]) == []


def test_normalize_derives_rate_from_rub():
    """Курс не прислали, рубли есть — считаем сами."""
    out = _normalize_payin_extra([
        {'method': 'sber_reqs', 'amount_rub': 200000, 'amount_usdt': 2365.362}])
    assert out[0]['rate_rub_usdt'] == pytest.approx(84.5537, abs=1e-4)


def test_normalize_crypto_part_has_no_rate():
    """Крипта пришла напрямую — рублей нет, курса нет."""
    out = _normalize_payin_extra([{'method': 'crypto_direct', 'amount_usdt': 500}])
    assert out[0]['amount_rub'] is None
    assert out[0]['rate_rub_usdt'] is None


def test_normalize_keeps_hashes_and_uuids():
    out = _normalize_payin_extra([{
        'method': 'crypto_direct', 'amount_usdt': 500,
        'tx_hashes': [{'hash': H_EXTRA, 'amount_usdt': 500}],
        'sber_uuids': ['uuid-1'],
    }])
    assert out[0]['tx_hashes'] == [{'hash': H_EXTRA, 'amount_usdt': 500.0}]
    assert out[0]['sber_uuids'] == ['uuid-1']


def test_all_parts_derives_main_from_totals(db):
    """Часть 1 восстанавливается как итог минус дополнительные —
    отдельно она нигде не хранится."""
    extra = _normalize_payin_extra([
        {'method': 'sber_reqs', 'amount_rub': 200000, 'amount_usdt': 2365.362}])
    d = make_deal(payin_partner_name='FOEX',
                  payin_amount_rub=800000, payin_amount_usdt=9285.362,
                  payin_extra=json.dumps(extra, ensure_ascii=False))
    db.add(d)
    db.commit()

    parts = _payin_all_parts(d)
    assert len(parts) == 2
    assert parts[0]['method'] == 'partners_cash'
    assert parts[0]['amount_usdt'] == pytest.approx(6920.0, abs=0.01)
    assert parts[0]['amount_rub'] == pytest.approx(600000, abs=0.01)
    assert parts[0]['rate_rub_usdt'] == pytest.approx(86.7052, abs=1e-4)
    assert parts[0]['partner_name'] == 'FOEX'
    assert parts[1]['amount_usdt'] == pytest.approx(2365.362, abs=0.01)


def test_all_parts_single_channel(db):
    """Сделка без дополнительных частей — ровно одна часть из плоских полей."""
    d = make_deal(payin_amount_rub=600000, payin_amount_usdt=6920.0)
    db.add(d)
    db.commit()
    parts = _payin_all_parts(d)
    assert len(parts) == 1
    assert parts[0]['amount_usdt'] == 6920.0


def test_extra_list_survives_broken_json(db):
    """Битый JSON не должен ронять карточку и выгрузку."""
    d = make_deal(payin_extra='{не json')
    db.add(d)
    db.commit()
    assert _payin_extra_list(d) == []
