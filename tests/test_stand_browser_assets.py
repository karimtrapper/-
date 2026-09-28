"""Resource registry and stage/prod response checks using synthetic local data."""

from html.parser import HTMLParser
import hashlib
from pathlib import Path
import os
import re
import subprocess
import sys

import pytest

from stand_browser import page_kind, transform_html, STAND_CSP, PUBLIC_VENDOR_PATHS


ROOT = Path(__file__).resolve().parents[1]
PAGES = {
    'calculator': 'static/calculator/index.html',
    'crm': 'static/crm/crm.html',
    'referrer': 'static/referrer/index.html',
    'partner': 'static/partner/index.html',
    'kyc': 'static/kyc/index.html',
    'login': 'static/auth/login.html',
    'tasks': 'static/stand/tasks.html',
    'walkthrough': 'static/stand/walkthrough/leasehold-rub.html',
}


class Resources(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'link' and a.get('rel') in ('stylesheet', 'preconnect', 'preload'):
            self.urls.append(a.get('href'))
        if tag in ('script', 'img', 'iframe') and a.get('src'):
            self.urls.append(a['src'])


def resources(html):
    parser = Resources()
    parser.feed(html)
    return parser.urls


@pytest.mark.parametrize('kind,source', PAGES.items())
def test_registered_pages_use_only_local_static_resources(kind, source):
    original = (ROOT / source).read_text()
    result = transform_html(kind, original)
    urls = resources(result)
    assert not [url for url in urls if url and url.startswith(('http:', 'https:', '//'))]
    for url in urls:
        if url and url.startswith('/static/stand/vendor/'):
            assert (ROOT / url.removeprefix('/')).is_file(), url
    assert 'fonts.googleapis.com' not in result
    assert 'fonts.gstatic.com' not in result
    assert 'cdn.jsdelivr.net' not in result
    if kind == 'crm':
        assert 'chartjs-4.4.7/chart.umd.min.js' in result
    if kind == 'login':
        assert 'if (cfg.bot_id && !(window.Telegram && window.Telegram.Login))' in result


@pytest.mark.parametrize('family', ['inter-v20', 'plus-jakarta-sans-v12'])
def test_local_font_css_references_existing_bytes(family):
    directory = ROOT / 'static/stand/vendor' / family
    css = (directory / 'font.css').read_text()
    assert '@font-face' in css
    assert 'font-display: swap' in css
    names = re.findall(r'url\(([^)]+)\)', css)
    assert names
    assert all((directory / name).is_file() for name in names)
    assert not any(name.startswith(('http:', 'https:', '//')) for name in names)
    assert (directory / 'OFL.txt').is_file()


def test_stage_csp_blocks_external_resources_and_keeps_previews():
    for directive in ("connect-src 'self'", "font-src 'self' data:",
                      "img-src 'self' data: blob:", "frame-src 'self' blob: data:"):
        assert directive in STAND_CSP
    assert 'https:' not in STAND_CSP and 'http:' not in STAND_CSP


def test_vendor_manifest_pins_every_served_asset():
    directory = ROOT / 'static/stand/vendor'
    checks = {}
    for line in (directory / 'SHA256SUMS').read_text().splitlines():
        digest, name = line.split(maxsplit=1)
        checks[name] = digest
    actual = {str(path.relative_to(directory)) for path in directory.rglob('*')
              if path.is_file() and path.name not in ('README.md', 'SHA256SUMS')}
    assert set(checks) == actual
    for name, digest in checks.items():
        assert hashlib.sha256((directory / name).read_bytes()).hexdigest() == digest
    assert PUBLIC_VENDOR_PATHS == {'/static/stand/vendor/' + name for name in checks
                                   if Path(name).suffix in ('.css', '.js', '.woff2')}


def test_changed_font_source_fails_with_explicit_registry_error():
    source = (ROOT / PAGES['partner']).read_text()
    changed = re.sub(r'<link href="https://fonts\.googleapis\.com/[^\n]+\n?', '', source, count=1)
    assert changed != source
    with pytest.raises(ValueError, match='partner: expected one registered font link, got 0'):
        transform_html('partner', changed)


@pytest.mark.parametrize('mode', ['0', '1'])
def test_app_response_matches_source_only_outside_stage(tmp_path, mode):
    # A fresh interpreter is required: STAND_MODE is fixed at app import.
    env = {'PATH': os.environ.get('PATH', ''), 'STAND_MODE': mode,
           'DATABASE_URL': 'sqlite:///' + str(tmp_path / f'{mode}.db'),
           'SECRET_KEY': 'synthetic-browser-test', 'STAND_PASSWORD': 'synthetic-pass',
           'LOCAL_NO_AUTH': '0', 'REESTR_SYNC_ENABLED': '0',
           'PAYMENT_POLL_ENABLED': '0', 'PAYIN_ADDR_BACKFILL': '0',
           'KYC_RETENTION_ENABLED': '0', 'TRONSCAN_WARM_ENABLED': '0',
           'STAND_TRANSFER_POLL_ENABLED': '0'}
    code = '''
import app
from pathlib import Path
from stand_browser import page_kind, transform_html
client = app.app.test_client()
if not app.STAND_MODE:
    db = app.SessionLocal()
    db.add(app.AdminUser(username='synthetic', display_name='Synthetic',
                         password_hash=app.AdminUser.hash_password('synthetic-pass')))
    db.commit()
    db.close()
paths = {'/login': 'static/auth/login.html', '/': 'static/calculator/index.html',
         '/crm': 'static/crm/crm.html',
         '/kyc/': 'static/kyc/index.html', '/partner/synthetic': 'static/partner/index.html',
         '/ref/synthetic': 'static/referrer/index.html',
         '/auth/login.html': 'static/auth/login.html',
         '/static/auth/login.html': 'static/auth/login.html',
         '/calculator/index.html': 'static/calculator/index.html',
         '/static/calculator/index.html': 'static/calculator/index.html',
         '/crm/crm.html': 'static/crm/crm.html',
         '/static/crm/crm.html': 'static/crm/crm.html',
         '/kyc/index.html': 'static/kyc/index.html',
         '/static/kyc/index.html': 'static/kyc/index.html',
         '/partner/synthetic/index.html': 'static/partner/index.html',
         '/static/partner/index.html': 'static/partner/index.html',
         '/static/referrer/index.html': 'static/referrer/index.html'}
if app.STAND_MODE:
    paths['/tasks'] = 'static/stand/tasks.html'
    paths['/tasks/tasks.html'] = 'static/stand/tasks.html'
    paths['/static/stand/tasks.html'] = 'static/stand/tasks.html'
    paths['/tasks/walkthrough/leasehold-rub.html'] = 'static/stand/walkthrough/leasehold-rub.html'
    paths['/static/stand/walkthrough/leasehold-rub.html'] = 'static/stand/walkthrough/leasehold-rub.html'
    for path in ('/static/stand/vendor/../../crm/crm.html',
                 '/static/stand/vendor/%2e%2e/%2e%2e/crm/crm.html',
                 '/static/stand/vendor/..%2f..%2fcrm%2fcrm.html',
                 '/static/stand/vendor/../browser-status.js',
                 '/static/crm/crm.html', '/static/partner/index.html',
                 '/static/stand/vendor/inter-v20/OFL.txt'):
        assert client.get(path).status_code != 200, path
    assert client.get('/api/bitrix/active-deals').status_code == 401
    for path in ('/static/stand/vendor/inter-v20/font.css',
                 '/static/stand/vendor/chartjs-4.4.7/chart.umd.min.js',
                 '/static/stand/vendor/inter-v20/UcC73FwrK3iLTeHuS_nVMrMxCp50SjIa0ZL7W0Q5n-wU.woff2'):
        assert client.get(path).status_code == 200, path
for path, source in paths.items():
    if path == '/':
        with client.session_transaction() as sess: sess['user_id'] = 1
    response = client.get(path)
    assert response.status_code == 200, (path, response.status_code)
    raw = Path(source).read_bytes()
    expected = transform_html(page_kind(path), raw.decode()).encode() if app.STAND_MODE else raw
    assert response.data == expected, path
    assert ('Content-Security-Policy' in response.headers) == app.STAND_MODE
    if app.STAND_MODE:
        assert response.headers['Cache-Control'] == 'no-store'
        assert 'ETag' not in response.headers and 'Last-Modified' not in response.headers
    if path == '/login' and app.STAND_MODE:
        asset = client.get('/static/stand/vendor/inter-v20/font.css')
        assert asset.status_code == 200
if app.STAND_MODE:
    conditional = client.get('/crm', headers={'If-Modified-Since': 'Wed, 21 Oct 2037 07:28:00 GMT'})
    assert conditional.status_code == 200
    assert conditional.data == transform_html('crm', Path('static/crm/crm.html').read_text()).encode()
    for path in ('/static/partner/index.html', '/static/partner/index.html?v=1'):
        for headers in ({'If-Modified-Since': 'Wed, 21 Oct 2037 07:28:00 GMT'},
                        {'If-None-Match': '*'}):
            response = client.get(path, headers=headers)
            assert response.status_code == 200 and 'Content-Security-Policy' in response.headers
            assert response.data == transform_html('partner', Path('static/partner/index.html').read_text()).encode()
        response = client.head(path)
        assert response.status_code == 200 and 'Content-Security-Policy' in response.headers
        assert response.data == b''
    for path in ('/crm/', '/tasks/', '/partner/synthetic/', '/login/'):
        assert client.get(path).status_code in (302, 404)
    for path in ('/api/bitrix/active-deals', '/api/webhook/config'):
        response = client.get(path)
        assert response.status_code == 403 and response.json['error'] == 'stand_blocked'
else:
    response = client.get('/static/partner/index.html',
                          headers={'If-Modified-Since': 'Wed, 21 Oct 2037 07:28:00 GMT'})
    assert response.status_code == 304 and 'Content-Security-Policy' not in response.headers
    response = client.head('/static/partner/index.html')
    assert response.status_code == 200 and response.data == b''
    assert 'Content-Security-Policy' not in response.headers
app.engine.dispose()
'''
    done = subprocess.run([sys.executable, '-c', code], cwd=ROOT, env=env,
                          text=True, capture_output=True, timeout=90)
    assert done.returncode == 0, done.stdout + done.stderr
