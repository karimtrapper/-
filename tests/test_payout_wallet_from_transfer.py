"""Кошелёк возврата = кошелёк, с которого выдали.

Форма обещает «с кошелька TMKuEbe… — туда же пойдёт возврат», но в базу
уезжал другой адрес: селект «Кошелёк списания» живёт в блоке Binance, всегда
имеет выбранное значение и при скрытом блоке всё равно попадал в payload
(первый кошелёк списка — TRgncc…). Бэкенд подставлял адрес из перевода только
в ПУСТОЕ поле, поэтому мусор побеждал: 162 сделки с 27.01 по 24.08 записаны
с возвратом на TRgncc, а в сводке пачки сделки с разных кошельков слипались
в одну группу возмещения.

Запуск: cd Dev/CalcCRM && python -m pytest tests/test_payout_wallet_from_transfer.py -v
"""
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('SECRET_KEY', 'test-secret-key-for-pytest')
os.environ['REESTR_SYNC_ENABLED'] = '0'

import pytest

import app as appmod
from app import (app as flask_app, get_session, Client, Deal, DealAgent,
                 PayinTx, PayinTxUse, Reimbursement, ReimbursementTxUse, Wallet)

# Адрес Андрея (TWyLcj…) занят фикстурами test_payout_cost с подписью «Андрей»,
# а кошельки в тестовой базе общие — берём соседний, чтобы не спорить за label
PAYOUT_A = 'TXW2hYJZvikmPQCnKPTsdRMTiWkTfRUyhE'   # кошелёк выдачи №1
PAYOUT_B = 'TMKuEbeVfETdcgfspp2hHfBxDCzQog9UV8'   # с него выдали #537 (Тед Битаза)
STRANGER = 'TRgnccUBQo8yZXtra8gqBngBqeTV5aQz74'   # первый в селекте Binance


def _uid():
    return uuid.uuid4().hex


@pytest.fixture
def cli(monkeypatch):
    flask_app.config['TESTING'] = True
    monkeypatch.setenv('LOCAL_NO_AUTH', '1')
    monkeypatch.setattr(appmod, 'sync_deals_to_gsheet', lambda *a, **kw: None)
    monkeypatch.setattr(appmod, '_send_deal_telegram', lambda *a, **kw: None)
    monkeypatch.setattr(appmod, 'send_deal_completed_webhook', lambda *a, **kw: None)
    monkeypatch.setattr(appmod, '_tron_tx_amount', lambda h: None)
    monkeypatch.setattr(appmod, '_tron_tx_info', lambda h: None)
    with flask_app.test_client() as c:
        yield c


@pytest.fixture(autouse=True)
def clean():
    def _clean():
        db = get_session()
        try:
            db.query(ReimbursementTxUse).delete()
            db.query(PayinTxUse).delete()
            db.query(PayinTx).delete()
            db.query(DealAgent).delete()
            db.query(Deal).delete()
            db.query(Reimbursement).delete()
            db.query(Client).delete()
            db.commit()
        finally:
            db.close()
    _clean()
    yield
    _clean()


def _wallet(address, label):
    db = get_session()
    try:
        w = db.query(Wallet).filter(Wallet.address == address).first()
        if not w:
            w = Wallet(address=address, label=label)
            db.add(w)
            db.commit()
        return w.id
    finally:
        db.close()


def _deal(cli, from_address, wallet_id_in_payload, cost=306.0, thb=10000.0):
    return cli.post('/api/deals', json={
        'client_name': 'Roman - Grusha', 'status': 'pending',
        'payin_method': 'sber_reqs', 'payin_amount_rub': 27352.12,
        'payin_amount_usdt': 323.55,
        'payout_method': 'transfer', 'payout_source': 'founder_personal',
        'payout_founder_name': 'Андрей', 'payout_amount_thb': thb,
        'payout_wallet_id': wallet_id_in_payload,
        'payout_tx_hashes': [{'hash': _uid(), 'amount_usdt': cost,
                              'from_address': from_address, 'to_address': STRANGER}],
        'skip_sync': True,
    }).get_json()['deal']


def test_кошелёк_берётся_из_перевода_а_не_из_payload(cli):
    """Мусор из скрытого селекта проигрывает адресу, с которого реально ушли деньги."""
    payout_wid = _wallet(PAYOUT_A, '')
    _wallet(STRANGER, STRANGER)
    deal = _deal(cli, PAYOUT_A, _wallet(STRANGER, STRANGER))

    db = get_session()
    try:
        assert db.query(Deal).get(deal['id']).payout_wallet_id == payout_wid
    finally:
        db.close()


def test_разные_кошельки_выдачи_не_слипаются(cli):
    """Две сделки одного фаундера с разных кошельков — два разных адреса возврата."""
    wid_a = _wallet(PAYOUT_A, '')
    wid_b = _wallet(PAYOUT_B, 'Тед Битаза')
    stranger = _wallet(STRANGER, STRANGER)
    d1 = _deal(cli, PAYOUT_A, stranger, cost=306.0)
    d2 = _deal(cli, PAYOUT_B, stranger, cost=1349.0, thb=43726.44)

    db = get_session()
    try:
        assert db.query(Deal).get(d1['id']).payout_wallet_id == wid_a
        assert db.query(Deal).get(d2['id']).payout_wallet_id == wid_b
    finally:
        db.close()


def test_правка_сделки_переставляет_кошелёк_на_новый_перевод(cli):
    """Перевод выдачи поменяли — возврат едет за ним."""
    wid_a = _wallet(PAYOUT_A, '')
    wid_b = _wallet(PAYOUT_B, 'Тед Битаза')
    deal = _deal(cli, PAYOUT_A, _wallet(STRANGER, STRANGER))

    cli.put(f"/api/deals/{deal['id']}", json={
        'payout_tx_hashes': [{'hash': _uid(), 'amount_usdt': 306.0,
                              'from_address': PAYOUT_B, 'to_address': STRANGER}],
        'skip_sync': True,
    })

    db = get_session()
    try:
        assert db.query(Deal).get(deal['id']).payout_wallet_id == wid_b
        assert wid_a != wid_b
    finally:
        db.close()


def test_возмещённую_сделку_не_трогаем(cli):
    """Возврат уже сделан — переписывать адрес задним числом нельзя."""
    wid_a = _wallet(PAYOUT_A, '')
    stranger = _wallet(STRANGER, STRANGER)
    deal = _deal(cli, PAYOUT_A, stranger)

    db = get_session()
    try:
        d = db.query(Deal).get(deal['id'])
        reimb = Reimbursement(founder_name='Андрей', amount_usdt=306.0, tx_hash=_uid())
        db.add(reimb)
        db.flush()
        d.reimbursement_id = reimb.id
        d.payout_wallet_id = stranger      # как записано в истории
        db.commit()
        deal_id, reimb_id = d.id, reimb.id
    finally:
        db.close()

    cli.put(f"/api/deals/{deal_id}", json={
        'payout_tx_hashes': [{'hash': _uid(), 'amount_usdt': 306.0,
                              'from_address': PAYOUT_A, 'to_address': STRANGER}],
        'skip_sync': True,
    })

    db = get_session()
    try:
        d = db.query(Deal).get(deal_id)
        assert d.reimbursement_id == reimb_id
        assert d.payout_wallet_id == stranger, 'история возмещения не переписывается'
        assert wid_a != stranger
    finally:
        db.close()


def test_свои_баты_кошелёк_выбирает_человек(cli):
    """Переводов нет — подставлять неоткуда, выбор менеджера остаётся."""
    wid_a = _wallet(PAYOUT_A, '')
    r = cli.post('/api/deals', json={
        'client_name': 'Мэкс - Grusha', 'status': 'pending',
        'payin_method': 'sber_reqs', 'payin_amount_rub': 49866.76,
        'payin_amount_usdt': 589.88,
        'payout_method': 'transfer', 'payout_source': 'founder_personal',
        'payout_founder_name': 'Теодор', 'payout_amount_thb': 18000.0,
        'payout_amount_usdt': 558.20, 'payout_no_conversion': True,
        'payout_wallet_id': wid_a, 'skip_sync': True,
    }).get_json()

    db = get_session()
    try:
        deal = db.query(Deal).get(r['deal']['id'])
        assert deal.payout_wallet_id == wid_a
        assert deal.payout_no_conversion is True
    finally:
        db.close()
