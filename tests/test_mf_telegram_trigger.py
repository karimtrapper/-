"""
Когда MF-сделка уведомляет в Telegram.

Инцидент 05.08: сделку #458 завели, потом в редакторе выставили тип «через MF
Corp» — выгрузка в таблицу отработала (лист «август leasehold» создался), а
уведомление не пришло: TG для MF слался ТОЛЬКО в create_deal, а правка идёт
через PUT. Оператор жмёт «Завершить» и ждёт сообщение, как у обычных сделок.

Запуск: cd Dev/CalcCRM && python -m pytest tests/test_mf_telegram_trigger.py -v
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ['SECRET_KEY'] = 'test-secret-key-for-pytest'

import app as A
from app import get_session, Deal, Client, DealAgent, AdminUser

MF = {'deal_kind': 'mf_realty', 'deal_type': 'pay_in', 'payin_method': 'crypto_direct',
      'payin_amount_usdt': 512000, 'invoice_amount_thb': 16742400,
      'buy_rate_thb_usdt': 33.20, 'company_percent': 0.9}


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
def sent(monkeypatch):
    """Перехватываем отправку — сеть не трогаем, считаем вызовы."""
    box = []
    monkeypatch.setattr(A, 'send_telegram_notification', lambda text, thread_id=None: box.append(text))
    monkeypatch.setattr(A, 'sync_realty_deal_to_gsheet', lambda d: {'ok': False})
    monkeypatch.setattr(A, 'sync_deals_to_gsheet', lambda d: None)
    return box


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


def test_pending_create_does_not_notify(tc, sent):
    """Сделка в работе — уведомление рано: его ждут после «Завершить»."""
    r = tc.post('/api/deals', json={**MF, 'client_name': 'Pending MF'})
    assert r.json['success']
    assert sent == []


def test_completing_notifies(tc, sent):
    """Кнопка «Завершить» шлёт PUT со статусом — уведомление должно уйти."""
    did = tc.post('/api/deals', json={**MF, 'client_name': 'Done MF'}).json['deal']['id']
    tc.put(f'/api/deals/{did}', json={'status': 'completed'})
    assert len(sent) == 1
    assert sent[0].startswith('🏠')


def test_created_completed_notifies_once(tc, sent):
    """Сразу завершённая уведомляет при создании и не дублирует при повторном сохранении."""
    d = tc.post('/api/deals', json={**MF, 'client_name': 'Instant MF', 'status': 'completed'}).json['deal']
    assert len(sent) == 1
    tc.put(f"/api/deals/{d['id']}", json={'status': 'completed', 'company_percent': 1.0})
    assert len(sent) == 1, 'повторное сохранение завершённой не должно слать второе'


def test_ordinary_deal_turned_into_mf_notifies(tc, sent):
    """Кейс #458: завершённую обычную сделку переделали в MF — уведомления ещё не было."""
    did = tc.post('/api/deals', json={
        'client_name': 'Was Exchange', 'deal_type': 'pay_in', 'payin_method': 'crypto_direct',
        'payin_amount_usdt': 1000, 'payout_method': 'transfer', 'payout_source': 'binance',
        'payout_amount_thb': 33000, 'status': 'completed'}).json['deal']['id']
    sent.clear()
    tc.put(f'/api/deals/{did}', json={**MF, 'status': 'completed'})
    assert len(sent) == 1
    assert sent[0].startswith('🏠')


def test_edit_of_pending_does_not_notify(tc, sent):
    """Правка незавершённой MF-сделки молчит — иначе спам на каждое сохранение."""
    did = tc.post('/api/deals', json={**MF, 'client_name': 'Edit MF'}).json['deal']['id']
    tc.put(f'/api/deals/{did}', json={'company_percent': 1.2})
    tc.put(f'/api/deals/{did}', json={'realty_purpose': 'Villa 7'})
    assert sent == []
