"""Task managers are accounts, including when display names collide."""
import uuid

import app as m


def test_stage_manager_directory_and_crm_identity(monkeypatch):
    monkeypatch.setenv('LOCAL_NO_AUTH', '1')
    monkeypatch.setattr(m, 'STAND_MODE', True)
    suffix = uuid.uuid4().hex[:8]
    db = m.get_session()
    users = [m.AdminUser(username=f'{suffix}-{i}', password_hash='unused',
        display_name='Общее имя' if i < 2 else 'Другой',
        role='manager' if i != 2 else 'admin', login_disabled=i == 3)
        for i in range(4)]
    db.add_all(users); db.commit()
    ids = [u.id for u in users]
    db.close()
    try:
        client = m.app.test_client()
        with client.session_transaction() as session:
            session['user_id'] = ids[0]
        plain = client.get('/api/managers')
        assert all(x.get('user_id') not in ids for x in plain.json['managers'])
        response = client.get('/api/managers?include_staff=1')
        assert response.status_code == 200
        staff = [x for x in response.json['managers'] if x.get('user_id') in ids]
        assert {x['user_id'] for x in staff} == set(ids[:2])
        assert len({x['account'] for x in staff}) == 2
        db = m.get_session()
        first, problem = m._crm_manager_user(db, {'manager_user_id': ids[0]})
        second, problem2 = m._crm_manager_user(db, {'manager_user_id': ids[1]})
        assert problem is problem2 is None
        assert first.id != second.id and first.display_name == second.display_name
        for bad in (0, '1', True, ids[2], ids[3]):
            _, error = m._crm_manager_user(db, {'manager_user_id': bad})
            assert error is not None
        db.close()
        db = m.get_session()
        deal = m.Deal(client_name=f'client-{suffix}', deal_type=m.DealType.PAY_IN,
            status=m.DealStatus.PENDING, manager_name='Старое имя', manager_user_id=ids[0])
        db.add(deal); db.commit(); deal_id = deal.id
        db.query(m.AdminUser).filter_by(id=ids[0]).update({'display_name': 'Новое имя'})
        db.commit(); db.close()
        ordinary = client.put(f'/api/deals/{deal_id}', json={'notes': 'ordinary'})
        assert ordinary.status_code == 200, ordinary.json
        assert ordinary.json['deal']['manager_user_id'] == ids[0]
        assert ordinary.json['deal']['manager_name'] == 'Новое имя'
        archived = client.put(f'/api/deals/{deal_id}', json={
            'manager_user_id': None, 'manager_name': 'Legacy manager'})
        assert archived.status_code == 200, archived.json
        assert archived.json['deal']['manager_user_id'] is None
        assert archived.json['deal']['manager_name'] == 'Legacy manager'
    finally:
        db = m.get_session()
        db.query(m.Deal).filter(m.Deal.client_name == f'client-{suffix}').delete()
        db.query(m.AdminUser).filter(m.AdminUser.id.in_(ids)).delete()
        db.commit(); db.close()
