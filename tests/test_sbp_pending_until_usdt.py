"""Сделка по СБП не закрывается, пока приход не пересчитан в USDT.

Регресс #519 (19.08.2026): приход 30 750.72 ₽ по sber_wl, выдача с карты
10 700 ฿ = 319.20 USDT. Приход в USDT ещё не считался (рубли не сконвертированы),
но автозавершение для bank_card смотрело только на payout_amount_usdt — сделка
сразу становилась «Завершена» с прибылью −319.20 (−100%), и уведомление с этим
минусом уходило в Telegram, агентам в DM и в Google Sheets.

Правильное поведение: пока payin_amount_usdt пуст — статус pending и никаких
уведомлений; как только USDT проставили — сделка закрывается сама и уведомления
уходят один раз.

Запуск: cd Dev/CalcCRM && python -m pytest tests/test_sbp_pending_until_usdt.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('SECRET_KEY', 'test-secret-key-for-pytest')
os.environ['REESTR_SYNC_ENABLED'] = '0'

import pytest

import app as appmod
from app import (BankCard, CardTopup, CashBatchStatus, Client, Deal, DealStatus,
                 app as flask_app, get_session)


@pytest.fixture(autouse=True)
def clean_db():
    def _wipe():
        s = get_session()
        try:
            s.query(Deal).delete()
            s.query(CardTopup).delete()
            s.query(BankCard).delete()
            s.query(Client).delete()
            s.commit()
        finally:
            s.close()
    _wipe()
    yield
    _wipe()


@pytest.fixture
def sent(monkeypatch):
    """Перехватываем всё, что уходит наружу при завершении сделки."""
    log = {'telegram': [], 'agents': [], 'gsheet': [], 'webhook': []}
    monkeypatch.setattr(appmod, '_send_deal_telegram',
                        lambda deal, *a, **kw: log['telegram'].append(deal.id))
    monkeypatch.setattr(appmod, 'notify_agents_new_deal',
                        lambda db, deal, *a, **kw: log['agents'].append(deal.id))
    monkeypatch.setattr(appmod, 'sync_deals_to_gsheet',
                        lambda deals, *a, **kw: log['gsheet'].extend(d.id for d in deals))
    monkeypatch.setattr(appmod, 'send_deal_completed_webhook',
                        lambda deal, *a, **kw: log['webhook'].append(deal.id))
    return log


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('LOCAL_NO_AUTH', '1')
    flask_app.config['TESTING'] = True
    with flask_app.test_client() as c:
        yield c


def _mk_card():
    s = get_session()
    try:
        card = BankCard(bank_name='IPPS', card_name='e-money VA', holder_name='MF Corporation',
                        balance_thb=0, status=CashBatchStatus.ACTIVE)
        s.add(card)
        s.commit()
        s.add(CardTopup(card_id=card.id, amount_thb=261466.06, cost_usdt=7800.0,
                        purchase_rate=33.5213, source_type='separate'))
        card.balance_thb = 261466.06
        s.commit()
        return card.id
    finally:
        s.close()


def _payload(card_id, **over):
    """Сделка #519: рубли по СБП пришли, в USDT ещё не пересчитаны."""
    data = {
        'deal_type': 'pay_in', 'status': 'pending',
        'client_name': 'grusha & радимир (sansiri)', 'manager_name': 'карим',
        'payin_method': 'sber_wl', 'payin_amount_rub': 30750.72,
        'payout_source': 'bank_card', 'bank_card_id': card_id,
        'payout_method': 'transfer', 'payout_amount_thb': 10700.0,
        'payout_amount_usdt': 319.2,
    }
    data.update(over)
    return data


def test_sbp_without_payin_usdt_stays_pending(client, sent):
    """Приход рублёвый и не сконвертирован → сделка ждёт, не «Завершена»."""
    card_id = _mk_card()
    r = client.post('/api/deals', json=_payload(card_id))
    assert r.status_code == 201
    deal = r.get_json()['deal']
    assert deal['status'] == 'pending'


def test_sbp_without_payin_usdt_sends_nothing(client, sent):
    """Пока прибыль неизвестна — ни TG, ни DM агентам, ни выгрузки."""
    card_id = _mk_card()
    client.post('/api/deals', json=_payload(card_id))
    assert sent['telegram'] == []
    assert sent['agents'] == []
    assert sent['gsheet'] == []
    assert sent['webhook'] == []


def test_payin_usdt_closes_deal_and_notifies(client, sent):
    """Проставили USDT прихода → сделка закрылась сама, уведомления ушли."""
    card_id = _mk_card()
    deal_id = client.post('/api/deals', json=_payload(card_id)).get_json()['deal']['id']

    r = client.put(f'/api/deals/{deal_id}', json={'payin_amount_usdt': 350.5})
    assert r.status_code == 200
    assert r.get_json()['deal']['status'] == 'completed'
    assert sent['telegram'] == [deal_id]
    assert sent['agents'] == [deal_id]


def test_profit_is_positive_after_conversion(client, sent):
    """Прибыль считается от реального прихода, а не от нуля (было −319.20)."""
    card_id = _mk_card()
    deal_id = client.post('/api/deals', json=_payload(card_id)).get_json()['deal']['id']

    deal = client.put(f'/api/deals/{deal_id}', json={'payin_amount_usdt': 350.5}).get_json()['deal']
    assert deal['profit_usdt'] == round(350.5 - 319.2, 2)
    assert deal['profit_usdt'] > 0


def test_usdt_payin_still_closes_on_create(client, sent):
    """Регресс: приход сразу в USDT (крипта) закрывается при создании, как раньше."""
    card_id = _mk_card()
    r = client.post('/api/deals', json=_payload(card_id, payin_method='crypto_direct',
                                                payin_amount_rub=None, payin_amount_usdt=350.5))
    assert r.get_json()['deal']['status'] == 'completed'
    assert sent['telegram'] != []


def test_explicit_status_wins(client, sent):
    """Оператор явно выбрал статус — автозакрытие его не перебивает."""
    card_id = _mk_card()
    deal_id = client.post('/api/deals', json=_payload(card_id)).get_json()['deal']['id']

    r = client.put(f'/api/deals/{deal_id}',
                   json={'payin_amount_usdt': 350.5, 'status': 'pending'})
    assert r.get_json()['deal']['status'] == 'pending'
