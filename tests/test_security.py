"""
Тесты безопасности — проверяют что защищённые страницы и API
недоступны без авторизации, а публичные — доступны.

Запуск: cd Dev/CalcCRM && python -m pytest tests/test_security.py -v

Эти тесты ловят типичные баги:
- Страница доступна без логина (забыли auth-проверку)
- API-эндпоинт не в PUBLIC_PATHS, но пропускает
- Статика CRM/калькулятора открыта (утечка кода)
- Новый роут добавлен без auth — тест упадёт
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('SECRET_KEY', 'test-secret-key-for-pytest')
os.environ.setdefault('DATABASE_URL', '')  # SQLite fallback

from app import app


@pytest.fixture
def client():
    """Flask test client без авторизации"""
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def auth_client():
    """Flask test client с авторизацией (через сессию)"""
    app.config['TESTING'] = True
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['display_name'] = 'Test Admin'
        yield c


# ── Страницы: без логина → редирект на /login ──────────────────────────

class TestPagesRequireAuth:
    """Все страницы кроме /login и /kyc/ должны требовать авторизацию"""

    @pytest.mark.parametrize("path", [
        "/",
        "/crm",
    ])
    def test_page_redirects_to_login(self, client, path):
        resp = client.get(path, follow_redirects=False)
        assert resp.status_code in (301, 302), f"{path} не редиректит (status={resp.status_code})"
        assert '/login' in resp.headers.get('Location', ''), f"{path} редиректит не на /login"

    @pytest.mark.parametrize("path", [
        "/calculator/calculator.js",
        "/calculator/index.html",
        "/crm/crm.js",
        "/crm/style.css",
    ])
    def test_static_blocked_without_auth(self, client, path):
        resp = client.get(path, follow_redirects=False)
        assert resp.status_code in (301, 302, 401, 404), \
            f"{path} доступен без авторизации (status={resp.status_code})"

    @pytest.mark.parametrize("path", [
        "/login",
        "/kyc/",
    ])
    def test_public_pages_accessible(self, client, path):
        resp = client.get(path, follow_redirects=False)
        assert resp.status_code == 200, f"{path} недоступен (status={resp.status_code})"


# ── API: без логина → 401 ──────────────────────────────────────────────

class TestAPIRequiresAuth:
    """Приватные API-эндпоинты должны возвращать 401 без авторизации"""

    @pytest.mark.parametrize("method,path", [
        ("GET", "/api/deals"),
        ("POST", "/api/deals"),
        ("GET", "/api/wallets"),
        ("GET", "/api/clients"),
        ("GET", "/api/managers"),
        ("GET", "/api/analytics/dashboard"),
        ("GET", "/api/reimbursements"),
        ("GET", "/api/reimbursements/pending"),
        ("POST", "/api/proxy/create-payment"),
        ("GET", "/api/cards"),
        ("GET", "/api/cards/balance"),
        ("GET", "/api/doverka/payments"),
        ("GET", "/api/wallets/summary"),
    ])
    def test_api_returns_401(self, client, method, path):
        if method == "GET":
            resp = client.get(path)
        else:
            resp = client.post(path, json={})
        assert resp.status_code == 401, f"{method} {path} не вернул 401 (status={resp.status_code})"


class TestPublicAPIAccessible:
    """Публичные API должны работать без авторизации"""

    @pytest.mark.parametrize("method,path", [
        ("GET", "/api/rates"),
        ("GET", "/api/health"),
        ("POST", "/api/auth/login"),
    ])
    def test_public_api_no_401(self, client, method, path):
        if method == "GET":
            resp = client.get(path)
        else:
            resp = client.post(path, json={"username": "", "password": ""})
        assert resp.status_code != 401, f"{method} {path} требует авторизацию, но должен быть публичным"


# ── С логином: всё работает ────────────────────────────────────────────

class TestAuthenticatedAccess:
    """Залогиненный пользователь видит страницы и API"""

    @pytest.mark.parametrize("path", [
        "/",
        "/crm",
    ])
    def test_pages_accessible_with_auth(self, auth_client, path):
        resp = auth_client.get(path, follow_redirects=False)
        assert resp.status_code == 200, f"{path} недоступен с авторизацией (status={resp.status_code})"

    def test_api_deals_accessible_with_auth(self, auth_client):
        resp = auth_client.get("/api/deals")
        assert resp.status_code == 200


# ── Cookie безопасность ────────────────────────────────────────────────

class TestCookieSecurity:
    """Куки сессии должны иметь правильные флаги"""

    def test_session_cookie_flags(self):
        assert app.config.get('SESSION_COOKIE_HTTPONLY') is True, "SESSION_COOKIE_HTTPONLY не включён"
        assert app.config.get('SESSION_COOKIE_SAMESITE') == 'Lax', "SESSION_COOKIE_SAMESITE не Lax"

    def test_session_lifetime(self):
        lifetime = app.permanent_session_lifetime
        assert lifetime.days >= 7, f"Сессия слишком короткая: {lifetime.days} дней"
        assert lifetime.days <= 90, f"Сессия слишком длинная: {lifetime.days} дней"
