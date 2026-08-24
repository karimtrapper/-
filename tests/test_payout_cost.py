"""Себестоимость выдачи с кошелька оунера — из фактических переводов, а не из возмещения.

Кейс CNV-0002 (21.08): две сделки Романа выданы с кошелька Андрея на 383,14 и 387,78 USDT,
а доли из пачки у них 408,04 и 408,04 — разница 45,16 наша маржа. Раньше
`payout_amount_usdt` появлялся только внутри `create_reimbursement`: до возврата прибыль
сделки была неизвестна, а возврату неоткуда было взять сумму, кроме как из доли пачки —
и тогда оунеру уходила наша маржа.

Выдача идёт РАНЬШЕ конвертации и с кошелька оунера, значит себестоимость известна
в момент выплаты. Берём её из отмеченных переводов.

Запуск: cd Dev/CalcCRM && python -m pytest tests/test_payout_cost.py -v
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
                 DealStatus, PayOutSource, Reimbursement)


def _hash():
    return uuid.uuid4().hex


@pytest.fixture
def cli(monkeypatch):
    flask_app.config['TESTING'] = True
    monkeypatch.setenv('LOCAL_NO_AUTH', '1')
    monkeypatch.setattr(appmod, 'sync_deals_to_gsheet', lambda *a, **kw: None)
    monkeypatch.setattr(appmod, '_send_deal_telegram', lambda *a, **kw: None)
    with flask_app.test_client() as c:
        yield c


@pytest.fixture(autouse=True)
def clean_deals():
    def _clean():
        db = get_session()
        try:
            db.query(DealAgent).delete()
            db.query(Deal).delete()
            db.query(Client).delete()
            db.commit()
        finally:
            db.close()
    _clean()
    yield
    _clean()


# Сделка Романа из CNV-0002: 34 755 ₽ прихода → доля пачки 408,04 USDT,
# выдано 12 500 ฿ с кошелька Андрея за 383,14 USDT (32,63 ฿/USDT).
ROMAN = {
    'client_name': 'Roman - Grusha', 'status': 'pending',
    'payin_method': 'sber_reqs', 'payin_amount_rub': 34755, 'payin_amount_usdt': 408.04,
    'payout_method': 'transfer', 'payout_source': 'founder_personal',
    'payout_founder_name': 'Андрей', 'payout_amount_thb': 12500,
    'skip_sync': True,
}


def _transfers(amount, addr='TWyLcjJzyQmiT1nt7gEn8BVoNSN94RGcHb'):
    return [{'hash': _hash(), 'amount_usdt': amount, 'to_address': addr}]


def test_себестоимость_считается_из_переводов_при_создании(cli):
    """Переводы отмечены — сумма и прибыль известны сразу, не дожидаясь возврата."""
    r = cli.post('/api/deals', json={**ROMAN, 'payout_tx_hashes': _transfers(383.14)}).get_json()
    assert r['success'] is True
    deal = r['deal']
    assert deal['payout_amount_usdt'] == 383.14
    assert deal['profit_usdt'] == 24.90          # 408,04 − 383,14, а не 0
    # Долг оунеру при этом никуда не делся — деньги ему ещё не вернули
    assert deal['reimbursement_id'] is None
    assert deal['needs_reimbursement'] is True
    assert deal['status'] == DealStatus.PENDING.value


def test_себестоимость_проставляется_и_через_put(cli):
    """Переводы отмечают позже, чем заводят сделку — обычный порядок работы."""
    deal_id = cli.post('/api/deals', json=ROMAN).get_json()['deal']['id']
    r = cli.put(f'/api/deals/{deal_id}',
                json={'payout_tx_hashes': _transfers(387.78), 'skip_sync': True}).get_json()
    assert r['success'] is True
    assert r['deal']['payout_amount_usdt'] == 387.78
    assert r['deal']['profit_usdt'] == 20.26


def test_возмещённую_сделку_не_перетираем(cli):
    """У возмещённой сделки сумма зафиксирована аллокацией возврата — переводы её не трогают."""
    deal_id = cli.post('/api/deals', json=ROMAN).get_json()['deal']['id']
    db = get_session()
    try:
        reimb = Reimbursement(founder_name='Андрей', amount_usdt=770.92)
        db.add(reimb)
        db.flush()
        deal = db.query(Deal).get(deal_id)
        deal.reimbursement_id = reimb.id
        deal.payout_amount_usdt = 383.14
        db.commit()
        reimb_id = reimb.id
    finally:
        db.close()

    cli.put(f'/api/deals/{deal_id}',
            json={'payout_tx_hashes': _transfers(999.00), 'skip_sync': True})
    db = get_session()
    try:
        assert db.query(Deal).get(deal_id).payout_amount_usdt == 383.14
        db.query(Deal).filter(Deal.id == deal_id).update({'reimbursement_id': None})
        db.query(Reimbursement).filter(Reimbursement.id == reimb_id).delete()
        db.commit()
    finally:
        db.close()


def test_курс_вне_коридора_не_подставляется(cli):
    """Урок #501: автоподстановка денег не проходит без проверки правдоподобия.

    12 500 ฿ за 4 000 USDT — это 3,1 ฿/USDT вместо рыночных ~32. Молча записать
    такую себестоимость значит увести прибыль сделки в минус на 3,5 тысячи долларов.
    """
    r = cli.post('/api/deals', json={**ROMAN, 'payout_tx_hashes': _transfers(4000.0)}).get_json()
    assert r['success'] is True
    assert r['deal']['payout_amount_usdt'] is None
    assert not r['deal'].get('profit_usdt')


def test_выдача_не_с_кошелька_оунера_не_трогается(cli):
    """Выдача с карты считается по курсу закупки карты — переводов там нет и быть не должно."""
    r = cli.post('/api/deals', json={**ROMAN, 'payout_source': 'bank_card',
                                     'payout_founder_name': None,
                                     'payout_tx_hashes': _transfers(383.14)}).get_json()
    assert r['success'] is True
    assert r['deal']['payout_amount_usdt'] != 383.14


# ─────────────────────────────────────────────────────────────────────────────
# Хеш выдачи: по нему видно, С КАКОГО кошелька ушло и СКОЛЬКО вернуть
# ─────────────────────────────────────────────────────────────────────────────

ANDREY_WALLET = 'TWyLcjJzyQmiT1nt7gEn8BVoNSN94RGcHb'


@pytest.fixture
def chain(monkeypatch):
    """Сеть не дёргаем: перевод на 383,14 с кошелька Андрея."""
    monkeypatch.setattr(appmod, '_tron_tx_info', lambda h: {
        'amount_usdt': 383.14, 'from_address': ANDREY_WALLET, 'to_address': 'TClientAddress'})
    return ANDREY_WALLET


@pytest.fixture
def andrey_wallet():
    from app import Wallet
    db = get_session()
    try:
        w = db.query(Wallet).filter(Wallet.address == ANDREY_WALLET).first()
        if not w:
            w = Wallet(address=ANDREY_WALLET, label='Андрей')
            db.add(w)
            db.commit()
        return w.id
    finally:
        db.close()


def test_хеш_выдачи_даёт_сумму_и_кошелёк(cli, chain, andrey_wallet):
    """Менеджер вставил один хеш — сумма возврата и кошелёк подтянулись из сети."""
    r = cli.post('/api/deals', json={
        **ROMAN, 'payout_tx_hashes': [{'hash': _hash()}]}).get_json()
    assert r['success'] is True
    assert r['deal']['payout_amount_usdt'] == 383.14
    assert r['deal']['payout_wallet_id'] == andrey_wallet
    assert r['deal']['profit_usdt'] == 24.90


def test_подсказка_по_хешу_до_сохранения(cli, chain, andrey_wallet):
    """Форма показывает разбор хеша сразу, не дожидаясь сохранения сделки."""
    r = cli.get(f'/api/tron/payout-tx?hash={_hash()}').get_json()
    assert r['success'] is True
    assert r['amount_usdt'] == 383.14
    assert r['from_address'] == ANDREY_WALLET
    assert r['wallet_id'] == andrey_wallet
    assert r['wallet_label'] == 'Андрей'


def test_неизвестный_кошелёк_не_ломает_сделку(cli, monkeypatch):
    """Перевод с кошелька, которого нет в справочнике: сумма есть, привязки нет."""
    monkeypatch.setattr(appmod, '_tron_tx_info', lambda h: {
        'amount_usdt': 387.78, 'from_address': 'TНеизвестныйКошелёк', 'to_address': 'TClient'})
    r = cli.post('/api/deals', json={
        **ROMAN, 'payout_tx_hashes': [{'hash': _hash()}]}).get_json()
    assert r['deal']['payout_amount_usdt'] == 387.78
    assert r['deal']['payout_wallet_id'] is None


def test_сумму_с_рук_сеть_не_перебивает(cli, chain, andrey_wallet):
    """Если сумма указана явно — верим ей: бывает, что перевод общий на две сделки."""
    r = cli.post('/api/deals', json={
        **ROMAN, 'payout_tx_hashes': [{'hash': _hash(), 'amount_usdt': 350.0}]}).get_json()
    assert r['deal']['payout_amount_usdt'] == 350.0


def test_фаундер_по_телефону_теодор():
    """Фаундера зовут Теодор. «Тёда» приезжало из маппинга по номеру телефона."""
    from deal_chat_analyzer import FOUNDER_BY_PHONE
    assert FOUNDER_BY_PHONE['0991971701'] == 'Теодор'
    assert 'Тёда' not in FOUNDER_BY_PHONE.values()
