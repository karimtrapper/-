"""Exercise cabinet link permissions through the authenticated CRM endpoints."""
import pytest

import app as A


@pytest.fixture
def cabinet_deals(monkeypatch):
    monkeypatch.setattr(A, 'TASKS_ENABLED', True)
    monkeypatch.setattr(A, 'STAND_MODE', False)
    A.StandCrmLink.__table__.create(A.engine, checkfirst=True)
    with A.get_session() as db:
        staff = {
            username: A.AdminUser(username=f'cabinet-{username}', display_name='Same Name',
                                  role=role, password_hash='unused')
            for username, role in [('owner', 'manager'), ('other', 'manager'), ('admin', 'admin')]
        }
        referrers = {
            key: A.Referrer(name=f'Cabinet {key}', code=f'TEST-CAB-{key}', token=f'synthetic-{key}',
                            auth_mode=mode, telegram=telegram, telegram_user_id=tg_id, active=active)
            for key, mode, telegram, tg_id, active in [
                ('legacy', 'telegram', '@Cabinet_User', None, True),
                ('agent', 'telegram', None, 12345678, True),
                ('detached', 'telegram', '@Detached_User', None, True),
                ('open', 'link', None, None, True),
                ('default-mode', 'link', None, None, True),
                ('test', 'link', None, None, True),
                ('missing', 'telegram', '', None, True),
                ('invalid', 'telegram', 'not a handle', None, True),
                ('inactive', 'telegram', '@Inactive_User', None, False),
            ]
        }
        referrers['test'].is_test = True
        db.add_all([*staff.values(), *referrers.values()])
        db.flush()
        referrers['default-mode'].auth_mode = None
        owned = A.Deal(deal_type=A.DealType.PAY_IN, manager_user_id=staff['owner'].id,
                       referrer_id=referrers['legacy'].id)
        nameless = A.Deal(deal_type=A.DealType.PAY_IN, manager_name='Same Name',
                          referrer_id=referrers['legacy'].id)
        named_only = A.Deal(deal_type=A.DealType.PAY_IN, manager_user_id=staff['owner'].id,
                            referrer_name=referrers['detached'].name)
        db.add_all((owned, nameless, named_only))
        db.flush()
        attached = [
            A.DealAgent(deal_id=owned.id, referrer_id=referrers[key].id)
            for key in ('agent', 'agent', 'open', 'default-mode', 'test', 'missing', 'invalid', 'inactive')
        ]
        db.add_all(attached)
        db.commit()
        deal_ids = [owned.id, nameless.id, named_only.id]
        staff_ids = {key: row.id for key, row in staff.items()}
        referrer_ids = {key: row.id for key, row in referrers.items()}
    try:
        yield deal_ids, staff_ids, referrer_ids
    finally:
        with A.get_session() as db:
            db.query(A.DealAgent).filter(A.DealAgent.deal_id.in_(deal_ids)).delete()
            db.query(A.Deal).filter(A.Deal.id.in_(deal_ids)).delete()
            db.query(A.AdminUser).filter(A.AdminUser.id.in_(staff_ids.values())).delete()
            db.query(A.Referrer).filter(A.Referrer.id.in_(referrer_ids.values())).delete()
            db.commit()


def _signed_in_client(user_id, **state):
    client = A.app.test_client()
    with client.session_transaction() as session:
        session.update(user_id=user_id, **state)
    return client


def test_manager_can_copy_only_eligible_attached_cabinet_links(cabinet_deals, monkeypatch):
    (owned, nameless, named_only), staff, refs = cabinet_deals
    client = _signed_in_client(staff['owner'])
    detail = f'/api/deals/{owned}'

    def link(client, key, deal=owned):
        return client.get(f'/api/deals/{deal}/referrers/{refs[key]}/cabinet-link')

    response = client.get(detail)
    allowed = ('legacy', 'agent', 'open', 'default-mode')
    assert response.json['deal']['cabinet_link_referrer_ids'] == sorted(refs[key] for key in allowed)
    assert 'no-store' in response.headers['Cache-Control']
    assert b'synthetic-' not in response.data
    for key in allowed:
        response = link(client, key)
        assert response.json == {'success': True, 'url': f'/ref/synthetic-{key}'}
        assert 'no-store' in response.headers['Cache-Control']
        expected_status = 401 if key in ('legacy', 'agent') else 200
        assert client.get(f'/api{response.json["url"]}/stats').status_code == expected_status
    for key in ('detached', 'test', 'missing', 'invalid', 'inactive'):
        response = link(client, key)
        assert response.status_code == 404
        assert b'synthetic-' not in response.data
    assert link(client, 'legacy', nameless).status_code == 404
    assert link(client, 'detached', named_only).status_code == 404

    listing = client.get('/api/deals')
    assert listing.status_code == 200
    assert b'cabinet_link_referrer_ids' not in listing.data
    assert b'synthetic-' not in listing.data
    for unauthorized in (
        _signed_in_client(staff['other']), _signed_in_client(staff['admin']),
        _signed_in_client(staff['owner'], stand_ref_preview=refs['legacy']),
    ):
        assert 'cabinet_link_referrer_ids' not in unauthorized.get(detail).json['deal']
        assert link(unauthorized, 'legacy').status_code in (403, 404)

    monkeypatch.setenv('SERVICE_API_KEY_RO', 'synthetic-read-only')
    response = A.app.test_client().get(
        f'{detail}/referrers/{refs["legacy"]}/cabinet-link',
        headers={'X-Api-Key': 'synthetic-read-only'},
    )
    assert response.status_code == 403

    with A.get_session() as db:
        db.query(A.DealAgent).filter_by(deal_id=owned, referrer_id=refs['open']).delete()
        db.get(A.Deal, owned).referrer_id = None
        db.commit()
    assert link(client, 'open').status_code == 404
    assert link(client, 'legacy').status_code == 404
    assert client.get(detail).json['deal']['cabinet_link_referrer_ids'] == [refs['agent'], refs['default-mode']]

    with A.get_session() as db:
        db.get(A.Deal, owned).manager_user_id = staff['other']
        db.commit()
    assert link(client, 'default-mode').status_code == 404
    assert 'cabinet_link_referrer_ids' not in client.get(detail).json['deal']
    new_owner = _signed_in_client(staff['other'])
    assert link(new_owner, 'default-mode').status_code == 200

    monkeypatch.setattr(A, 'STAND_MODE', True)
    assert 'cabinet_link_referrer_ids' not in new_owner.get(detail).json['deal']
    assert link(new_owner, 'default-mode').status_code == 404
