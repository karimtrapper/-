"""Stage HTML response coverage for real Flask file aliases and HTTP validators."""

import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('mode', ['0', '1'])
def test_served_html_file_aliases_and_ranges(tmp_path, mode):
    # Import app in a fresh, synthetic process because STAND_MODE is import-time.
    env = {'PATH': os.environ.get('PATH', ''), 'PYTHONPATH': str(ROOT),
           'STAND_MODE': mode, 'DATABASE_URL': 'sqlite:///' + str(tmp_path / 'fixture.db'),
           'SECRET_KEY': 'synthetic-alias-test', 'STAND_PASSWORD': 'synthetic-pass',
           'LOCAL_NO_AUTH': '0', 'REESTR_SYNC_ENABLED': '0',
           'PAYMENT_POLL_ENABLED': '0', 'PAYIN_ADDR_BACKFILL': '0',
           'KYC_RETENTION_ENABLED': '0', 'TRONSCAN_WARM_ENABLED': '0',
           'STAND_TRANSFER_POLL_ENABLED': '0'}
    code = r'''
from pathlib import Path
import app
from stand_browser import PAGE_SOURCES, STAND_CSP, transform_html

client = app.app.test_client()
if not app.STAND_MODE:
    db = app.SessionLocal()
    db.add(app.AdminUser(username='synthetic', display_name='Synthetic',
                         password_hash=app.AdminUser.hash_password('synthetic-pass')))
    db.commit()
    db.close()
with client.session_transaction() as sess:
    sess['user_id'] = 1

paths = {
    'calculator': ('/', '/static/calculator/index.html',
                   '/static/calculator/index.html/', '/static/calculator/./index.html'),
    'crm': ('/crm', '/static/crm/crm.html', '/static/crm/crm.html/',
            '/static/crm/./crm.html', '/static/crm//crm.html',
            '/static/crm/%2e/crm.html', '/static/crm/CRM.HTML',
            '/static/stand/../crm/crm.html', '/crm/./crm.html'),
    'login': ('/login', '/static/auth/login.html', '/static/auth/login.html/',
              '/static/auth/%2e/login.html', '/auth/./login.html'),
    'kyc': ('/kyc/', '/static/kyc/index.html', '/kyc/index.html/',
            '/static/kyc/./index.html'),
    'partner': ('/partner/synthetic', '/static/partner/index.html',
                '/static/partner/index.html/', '/partner/synthetic/index.html/',
                '/static/partner/./index.html'),
    'referrer': ('/ref/synthetic', '/static/referrer/index.html',
                 '/static/referrer/index.html/', '/static/referrer//index.html'),
    'tasks': ('/tasks', '/static/stand/tasks.html', '/tasks/tasks.html/',
              '/static/stand/./tasks.html'),
    'walkthrough': ('/tasks/walkthrough/leasehold-rub.html',
                    '/static/stand/walkthrough/leasehold-rub.html',
                    '/static/stand/walkthrough/leasehold-rub.html/',
                    '/tasks/walkthrough/../walkthrough/leasehold-rub.html'),
}
conditional = ({'If-Modified-Since': 'Wed, 21 Oct 2037 07:28:00 GMT'},
               {'If-None-Match': '*'}, {'Range': 'bytes=0-400'},
               {'Range': 'bytes=0-400', 'If-Range': 'Wed, 21 Oct 2037 07:28:00 GMT'})
for kind, urls in paths.items():
    raw = Path(PAGE_SOURCES[kind]).read_bytes()
    transformed = transform_html(kind, raw.decode()).encode()
    for url in urls:
        for headers in ({}, *conditional):
            for method in ('GET', 'HEAD'):
                response = client.open(url + '?fixture=1', method=method, headers=headers)
                if not app.STAND_MODE and url.startswith('/tasks'):
                    assert response.status_code in (302, 404), (url, method, headers)
                    continue
                if response.status_code in (302, 404):
                    # Routing may reject an alias on another OS. It must not
                    # serve a raw 200 if the file does resolve there.
                    assert response.data != raw, (url, method, headers)
                    continue
                if app.STAND_MODE:
                    assert response.status_code == 200, (url, method, headers, response.status_code)
                    assert response.headers['Content-Security-Policy'] == STAND_CSP
                    assert response.headers['Cache-Control'] == 'no-store'
                    assert not any(h in response.headers for h in
                                   ('Content-Range', 'ETag', 'Last-Modified'))
                    assert response.content_length == len(transformed)
                    assert response.data == (b'' if method == 'HEAD' else transformed)
                else:
                    assert 'Content-Security-Policy' not in response.headers
                    if response.status_code == 200:
                        assert response.data == (b'' if method == 'HEAD' else raw), url
                    elif response.status_code == 206:
                        assert response.headers['Content-Range'].startswith('bytes 0-400/')
                        assert response.data == (b'' if method == 'HEAD' else raw[:401])
                    else:
                        assert response.status_code == 304, (url, method, headers)
                        assert response.data == b''

if app.STAND_MODE:
    with client.session_transaction() as sess:
        sess.clear()
    for url in ('/static/crm/crm.html/', '/static/crm/CRM.HTML',
                '/static/stand/../crm/crm.html', '/static/partner/index.html/'):
        assert client.get(url).status_code != 200, url
    assert client.get('/api/bitrix/active-deals').status_code == 401
    for url in ('/static/stand/vendor/inter-v20/font.css',
                '/static/stand/vendor/chartjs-4.4.7/chart.umd.min.js'):
        assert client.get(url).status_code == 200, url
app.engine.dispose()
'''
    done = subprocess.run([sys.executable, '-c', code], cwd=ROOT, env=env,
                          text=True, capture_output=True, timeout=120)
    assert done.returncode == 0, done.stdout + done.stderr
