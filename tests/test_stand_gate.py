"""Ворота стенда проверяются в новом процессе: conftest меняет окружение при импорте."""

import os
import subprocess
import sys


def _run(code, tmp_path, stand=True):
    env = {k: v for k, v in os.environ.items() if k not in (
        'DATABASE_URL', 'STAND_MODE', 'LOCAL_NO_AUTH', 'SERVICE_API_KEY')}
    env.update(DATABASE_URL=f'sqlite:///{tmp_path / "gate.db"}',
               SECRET_KEY='gate-test-secret', STAND_MODE='1' if stand else '0',
               STAND_PASSWORD='gate-password', SERVICE_API_KEY='service-secret',
               LOCAL_NO_AUTH='0', REESTR_SYNC_ENABLED='0', PAYMENT_POLL_ENABLED='0',
               PAYIN_ADDR_BACKFILL='0', TRONSCAN_WARM_ENABLED='0',
               KYC_RETENTION_ENABLED='0', STAND_TRANSFER_POLL_ENABLED='0')
    result = subprocess.run([sys.executable, '-c', code], cwd=os.path.dirname(os.path.dirname(__file__)),
                            env=env, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr


def test_stand_gate_roles_and_preview(tmp_path):
    _run('''
import app as m
import os
from datetime import datetime
from flask import session
from sqlalchemy import text

db = m.get_session()
karim = db.query(m.AdminUser).filter_by(username='karim').one()
marina = db.query(m.AdminUser).filter_by(username='marina').one()
assert karim.notify_enabled and not marina.notify_enabled
assert not karim.login_disabled
ref = m.Referrer(name='Preview', code='PREVIEW', token='previewtoken', auth_mode='telegram',
                 telegram_user_id=999, active=True)
link_ref = m.Referrer(name='Link', code='LINK', token='linktoken', auth_mode='link', active=True)
disabled = m.AdminUser(username='prod_user', password_hash=m.AdminUser.hash_password('secret'),
                       telegram='@produser', telegram_user_id=777, login_disabled=True, role='admin')
db.add_all([ref, link_ref, disabled]); db.commit()
rid, mid, kid, did = ref.id, marina.id, karim.id, disabled.id
db.close()

with m.app.test_client() as c:
    open_paths = {'/login': 200, '/api/auth/login': 400, '/api/auth/logout': 200,
                  '/api/auth/me': 401, '/api/health': 200,
                  '/static/kyc/grusha-logo.png': 200, '/kyc/grusha-logo.png': 200}
    for path, expected in open_paths.items():
        response = c.post(path, json={}) if path == '/api/auth/login' else (
            c.post(path) if path == '/api/auth/logout' else c.get(path))
        assert response.status_code == expected, (path, response.status_code)
        assert response.headers['Referrer-Policy'] == 'no-referrer'
    closed = ['/crm', '/tasks', '/static/stand/tasks.html', '/ref/previewtoken',
              '/api/ref/previewtoken/stats', '/api/partner/x', '/api/kyc/submit',
              '/api/tg/x', '/api/webhook/x', '/api/sber-incomes/ingest',
              '/api/auth/tg-start', '/api/auth/tg-poll', '/api/auth/tg-login',
              '/api/auth/tg-config', '/api/auth/setup', '/api/admins',
              '/api/stand/reset', '/api/stand/ref-preview/%s' % rid, '/api/rates']
    for path in closed:
        response = c.get(path, headers={'X-Api-Key': 'service-secret'})
        expected = 401 if path.startswith('/api/') else 302
        assert response.status_code == expected, (path, response.status_code)
    os.environ['LOCAL_NO_AUTH'] = '1'
    assert c.get('/login').status_code == 200
    assert c.get('/api/ref/previewtoken/stats').status_code == 401
    os.environ['LOCAL_NO_AUTH'] = '0'
    assert c.post('/api/auth/login', json={'username':'prod_user','password':'secret'}).status_code == 401
    assert c.post('/api/auth/login', json={'username':'marina','password':'gate-password'}).status_code == 200
    for path in ['/api/auth/tg-start', '/api/auth/tg-poll', '/api/auth/tg-login',
                 '/api/auth/tg-config', '/api/auth/setup', '/api/tg/x', '/api/webhook/x',
                 '/api/sber-incomes/ingest']:
        assert c.get(path).status_code == 403, path
    assert c.put('/api/admins/%s' % mid, json={'role':'admin'},
                 headers={'X-Api-Key':'service-secret'}).status_code == 403
    assert c.put('/api/admins/%s' % mid, json={'notify_enabled':True}).status_code == 403
    assert c.get('/api/admins').status_code == 403
    assert c.get('/api/stand/ref-preview/%s' % rid).status_code == 403
    assert c.get('/api/ref/linktoken/stats').status_code == 401
    assert c.post('/api/ref/previewtoken/tg-start').status_code == 403
    db = m.get_session(); assert db.query(m.AdminUser).get(mid).role == 'manager'; db.close()
    c.post('/api/auth/logout')
    assert c.post('/api/auth/login', json={'username':'karim','password':'gate-password'}).status_code == 200
    assert c.get('/api/admins').status_code == 200
    assert c.put('/api/admins/%s' % mid, json={'role':'unknown'}).status_code == 400
    assert c.post('/api/admins', json={'display_name':'X','username':'x','role':'unknown'}).status_code == 400
    assert c.put('/api/admins/%s' % mid, json={'role':'operator','notify_enabled':True}).status_code == 200
    assert c.put('/api/admins/%s' % kid, json={'role':'manager'}).status_code == 400
    assert c.put('/api/admins/%s' % kid, json={'login_disabled':True}).status_code == 400
    assert c.delete('/api/admins/%s' % kid).status_code == 400
    preview = c.get('/api/stand/ref-preview/%s' % rid)
    assert preview.status_code == 302 and preview.location.endswith('/ref/previewtoken')
    assert c.get('/api/ref/previewtoken/stats').status_code == 200
    assert c.put('/api/admins/%s' % mid, json={'role':'manager','login_disabled':False}).status_code == 200
    assert c.put('/api/admins/%s' % kid, json={'notify_enabled':False}).status_code == 200
    assert c.put('/api/admins/%s' % did, json={'login_disabled':False}).status_code == 200
    assert c.put('/api/admins/%s' % kid, json={'role':'manager'}).status_code == 400
    db = m.get_session(); db.query(m.AdminUser).get(kid).role = 'manager'; db.commit(); db.close()
    assert c.get('/api/ref/previewtoken/stats').status_code == 401
    c.post('/api/auth/logout')
    assert c.get('/api/stand/ref-preview/%s' % rid).status_code == 401
    db = m.get_session()
    assert m._match_admin_by_tg(db, 777, 'produser') is not None  # re-enabled above
    disabled = db.query(m.AdminUser).get(did); disabled.login_disabled = True; db.commit()
    assert m._match_admin_by_tg(db, 777, 'produser') is None
    disabled.telegram_user_id = None; db.commit()
    assert m._match_admin_by_tg(db, 888, 'produser') is None
    assert disabled.telegram_user_id is None
    nonce = m.LoginNonce(nonce='disabled-nonce', admin_id=did, created_at=datetime.utcnow())
    db.add(nonce); db.commit(); db.close()
    assert c.get('/api/auth/tg-poll?nonce=disabled-nonce').status_code == 401
    with m.app.test_request_context('/api/auth/tg-poll?nonce=disabled-nonce'):
        assert m.auth_tg_poll().get_json()['status'] == 'denied'
    with m.app.test_request_context('/api/auth/tg-login', method='POST', json={'id':777,'username':'produser'}):
        m.verify_telegram_auth = lambda *args: True
        assert m.auth_tg_login()[1] == 403
''', tmp_path)


def test_seed_keeps_changed_role_after_restart(tmp_path):
    _run('''
import app as m
db=m.get_session(); user=db.query(m.AdminUser).filter_by(username='marina').one()
user.role='operator'; user.notify_enabled=True; db.commit(); db.close()
    ''', tmp_path)
    _run('''
import app as m
db=m.get_session(); user=db.query(m.AdminUser).filter_by(username='marina').one()
assert user.role=='operator' and user.notify_enabled
db.close()
''', tmp_path)


def test_sqlite_migration_adds_missing_flags(tmp_path):
    _run('''
import app as m
from sqlalchemy import text
with m.engine.begin() as conn:
    conn.execute(text('ALTER TABLE admin_users DROP COLUMN login_disabled'))
    conn.execute(text('ALTER TABLE admin_users DROP COLUMN notify_enabled'))
''', tmp_path)
    _run('''
import app as m
from sqlalchemy import inspect
cols={c['name'] for c in inspect(m.engine).get_columns('admin_users')}
assert {'login_disabled', 'notify_enabled'} <= cols
m._migrate_admin_access()
db=m.get_session()
assert db.query(m.AdminUser).filter_by(username='karim').one().login_disabled is False
db.close()
''', tmp_path)


def test_production_public_paths_unchanged(tmp_path):
    _run('''
import app as m
with m.app.test_client() as c:
    for path in ['/api/auth/tg-config', '/api/ref/missing/stats', '/api/rates']:
        assert c.get(path).status_code != 401, path
    assert 'Referrer-Policy' not in c.get('/api/health').headers
''', tmp_path, stand=False)
