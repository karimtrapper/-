"""Staff catalogue permissions and invalidation of a reconfigured cabinet."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

import app as A


CATALOGUE = '/api/manager/referrers'


@pytest.fixture
def manager_catalogue(monkeypatch):
    monkeypatch.setattr(A, 'TASKS_ENABLED', True)
    monkeypatch.setattr(A, 'STAND_MODE', False)
    monkeypatch.setattr(A, '_login_bot_username_cache', 'synthetic_bot')
    with A.get_session() as db:
        manager = A.AdminUser(username='catalogue-manager', role='manager', password_hash='unused')
        operator = A.AdminUser(username='catalogue-operator', role='operator', password_hash='unused')
        disabled = A.AdminUser(username='catalogue-disabled', role='manager',
                               login_disabled=True, password_hash='unused')
        admin = A.AdminUser(username='catalogue-admin', role='admin', password_hash='unused')
        partner = A.Referrer(name='Catalogue Partner', code='CAT-PARTNER', token='catalogue-old-token',
                             auth_mode='telegram', telegram='@current_handle', telegram_user_id=1234,
                             can_create_links=True, default_percent=37)
        legacy = A.Referrer(name='Catalogue Legacy', code='CAT-LEGACY', token='catalogue-legacy',
                            auth_mode='telegram', telegram='@abc')
        inactive = A.Referrer(name='Catalogue Inactive', code='CAT-INACTIVE',
                              token='catalogue-inactive', active=False)
        demo = A.Referrer(name='Catalogue Demo', code='CAT-DEMO', token='catalogue-demo', is_test=True)
        staff = [manager, operator, disabled, admin]
        referrers = [partner, legacy, inactive, demo]
        db.add_all(staff + referrers)
        db.commit()
        staff_ids = [user.id for user in staff]
        referrer_ids = [referrer.id for referrer in referrers]
    try:
        yield staff_ids, referrer_ids
    finally:
        with A.get_session() as db:
            referrers = db.query(A.Referrer).filter(A.Referrer.code.like('CAT-%')).all()
            ids = [referrer.id for referrer in referrers]
            db.query(A.LoginNonce).filter(A.LoginNonce.referrer_id.in_(ids)).delete()
            for referrer in referrers:
                db.delete(referrer)
            db.query(A.AdminUser).filter(A.AdminUser.id.in_(staff_ids)).delete()
            db.commit()


def _client(uid, **session_values):
    client = A.app.test_client()
    with client.session_transaction() as session:
        session.update(user_id=uid, **session_values)
    return client


def _link(client, referrer_id):
    return client.get(f'{CATALOGUE}/{referrer_id}/cabinet-link')


def test_manager_catalogue_scope_and_validation(manager_catalogue, monkeypatch):
    (manager, operator, disabled, admin), (partner, legacy, inactive, demo) = manager_catalogue
    client = _client(manager)
    catalogue = client.get(CATALOGUE)
    assert catalogue.status_code == 200
    assert 'no-store' in catalogue.headers['Cache-Control']
    rows = {row['id']: row for row in catalogue.json['referrers']}
    assert rows[partner] == {
        'id': partner, 'name': 'Catalogue Partner', 'code': 'CAT-PARTNER',
        'telegram': '@current_handle', 'lang': 'ru', 'auth_mode': 'telegram',
        'can_manage': True, 'can_copy_cabinet_link': True, 'cabinet_has_payment_links': True,
    }
    assert rows[legacy]['can_manage'] and not rows[legacy]['can_copy_cabinet_link']
    assert inactive not in rows and demo not in rows
    assert _link(client, partner).json['url'] == '/ref/catalogue-old-token'
    assert _link(client, legacy).status_code == 404
    assert client.put(f'{CATALOGUE}/{legacy}', json={'name': 'Legacy updated', 'telegram': '@abc'}).status_code == 200
    for referrer_id in (inactive, demo):
        assert _link(client, referrer_id).status_code == 404
        assert client.put(f'{CATALOGUE}/{referrer_id}', json={'name': 'Denied'}).status_code == 404
    assert client.get('/api/referrers').status_code == 403
    assert client.post(CATALOGUE, json={'name': 'Rejected', 'default_percent': 99}).status_code == 400
    assert client.put(f'{CATALOGUE}/{partner}', json={'can_create_links': False}).status_code == 400
    assert client.post(CATALOGUE, json={'name': 'Rejected', 'auth_mode': 'telegram'}).status_code == 400
    assert client.post(CATALOGUE, json={'name': 'Duplicate', 'code': 'CATINACTIVE'}).status_code == 409
    assert client.put(f'{CATALOGUE}/{partner}', json={'code': 'CATLEGACY'}).status_code == 409
    admin_client = _client(admin)
    assert admin_client.post('/api/referrers', json={'name': 'Duplicate', 'code': 'CAT._LEGACY'}).status_code == 400
    assert admin_client.put(f'/api/referrers/{partner}', json={'code': 'CAT._LEGACY'}).status_code == 400
    assert admin_client.get('/api/referrers/lookup', query_string={'code': 'CAT._LEGACY'}).json['referrer']['id'] == legacy

    created = client.post(CATALOGUE, json={'name': 'Created', 'code': 'cat-created', 'auth_mode': 'link'})
    assert created.status_code == 201
    row = created.json['referrer']
    assert row['code'] == 'CAT-CREATED' and row['can_copy_cabinet_link']
    link = _link(client, row['id'])
    assert link.status_code == 200 and 'no-store' in link.headers['Cache-Control']
    assert A.app.test_client().get(f'/api{link.json["url"]}/stats').status_code == 200

    for denied in (admin_client, _client(operator), _client(disabled),
                   _client(manager, stand_ref_preview=partner)):
        assert denied.get(CATALOGUE).status_code in (401, 403, 404)
        assert _link(denied, partner).status_code in (401, 403, 404)
        assert denied.post(CATALOGUE, json={'name': 'Denied'}).status_code in (401, 403, 404)
    monkeypatch.setenv('SERVICE_API_KEY', 'catalogue-service-key')
    anonymous = A.app.test_client()
    assert anonymous.get(CATALOGUE, headers={'X-Api-Key': 'catalogue-service-key'}).status_code == 403
    monkeypatch.setattr(A, 'STAND_MODE', True)
    assert client.get(CATALOGUE).status_code == 404


def test_reconfiguring_cabinet_rotates_token_and_revokes_related_login_state(manager_catalogue):
    (manager, *_), (partner, *_) = manager_catalogue
    client = _client(manager)
    public = A.app.test_client()
    old_url = _link(client, partner).json['url']
    old_token = old_url.rsplit('/', 1)[1]
    with public.session_transaction() as session:
        session['ref_auth'] = {old_token: 1234}
    assert public.get(f'/api{old_url}/stats').status_code == 200
    nonce = public.post(f'/api{old_url}/tg-start').json['nonce']
    with A.get_session() as db:
        db.get(A.LoginNonce, nonce).tg_id = 1234
        db.commit()
        old_profile = db.get(A.Referrer, partner)

    detail = f'{CATALOGUE}/{partner}'
    response = client.put(detail, json={'telegram': 'CURRENT_HANDLE', 'lang': 'en'})
    assert response.status_code == 200
    assert response.json['referrer']['cabinet_has_payment_links']
    assert _link(client, partner).json['url'] == old_url

    response = client.put(detail, json={'telegram': '@new_handle'})
    assert response.status_code == 200
    assert 'cabinet_has_payment_links' not in response.json['referrer']
    telegram_url = _link(client, partner).json['url']
    assert telegram_url != old_url
    assert public.get(f'/api{old_url}/stats').status_code == 404
    assert public.get(f'/api{telegram_url}/stats').status_code == 401
    assert public.get(f'/api{telegram_url}/tg-poll', query_string={'nonce': nonce}).status_code == 404
    assert not A.apply_referrer_tg_binding(old_profile, 1234, 'current_handle')[0]
    with A.get_session() as db:
        assert db.get(A.LoginNonce, nonce) is None
        profile = db.get(A.Referrer, partner)
        assert profile.telegram_user_id is None and not profile.can_create_links
        assert profile.default_percent == 37

    response = client.put(detail, json={'auth_mode': 'link', 'telegram': ''})
    assert response.status_code == 200
    link_url = _link(client, partner).json['url']
    assert link_url != telegram_url
    assert public.get(f'/api{telegram_url}/stats').status_code == 404
    assert public.get(f'/api{link_url}/stats').status_code == 200
    assert public.post(f'/api{link_url}/links/quote', json={}).status_code == 403
    assert client.put(detail, json={'telegram': '@contact_handle'}).status_code == 200
    assert _link(client, partner).json['url'] == link_url
    assert client.put(detail, json={'auth_mode': 'telegram'}).status_code == 200
    assert _link(client, partner).json['url'] != link_url
    assert public.get(f'/api{link_url}/stats').status_code == 404


def test_concurrent_normalized_codes_are_reserved_once(manager_catalogue):
    (manager, _, _, admin), _ = manager_catalogue
    barrier = Barrier(2, timeout=5)

    def create(user, endpoint, code):
        client = _client(user)
        barrier.wait()
        return client.post(endpoint, json={'name': 'Concurrent', 'code': code}).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        manager_result = pool.submit(create, manager, CATALOGUE, 'CAT-RACE')
        admin_result = pool.submit(create, admin, '/api/referrers', 'CAT--RACE')
        assert (manager_result.result(), admin_result.result()) in ((201, 400), (409, 200))
