"""Тесты реестра обменников (CalcCRM): эндпоинт /api/reestr/all из снапшота,
онлайн-синк из WL-бота (_reestr_upsert + sync_reestr_from_wl с моком requests),
graceful-поведение при недоступном WL-боте.

Запуск: cd Dev/CalcCRM && python -m pytest tests/test_reestr.py -v
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ['SECRET_KEY'] = 'test-secret-key-for-pytest'
os.environ['REESTR_SYNC_ENABLED'] = '0'  # не запускать фоновый тред в тестах

import pytest
import requests

import app as appmod
from app import (app as flask_app, get_session, ReestrSnapshot, ReestrInflow,
                _reestr_upsert, sync_reestr_from_wl, _reestr_inflow_composition)


@pytest.fixture
def client():
    """Авторизованный test client (эндпоинты /api/* за session-аутентификацией)."""
    flask_app.config['TESTING'] = True
    with flask_app.test_client() as c:
        with c.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['display_name'] = 'Test Admin'
        yield c


@pytest.fixture
def clean_snapshots():
    """Чистим таблицу снапшотов до/после теста — изоляция от seed и других тестов."""
    s = get_session()
    s.query(ReestrSnapshot).delete()
    s.commit()
    s.close()
    yield
    s = get_session()
    s.query(ReestrSnapshot).delete()
    s.commit()
    s.close()


def _set_view(view, arr):
    s = get_session()
    _reestr_upsert(s, view, arr)
    s.commit()
    s.close()


def test_reestr_all_empty(client, clean_snapshots):
    """Пустые снапшоты → все массивы пустые, без падений."""
    resp = client.get('/api/reestr/all')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['deals'] == [] and data['brokers'] == [] and data['merchants'] == []


def test_reestr_all_reads_snapshot(client, clean_snapshots):
    """/api/reestr/all отдаёт ровно то, что лежит в reestr_snapshots."""
    _set_view('deals', [{'wl': 'WL-0001', 'usdt': 9.8}])
    _set_view('merchants', [{'name': 'EX1', 'free': 9.8}])
    resp = client.get('/api/reestr/all')
    data = resp.get_json()
    assert len(data['deals']) == 1
    assert data['deals'][0]['wl'] == 'WL-0001' and data['deals'][0]['usdt'] == 9.8
    assert data['deals'][0]['covered'] is False  # нет ручного прихода → не обеспечено
    assert data['merchants'][0]['name'] == 'EX1'
    assert data['updated_at'] is not None


def test_reestr_upsert_overwrites(clean_snapshots):
    """Повторный upsert одного view перезаписывает payload (idempotent, не плодит строки)."""
    _set_view('deals', [{'wl': 'WL-0001'}])
    _set_view('deals', [{'wl': 'WL-0002'}, {'wl': 'WL-0003'}])
    s = get_session()
    rows = s.query(ReestrSnapshot).filter_by(view='deals').all()
    assert len(rows) == 1
    assert len(json.loads(rows[0].payload)) == 2
    s.close()


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload
    def raise_for_status(self):
        pass
    def json(self):
        return self._payload


def test_sync_writes_views(monkeypatch, clean_snapshots):
    """sync_reestr_from_wl пишет deals/requests/merchants из ответа WL-бота, brokers не трогает."""
    payload = {
        'merchants': [{'name': 'EX1', 'free': 100}],
        'deals': [{'wl': 'WL-0001'}, {'wl': 'WL-0002'}],
        'requests': [{'id': 1}],
    }
    monkeypatch.setattr(requests, 'get', lambda *a, **k: _FakeResp(payload))
    # заранее положим brokers — синк не должен их затронуть
    _set_view('brokers', [{'n': '#1'}])

    counts = sync_reestr_from_wl()
    assert counts == {'merchants': 1, 'deals': 2, 'requests': 1}

    s = get_session()
    views = {r.view: json.loads(r.payload) for r in s.query(ReestrSnapshot).all()}
    s.close()
    assert len(views['deals']) == 2
    assert views['merchants'][0]['name'] == 'EX1'
    assert views['brokers'] == [{'n': '#1'}]  # не затронут синком


def test_sync_propagates_network_error(monkeypatch, clean_snapshots):
    """Сетевая ошибка WL-бота пробрасывается (эндпоинт /sync вернёт 502, старый снапшот цел)."""
    def _boom(*a, **k):
        raise requests.exceptions.ConnectionError('WL down')
    monkeypatch.setattr(requests, 'get', _boom)
    with pytest.raises(requests.exceptions.RequestException):
        sync_reestr_from_wl()


def test_sync_endpoint_502_when_wl_down(client, monkeypatch, clean_snapshots):
    """POST /api/reestr/sync при недоступном WL-боте → 502 ok:false, без 500."""
    def _boom(*a, **k):
        raise requests.exceptions.ConnectionError('WL down')
    monkeypatch.setattr(requests, 'get', _boom)
    resp = client.post('/api/reestr/sync')
    assert resp.status_code == 502
    assert resp.get_json()['ok'] is False


# --- ручные приходы: разница раскидывается пропорционально ---

def test_inflow_composition_proportional():
    """Разница (received − Σ) делится пропорционально сумме сделки."""
    deals_by_wl = {
        'WL-001': {'wl': 'WL-001', 'usdt': 3000, 'merchant': 'A', 'status': 'closed'},
        'WL-002': {'wl': 'WL-002', 'usdt': 5000, 'merchant': 'A', 'status': 'closed'},
        'WL-003': {'wl': 'WL-003', 'usdt': 1800, 'merchant': 'B', 'status': 'paid'},
    }
    items, expected, delta = _reestr_inflow_composition(10000, ['WL-001', 'WL-002', 'WL-003'], deals_by_wl)
    assert expected == 9800
    assert delta == 200
    m = {it['wl']: it['margin'] for it in items}
    assert m['WL-001'] == pytest.approx(61.22, abs=0.01)   # 3000/9800*200
    assert m['WL-002'] == pytest.approx(102.04, abs=0.01)
    assert m['WL-003'] == pytest.approx(36.73, abs=0.01)
    assert sum(m.values()) == pytest.approx(200, abs=0.05)  # вся разница разнесена


def test_inflow_composition_negative_delta():
    """Пришло меньше ожидаемого → разница минусовая, маржа отрицательная."""
    deals_by_wl = {'WL-1': {'wl': 'WL-1', 'usdt': 1000, 'merchant': 'A', 'status': 'closed'}}
    items, expected, delta = _reestr_inflow_composition(950, ['WL-1'], deals_by_wl)
    assert expected == 1000 and delta == -50
    assert items[0]['margin'] == pytest.approx(-50)


def test_uncovered_paid_is_advance(client, clean_snapshots):
    """Выплаченная сделка без прихода → статус 'advance' + маржа 'ждём'.
    После прихода → 'closed' + маржа посчитана."""
    _set_view('deals', [{'wl': 'WL-9', 'usdt': 1000, 'merchant': 'A', 'status': 'closed'}])
    s = get_session(); s.query(ReestrInflow).delete(); s.commit(); s.close()

    d = client.get('/api/reestr/all').get_json()['deals'][0]
    assert d['status'] == 'advance' and d['covered'] is False and d['mKnown'] is False

    j = client.post('/api/reestr/inflows', json={'broker': 'X', 'received': 1100, 'deals': ['WL-9']}).get_json()
    assert j['ok']
    d = client.get('/api/reestr/all').get_json()['deals'][0]
    assert d['status'] == 'closed' and d['covered'] is True
    assert d['margin'] == pytest.approx(100)  # вся разница на одну сделку
    s = get_session(); s.query(ReestrInflow).delete(); s.commit(); s.close()


def test_post_and_delete_inflow(client, clean_snapshots):
    """POST заводит приход (считает разницу, пишет в brokers /all), DELETE убирает."""
    _set_view('deals', [
        {'wl': 'WL-001', 'usdt': 3000, 'merchant': 'A', 'status': 'closed'},
        {'wl': 'WL-002', 'usdt': 5000, 'merchant': 'A', 'status': 'closed'},
    ])
    s = get_session(); s.query(ReestrInflow).delete(); s.commit(); s.close()

    resp = client.post('/api/reestr/inflows', json={
        'broker': 'TruidX', 'wallet': 'Tw', 'received': 8100,
        'txhashes': ['hashA'], 'deals': ['WL-001', 'WL-002'],
    })
    j = resp.get_json()
    assert j['ok'] and j['expected'] == 8000 and j['delta'] == 100

    allr = client.get('/api/reestr/all').get_json()
    assert len(allr['brokers']) == 1
    b = allr['brokers'][0]
    assert b['br'] == 'TruidX' and b['got'] == 8100 and b['manual'] is True
    # маржа переопределена в сделках
    dm = {d['wl']: d['margin'] for d in allr['deals']}
    assert dm['WL-001'] == pytest.approx(37.5)   # 3000/8000*100
    assert dm['WL-002'] == pytest.approx(62.5)

    # удаление
    iid = j['id']
    assert client.delete(f'/api/reestr/inflows/{iid}').get_json()['ok']
    assert client.get('/api/reestr/all').get_json()['brokers'] == []
    s = get_session(); s.query(ReestrInflow).delete(); s.commit(); s.close()
