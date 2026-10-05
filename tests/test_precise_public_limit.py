"""Публичный дорогой endpoint отказывает до постановки фоновой задачи."""
from app import app, limiter
from calculator import playwright_queue


def test_precise_endpoint_has_per_client_limit(monkeypatch):
    app.config['TESTING'] = True
    monkeypatch.setattr(limiter, 'enabled', True)
    called = []
    monkeypatch.setattr(playwright_queue, 'submit', lambda *a, **k: called.append(1))
    client = app.test_client()
    for _ in range(6):
        response = client.post('/api/rates/precise', json={'amount': 0}, environ_base={'REMOTE_ADDR': '192.0.2.66'})
        assert response.status_code == 400
    response = client.post('/api/rates/precise', json={'amount': 0}, environ_base={'REMOTE_ADDR': '192.0.2.66'})
    assert response.status_code == 429
    other_client = client.post('/api/rates/precise', json={'amount': 0},
                               environ_base={'REMOTE_ADDR': '192.0.2.67'})
    assert other_client.status_code == 400
    assert called == []


def test_precise_endpoint_rejects_full_queue_without_fallback(monkeypatch):
    app.config['TESTING'] = True
    monkeypatch.setattr(limiter, 'enabled', False)
    monkeypatch.setattr(playwright_queue, 'submit', lambda *a, **k: {'error': 'queue_full'})
    response = app.test_client().post('/api/rates/precise',
        json={'scenario': 'usdt-to-thb', 'amount': 100},
        environ_base={'REMOTE_ADDR': '192.0.2.68'})
    assert response.status_code == 503
    assert response.get_json()['error'] == 'queue_full'
