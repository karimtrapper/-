"""Read-only сервисный ключ (SERVICE_API_KEY_RO) — доступ Claude Code фаундера.

Ключ даёт смотреть сделки, рефералов, возмещения и балансы и не даёт ничего
менять. Проверяем именно границы: метод, набор путей, невлияние на основной
ключ. Отдельно — поиск сделок `?q=`, ради которого этот доступ вообще нужен
(без него «найди сделки Сергея» = выкачать все страницы).

Запуск: cd Dev/CalcCRM && python -m pytest tests/test_readonly_key.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('SECRET_KEY', 'test-secret-key-for-pytest')
os.environ['REESTR_SYNC_ENABLED'] = '0'

import pytest

from app import app as flask_app, Client, Deal, DealStatus, DealType, get_session

RO = 'ro-test-key'
FULL = 'full-test-key'


@pytest.fixture
def cli(monkeypatch):
    """Клиент с включённой авторизацией — LOCAL_NO_AUTH снят намеренно."""
    flask_app.config['TESTING'] = True
    monkeypatch.delenv('LOCAL_NO_AUTH', raising=False)
    monkeypatch.setenv('SERVICE_API_KEY', FULL)
    monkeypatch.setenv('SERVICE_API_KEY_RO', RO)
    with flask_app.test_client() as c:
        yield c


def ro(cli, path, method='get', **kw):
    return getattr(cli, method)(path, headers={'X-Api-Key': RO}, **kw)


class TestReadOnlyScope:
    def test_get_deals_allowed(self, cli):
        assert ro(cli, '/api/deals').status_code == 200

    def test_referrers_and_reimbursements_allowed(self, cli):
        assert ro(cli, '/api/referrers').status_code == 200
        assert ro(cli, '/api/reimbursements/pending').status_code == 200
        assert ro(cli, '/api/wallets/summary').status_code == 200

    def test_write_methods_forbidden(self, cli):
        for method, path in (('post', '/api/deals'), ('delete', '/api/deals/1'),
                             ('put', '/api/deals/1')):
            resp = ro(cli, path, method=method, json={})
            assert resp.status_code == 403, f'{method} {path}'
            assert resp.get_json()['error'] == 'read_only_key'

    def test_kyc_photos_out_of_scope(self, cli):
        """Паспорта и селфи клиентов — не то, что уезжает в чужой контекст."""
        resp = ro(cli, '/api/kyc/list')
        assert resp.status_code == 403
        assert resp.get_json()['error'] == 'read_only_key_scope'

    def test_paid_llm_endpoint_out_of_scope(self, cli):
        """GET, но каждый вызов гоняет модель по чату — за деньги."""
        resp = ro(cli, '/api/bitrix/deals/647/analyze')
        assert resp.status_code == 403
        assert resp.get_json()['error'] == 'read_only_key_scope'

    def test_admins_out_of_scope(self, cli):
        assert ro(cli, '/api/admins').status_code == 403

    def test_full_key_still_writes(self, cli):
        """RO-ветка не должна перехватывать основной ключ ботов."""
        resp = cli.post('/api/deals', headers={'X-Api-Key': FULL}, json={})
        assert resp.status_code != 403

    def test_wrong_key_unauthorized(self, cli):
        resp = cli.get('/api/deals', headers={'X-Api-Key': 'мимо'})
        assert resp.status_code == 401

    def test_no_ro_env_no_access(self, cli, monkeypatch):
        monkeypatch.delenv('SERVICE_API_KEY_RO', raising=False)
        assert ro(cli, '/api/deals').status_code == 401


class TestDealSearch:
    @pytest.fixture
    def deals(self):
        db = get_session()
        made = []
        try:
            cl = Client(name='Сергей Петров')
            db.add(cl)
            db.flush()
            for name, client_id, referrer in (('Сергей Петров', cl.id, None),
                                              ('John Smith', None, 'GR-KARIM')):
                d = Deal(deal_type=DealType.PAY_IN, status=DealStatus.COMPLETED,
                         client_id=client_id, client_name=name, referrer_name=referrer,
                         manager_name='Валера')
                db.add(d)
                db.flush()
                made.append(d.id)
            db.commit()
            yield made
        finally:
            for did in made:
                obj = db.get(Deal, did)
                if obj:
                    db.delete(obj)
            db.commit()
            db.close()

    def test_search_by_cyrillic_name(self, cli, deals):
        body = ro(cli, '/api/deals?q=сергей').get_json()
        ids = [d['id'] for d in body['deals']]
        assert deals[0] in ids and deals[1] not in ids

    def test_search_by_latin_name(self, cli, deals):
        body = ro(cli, '/api/deals?q=smith').get_json()
        assert deals[1] in [d['id'] for d in body['deals']]

    def test_search_by_referrer(self, cli, deals):
        body = ro(cli, '/api/deals?q=GR-KARIM').get_json()
        assert [d['id'] for d in body['deals']] == [deals[1]]

    def test_search_by_deal_id(self, cli, deals):
        body = ro(cli, f'/api/deals?q={deals[0]}').get_json()
        assert [d['id'] for d in body['deals']] == [deals[0]]

    def test_search_miss_returns_empty(self, cli, deals):
        body = ro(cli, '/api/deals?q=никогонет').get_json()
        assert body['deals'] == [] and body['total'] == 0
