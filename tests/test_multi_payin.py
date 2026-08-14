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
                 PayInMethod, DealType, DealStatus)


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
