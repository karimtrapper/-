#!/usr/bin/env python3
"""Headless prod-mode DOM comparison on two isolated raw-dump clones."""
import argparse
import ctypes
import difflib
import gzip
import hashlib
import json
from collections import Counter
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright
from PIL import Image, ImageChops

from run import Worker, FILTERED, digest, run_cmd, sha, tracked_clean

BLOCKED_BROWSER = []
CAPTURE_HOOK = None  # synthetic runtime mutation hook; never set in raw-dump audit

REVIEWED_SOURCE_HUNKS = {
    '8f8cf53b8c7c07468157822a1b2a6c43c703a4d1': {
        'static/crm/crm.html': 14,
        'static/referrer/index.html': 8,
    },
}


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def restore(pg, sockdir, port, dbname, dump, private):
    run_cmd([pg / 'createdb', '-h', sockdir, '-p', str(port), dbname])
    log = private / f'{dbname}-restore.log'
    with open(log, 'w', opener=lambda path, flags: os.open(path, flags, 0o600)) as err:
        proc = subprocess.Popen([str(pg / 'psql'), '-X', '-v', 'ON_ERROR_STOP=1',
                                 '-h', str(sockdir), '-p', str(port), '-d', dbname, '-q'],
                                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=err)
        with gzip.open(dump, 'rb') as source:
            try:
                for line in source:
                    if any(line.startswith(prefix) for prefix in FILTERED):
                        continue
                    proc.stdin.write(line)
            except BrokenPipeError:
                pass
        proc.stdin.close()
        if proc.wait():
            raise RuntimeError('local UI restore failed; private log removed on exit')


def block_external(route):
    if urlsplit(route.request.url).hostname in ('127.0.0.1', 'localhost', '::1'):
        route.continue_()
    else:
        parsed = urlsplit(route.request.url)
        BLOCKED_BROWSER.append((parsed.hostname or 'unknown', parsed.path))
        route.abort()


def audited_context(browser):
    context = browser.new_context(service_workers='block')
    context.route('**/*', block_external)
    # Registry N1: calculator's "Обновлено" uses the browser wall clock.
    context.add_init_script("""(() => {
      const NativeDate = Date, fixed = 1790632800000;
      class AuditDate extends NativeDate {
        constructor(...args) { super(...(args.length ? args : [fixed])); }
        static now() { return fixed; }
      }
      window.Date = AuditDate;
    })();""")
    return context


def snapshot(page, kind):
    if kind == 'crm':
        return page.evaluate("""() => ({
            nav: [...document.querySelectorAll('.nav-tab')]
                .filter(e => !e.classList.contains('stand-only') && getComputedStyle(e).display !== 'none')
                .map(e => e.dataset.section || ''),
            sections: [...document.querySelectorAll('section.section')]
                .filter(e => !e.classList.contains('stand-only')).map(e => e.id),
            active: document.querySelector('section.section.active')?.id || '',
            key: ['statsGrid','dealsTable','dealsPagination','adminsList']
                .map(id => [id, !!document.getElementById(id)]),
            referral_links: [...document.querySelectorAll('#referrers input[title="Сайт"], #referrers input[title="Telegram"], #referrers input[title="WhatsApp"]')]
                .map(e => [e.title, e.value]),
            admin_invites: document.querySelectorAll('#adminsList button[onclick^="copyAdminInvite"]').length,
            stand_visible: [...document.querySelectorAll('.stand-only')]
                .some(e => getComputedStyle(e).display !== 'none'),
        })""")
    if kind == 'referrer':
        return page.evaluate("""() => ({
            app: !!document.getElementById('app'),
            deals: !!document.getElementById('deals-list'),
            pager: !!document.getElementById('deals-pager'),
            buttons: [...document.querySelectorAll('#app button')].map(e => e.id || e.className).sort(),
            links: [...document.querySelectorAll('#app a')]
                .map(e => { try { return new URL(e.href).origin === location.origin ? 'local' : 'external'; }
                            catch (_) { return 'invalid'; } }).sort(),
            referral_links: ['url-site','url-bot','url-wa'].map(id => document.getElementById(id)?.textContent || ''),
        })""")
    return page.evaluate("""() => ({
        title: document.title,
        forms: document.querySelectorAll('form').length,
        inputs: [...document.querySelectorAll('input')].map(e => e.id || e.type),
        buttons: document.querySelectorAll('button').length,
    })""")


def browser_case(browser, port, ref_token):
    context = audited_context(browser)
    base = f'http://127.0.0.1:{port}'
    checks = {}
    try:
        login = context.request.post(base + '/api/auth/login',
            data={'username': 't12-parity', 'password': 't12-local-only'})
        checks['login_status'] = login.status
        page = context.new_page()
        page.goto(base + '/', wait_until='domcontentloaded', timeout=15000)
        checks['calculator'] = (page.evaluate('location.pathname'), snapshot(page, 'calculator'))
        page.goto(base + '/crm', wait_until='domcontentloaded', timeout=15000)
        page.wait_for_timeout(800)
        checks['dashboard'] = snapshot(page, 'crm')
        for name in ('deals', 'admins', 'referrers'):
            page.locator(f'.nav-tab[data-section="{name}"]').first.click(timeout=5000)
            page.wait_for_timeout(800)
            checks[name] = snapshot(page, 'crm')
        ref = context.new_page()
        ref.goto(base + '/ref/' + ref_token, wait_until='domcontentloaded', timeout=15000)
        ref.wait_for_timeout(1200)
        checks['referrer'] = snapshot(ref, 'referrer')
    finally:
        context.close()
    return checks


def form_snapshot(page, selector, private, name):
    """Keep full DOM text and screenshots in a private local directory only."""
    if CAPTURE_HOOK:
        CAPTURE_HOOK(page, name)
    data = page.locator(selector).evaluate("""root => {
      const visible = e => !!e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden';
      const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
      const descendants = node => [...node.querySelectorAll('*')].flatMap(e =>
        e.shadowRoot ? [e, ...descendants(e.shadowRoot)] : [e]);
      const shadowRoots = descendants(root).filter(e => e.shadowRoot).map(e => ({
        host: e.id || e.tagName.toLowerCase(), text: e.shadowRoot.textContent,
        controls: descendants(e.shadowRoot).filter(x => x.matches('input,select,textarea,button'))
          .map(x => ({tag:x.tagName, id:x.id, value:x.value, required:x.required,
                     readOnly:x.readOnly, disabled:x.disabled,
                     options:x.tagName === 'SELECT' ? [...x.options].map(y=>y.textContent) : []}))
      }));
      return {
        url: location.pathname + location.search,
        text: root.innerText,
        visible_rate: document.getElementById('usdtThbRate')?.innerText || null,
        rate_source: document.getElementById('usdtThbLabel')?.innerText || null,
        shadowRoots,
        labels: [...root.querySelectorAll('label')].filter(visible).map(e => norm(e.innerText)),
        controls: [...root.querySelectorAll('input,select,textarea,button')].filter(visible)
          .map(e => ({tag:e.tagName, id:e.id, name:e.name, type:e.type,
                      label:norm(e.closest('.form-group,.fg')?.querySelector('label')?.innerText),
                      text:norm(e.tagName === 'BUTTON' ? e.innerText : ''),
                      value:e.value, required:e.required, readOnly:e.readOnly,
                      disabled:e.disabled,
                      options:e.tagName === 'SELECT' ? [...e.options].map(x=>x.textContent) : []})),
      };
    }""")
    dest = private / f'{name}.json'
    dest.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    dest.chmod(0o600)
    shot = private / f'{name}.png'
    page.screenshot(path=str(shot), full_page=True)
    shot.chmod(0o600)
    return {'url': data['url'], 'text_sha256': hashlib.sha256(data['text'].encode()).hexdigest(),
            'labels': data['labels'], 'controls': data['controls'],
            'visible_rate': data['visible_rate'], 'rate_source': data['rate_source'],
            'shadowRoots': data['shadowRoots'], 'screenshot': shot.name,
            'screenshot_sha256': digest(shot), 'dom_file': dest.name}


def pixel_diff(private, left, right):
    a = Image.open(private / left['screenshot']).convert('RGB')
    b = Image.open(private / right['screenshot']).convert('RGB')
    if a.size != b.size:
        return f'SIZE {a.width}x{a.height} vs {b.width}x{b.height}'
    diff = ImageChops.difference(a, b)
    return sum(1 for pixel in diff.getdata() if pixel != (0, 0, 0))


def crm_forms(browser, port, work, private, label):
    base = f'http://127.0.0.1:{port}'
    context = audited_context(browser)
    forms = {}
    try:
        login = context.request.post(base + '/api/auth/login',
            data={'username':'t12-parity','password':'t12-local-only'})
        if login.status != 200:
            raise RuntimeError(f'{label} login {login.status}')
        page = context.new_page()
        page.goto(base + '/crm', wait_until='domcontentloaded', timeout=15000)
        page.wait_for_timeout(1000)
        ids = {}
        for kind, ident in work.ask(op='deal_kinds'):
            ids.setdefault(kind, ident)
        for kind in ('exchange','mf_realty','mf_freehold'):
            page.evaluate("showSection('create')")
            page.wait_for_timeout(800)
            page.evaluate("document.getElementById('create').classList.add('active')")
            page.evaluate("(kind) => { const el = document.getElementById('dealKindSelect'); el.value = kind; onDealKindChange(); }", kind)
            page.wait_for_timeout(500)
            forms['create_'+kind] = form_snapshot(page, '#createDealForm', private, f'{label}-create-{kind}')
            if kind in ids:
                page.evaluate('(id) => openDealEditor(id)', ids[kind])
                page.wait_for_load_state('networkidle', timeout=15000)
                page.wait_for_timeout(1500)
                forms['edit_'+kind] = form_snapshot(page, '#createDealForm', private, f'{label}-edit-{kind}')
        forms['create_rental'] = {'open': 'CRM has no rental deal_kind option'}
        forms['edit_rental'] = {'open': 'CRM has no rental deal_kind option'}
    finally:
        context.close()
    return forms


def task_forms(browser, port, private, work):
    base = f'http://127.0.0.1:{port}'
    context = audited_context(browser)
    forms = {}
    try:
        login = context.request.post(base + '/api/auth/login',
            data={'username':'t12-parity','password':'t12-local-only'})
        if login.status != 200:
            raise RuntimeError(f'tasks login {login.status}')
        page = context.new_page()
        page.goto(base + '/tasks', wait_until='domcontentloaded', timeout=15000)
        page.wait_for_timeout(1200)
        for kind in ('exchange','mf_realty','mf_freehold'):
            page.evaluate('startManual()')
            page.wait_for_timeout(350)
            if kind != 'exchange':
                page.evaluate('(kind) => setDealKind(S.edit, kind)', kind)
                page.wait_for_timeout(350)
            forms['create_'+kind] = form_snapshot(page, '.edit-page', private, f'stand-tasks-create-{kind}')
            page.evaluate('S.deals.find(d=>d.id===S.edit).manualNew=false; render()')
            page.wait_for_timeout(350)
            forms['edit_'+kind] = form_snapshot(page, '.edit-page', private, f'stand-tasks-edit-{kind}')
            page.evaluate('editClose()')
        page.evaluate("""() => {
          startCreate(); draftSet('kind', 'Аренда');
          draftSet('client', 'T18 Synthetic Rental'); draftSet('sum', '100000');
          createFull();
          const d = deal(S.edit);
          d.amountRub = 300000; d.incomeAmount = 300000;
          d.rates = {broker: 80, client: 3, usdtThb: 32.5};
          d.companyPct = 1; save(); render();
        }""")
        page.wait_for_timeout(500)
        forms['create_rental'] = form_snapshot(page, '.edit-page', private, 'stand-tasks-create-rental')
        rental_id = page.evaluate('S.edit')
        page.evaluate('(id) => editSave(id)', rental_id)
        page.wait_for_timeout(700)
        page.reload(wait_until='domcontentloaded')
        page.wait_for_timeout(900)
        kind_after = page.evaluate("(id) => S.deals.find(d => d.id === id)?.kind || null", rental_id)
        forms['rental_kind_after_reload'] = kind_after
        if kind_after:
            page.evaluate('(id) => editOpen(id)', rental_id)
            page.wait_for_timeout(350)
            forms['edit_rental'] = form_snapshot(page, '.edit-page', private, 'stand-tasks-edit-rental')
            payload = page.evaluate('(id) => crmPayloadFinal(deal(id))', rental_id)
            dest = private / 'stand-tasks-rental-payload.json'
            dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
            dest.chmod(0o600)
            forms['rental_payload_kind'] = payload.get('deal_kind')
            forms['rental_payload_field_names'] = sorted(payload)
            posted = work.ask(op='request', path='/api/deals', method='POST', json=payload)
            forms['rental_post_status'] = posted['status']
            post_file = private / 'stand-tasks-rental-post-response.json'
            post_file.write_text(json.dumps(posted, ensure_ascii=False, indent=2))
            post_file.chmod(0o600)
            if posted['status'] == 201:
                crm_id = ((posted.get('body') or {}).get('deal') or {}).get('id')
                if crm_id:
                    context.request.post(base + '/api/auth/login',
                        data={'username':'t12-parity','password':'t12-local-only'})
                    page.goto(base + '/crm', wait_until='domcontentloaded', timeout=15000)
                    page.wait_for_timeout(700)
                    page.evaluate('(id) => openDealEditor(id)', crm_id)
                    page.wait_for_load_state('networkidle', timeout=15000)
                    forms['crm_rental'] = form_snapshot(page, '#createDealForm', private,
                                                       'stand-crm-edit-rental-fixture')
        else:
            forms['edit_rental'] = {'open': 'synthetic rental did not survive reload'}
    finally:
        context.close()
    return forms


CRM_SECTIONS = ('dashboard','deals','documents','closing','exchangers','balance',
                'incomes','conversions','reimbursements','transactions','managers',
                'verification','kyc','partners','referrers','payoutRequests','admins')


def all_screens(browser, port, work, private, label, ref_token):
    base = f'http://127.0.0.1:{port}'
    context = audited_context(browser)
    out = {}
    try:
        login = context.request.post(base + '/api/auth/login',
            data={'username':'t12-parity','password':'t12-local-only'})
        if login.status != 200:
            raise RuntimeError(f'{label} screen login {login.status}')
        page = context.new_page()
        page.goto(base + '/', wait_until='domcontentloaded', timeout=15000)
        page.wait_for_timeout(400)
        out['calculator'] = form_snapshot(page, 'body', private, f'{label}-calculator')
        page.goto(base + '/crm', wait_until='domcontentloaded', timeout=15000)
        page.wait_for_timeout(1000)
        for section in CRM_SECTIONS:
            page.locator(f'.nav-tab[data-section="{section}"]').first.click(timeout=7000)
            page.wait_for_timeout(500)
            active = page.locator('section.section.active')
            if active.count() != 1 or active.get_attribute('id') != section:
                out[section] = {'open': 'section did not become active'}
                continue
            out[section] = form_snapshot(page, f'#{section}', private, f'{label}-crm-{section}')
        ids = {}
        for kind, ident in work.ask(op='deal_kinds'):
            ids.setdefault(kind, ident)
        for kind, ident in ids.items():
            page.evaluate("showSection('deals')")
            page.wait_for_timeout(350)
            page.evaluate('(id) => showDealDetails(id)', ident)
            page.wait_for_timeout(900)
            if page.locator('#dealModal.active').count():
                out['card_'+kind] = form_snapshot(page, '#dealModalContent', private, f'{label}-card-{kind}')
            else:
                out['card_'+kind] = {'open': 'deal modal did not become active'}
            page.evaluate('closeModal()')
        ref = context.new_page()
        if label == 'stage-stand':
            ref.goto(base + '/ref/' + ref_token, wait_until='domcontentloaded', timeout=15000)
            ref.wait_for_timeout(700)
            out['referrer_direct_stand'] = form_snapshot(ref, 'body', private,
                                                         f'{label}-referrer-direct')
            refs = work.ask(op='ids')['referrers']
            fixture = next((ident for ident, token in refs if token == ref_token), None)
            if fixture is None:
                out['referrer_cabinet'] = {'open': 'no referrer fixture'}
            else:
                ref.goto(base + '/api/stand/ref-preview/' + str(fixture),
                         wait_until='domcontentloaded', timeout=15000)
                ref.wait_for_timeout(900)
                out['referrer_cabinet'] = form_snapshot(ref, 'body', private,
                                                        f'{label}-referrer-preview')
        else:
            ref.goto(base + '/ref/' + ref_token, wait_until='domcontentloaded', timeout=15000)
            ref.wait_for_timeout(700)
            out['referrer_cabinet'] = form_snapshot(ref, 'body', private, f'{label}-referrer')
    finally:
        context.close()
    return out


def main():
    if sys.platform != 'darwin':
        raise RuntimeError('runtime audit requires a verified macOS network sandbox')
    check = ctypes.CDLL('/usr/lib/libSystem.B.dylib').sandbox_check
    check.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
    check.restype = ctypes.c_int
    if check(os.getpid(), b'network-outbound', 0) != 1:
        raise RuntimeError('OS network fence absent; refusing import/restore')
    p = argparse.ArgumentParser()
    p.add_argument('--baseline', type=Path, required=True)
    p.add_argument('--candidate', type=Path, required=True)
    p.add_argument('--dump', type=Path, required=True)
    p.add_argument('--report', type=Path, required=True)
    p.add_argument('--pg-bin', type=Path, default=Path('/opt/homebrew/opt/postgresql@17/bin'))
    p.add_argument('--app-ports', nargs=2, type=int, default=[18881, 18882])
    p.add_argument('--pg-port', type=int, default=18880)
    p.add_argument('--stand-port', type=int, default=18883)
    p.add_argument('--evidence-dir', type=Path, required=True)
    p.add_argument('--forms-only', action='store_true')
    p.add_argument('--screens-only', action='store_true')
    args = p.parse_args()
    os.umask(0o077)
    if args.report.exists():
        p.error('report already exists')
    if args.evidence_dir.exists():
        p.error('evidence dir already exists')
    args.evidence_dir.mkdir(mode=0o700, parents=True)
    args.evidence_dir.chmod(0o700)
    dump_sha = digest(args.dump)
    expected_sha = args.dump.with_suffix(args.dump.suffix + '.sha256')
    if expected_sha.is_file() and expected_sha.read_text().split()[0] != dump_sha:
        p.error('dump SHA256 mismatch')
    before = {name: (sha(path), tracked_clean(path)) for name, path in
              (('baseline', args.baseline), ('candidate', args.candidate))}
    if not all(clean for _, clean in before.values()):
        p.error('tracked input trees must be clean')
    workers = []
    with tempfile.TemporaryDirectory(prefix='calccrm-t18-ui-', dir='/tmp') as tmp:
        private = Path(tmp)
        private.chmod(0o700)
        sockdir = private / 'socket'; sockdir.mkdir(mode=0o700)
        datadir = private / 'pg'; datadir.mkdir(mode=0o700)
        log = private / 'pg.log'
        pg_env = {k: os.environ[k] for k in ('PATH', 'HOME', 'USER', 'TMPDIR') if k in os.environ}
        pg_env['LC_ALL'] = 'C'
        with open(log, 'w', opener=lambda path, flags: os.open(path, flags, 0o600)) as f:
            run_cmd([args.pg_bin / 'initdb', '-D', datadir, '--no-sync', '--auth=trust', '--encoding=UTF8', '--locale=C'],
                    stderr=f, env=pg_env)
        port = args.pg_port
        started = False
        try:
            run_cmd([args.pg_bin / 'pg_ctl', '-D', datadir, '-l', log,
                     '-o', f'-k {sockdir} -p {port} -h ""', 'start'], env=pg_env)
            started = True
            for name in ('baseline', 'candidate', 'stand'):
                restore(args.pg_bin, sockdir, port, name, args.dump, private)
            def url(name):
                return f'postgresql://{os.environ["USER"]}@/{name}?host={sockdir}&port={port}'
            audit_key = secrets.token_hex(32)
            a = Worker(args.baseline, url('baseline'), None, private, 'ui-main', audit_key); workers.append(a)
            b = Worker(args.candidate, url('candidate'), None, private, 'ui-candidate', audit_key); workers.append(b)
            c = Worker(args.candidate, url('stand'), '1', private, 'ui-stand', audit_key); workers.append(c)
            for worker in workers:
                if worker.ask(op='auth')['status'] != 200:
                    raise RuntimeError('synthetic UI admin login failed')
            ref_token = a.ask(op='ids')['public_ref_token']
            if not ref_token:
                raise RuntimeError('no link-mode referrer in dump')
            pa, pb = args.app_ports
            pc = args.stand_port
            a.ask(op='serve', port=pa); b.ask(op='serve', port=pb); c.ask(op='serve', port=pc)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                try:
                    left, right = browser_case(browser, pa, ref_token), browser_case(browser, pb, ref_token)
                    if args.screens_only:
                        main_forms = prod_forms = stand_forms = tasks_forms = {}
                    else:
                        main_forms = crm_forms(browser, pa, a, args.evidence_dir, 'main')
                        prod_forms = crm_forms(browser, pb, b, args.evidence_dir, 'stage-prod')
                        stand_forms = crm_forms(browser, pc, c, args.evidence_dir, 'stage-stand-crm')
                    if args.forms_only:
                        main_screens = prod_screens = stand_screens = {}
                    else:
                        main_screens = all_screens(browser, pa, a, args.evidence_dir, 'main', ref_token)
                        prod_screens = all_screens(browser, pb, b, args.evidence_dir, 'stage-prod', ref_token)
                        stand_screens = all_screens(browser, pc, c, args.evidence_dir, 'stage-stand', ref_token)
                    if not args.screens_only:
                        # Task form coverage creates a rental fixture; capture equal snapshots first.
                        tasks_forms = task_forms(browser, pc, args.evidence_dir, c)
                finally:
                    browser.close()
            checks = {name: left[name] == right[name] for name in left}
            stand_hidden = not right['dashboard']['stand_visible'] and not right['deals']['stand_visible'] and not right['admins']['stand_visible']
            static = {}
            for path in ('static/calculator/index.html', 'static/auth/login.html'):
                static[path] = (args.baseline / path).read_bytes() == (args.candidate / path).read_bytes()
            source_hunks = {}
            for path in ('static/crm/crm.html', 'static/referrer/index.html'):
                old = (args.baseline / path).read_text().splitlines()
                new = (args.candidate / path).read_text().splitlines()
                source_hunks[path] = sum(line.startswith('@@') for line in difflib.unified_diff(old, new))
            source_review = source_hunks == REVIEWED_SOURCE_HUNKS.get(before['candidate'][0])
            after = {name: (sha(path), tracked_clean(path)) for name, path in
                     (('baseline', args.baseline), ('candidate', args.candidate))}
            integrity = before == after
            report = ['# T18 — browser UI parity audit', '',
                      f'- Baseline SHA: `{before["baseline"][0]}`; candidate SHA: `{before["candidate"][0]}`.',
                      f'- Dump SHA256: `{dump_sha}`; PostgreSQL 17; STAND_MODE unset.',
                      '- Chromium: localhost only; all external browser requests aborted. Synthetic admin, raw dump clones.',
                      '- Smoke snapshots use key block names, visibility and control counts; private form/screen JSON files contain full DOM text and controls.',
                      '', '| Экран/условие | Результат |', '|---|---|']
            report.extend(f'| `{name}` DOM | {"PASS" if ok else "FAIL"} |' for name, ok in checks.items())
            report.extend(['', '## Form text/field baseline (actual browser actions)', '',
                           'Full DOM text and screenshot are private 0600 files; this report contains only hashes and field-label differences.',
                           '', '| Form fixture | main vs stage prod text | stage STAND CRM vs tasks field labels | CRM-only labels | Tasks-only labels |',
                           '|---|---|---|---|---|'])
            for form in ('create_exchange','edit_exchange','create_mf_realty','edit_mf_realty',
                         'create_mf_freehold','edit_mf_freehold','create_rental','edit_rental'):
                m, pform, sform, tform = (collection.get(form, {}) for collection in
                                           (main_forms, prod_forms, stand_forms, tasks_forms))
                if form.endswith('_rental'):
                    sform = stand_forms.get(form.replace('_rental', '_mf_realty'), {})
                parity = ('OPEN' if not m.get('text_sha256') or not pform.get('text_sha256') else
                          'SAME' if m['text_sha256'] == pform['text_sha256'] else 'DIFF')
                crm_labels, task_labels = set(sform.get('labels', [])), set(tform.get('labels', []))
                task_status = ('OPEN' if not sform.get('text_sha256') or not tform.get('text_sha256') else
                               'SAME' if crm_labels == task_labels else 'DIFF')
                def safe_labels(values):
                    return ', '.join(sorted(x.replace('|','/') for x in values)[:18]) or '—'
                report.append(f'| `{form}` | {parity} | {task_status} | '
                              f'{safe_labels(crm_labels-task_labels)} | {safe_labels(task_labels-crm_labels)} |')
            report.extend(['', f'Rental subtype after task save/reload: `{tasks_forms.get("rental_kind_after_reload") or "OPEN"}`; '
                           f'CRM payload deal_kind: `{tasks_forms.get("rental_payload_kind") or "OPEN"}`. '
                           f'Local CRM POST status: `{tasks_forms.get("rental_post_status", "OPEN")}`. '
                           'Rental form comparison uses the existing MF Realty CRM path; workflow/document fields remain distinct.'])
            report.extend(['', '## Full screen inventory', '',
                           'Each captured screen has a private full DOM text JSON and screenshot. SAME means exact innerText hash on this captured state; DIFF needs review.',
                           '', '| Screen | main vs stage prod | stage STAND | evidence |',
                           '|---|---|---|---|'])
            for screen in ('calculator', *CRM_SECTIONS, 'card_exchange', 'card_mf_realty',
                           'card_mf_freehold', 'referrer_cabinet'):
                m = main_screens.get(screen, {})
                pform = prod_screens.get(screen, {})
                sform = stand_screens.get(screen, {})
                parity = ('OPEN' if not m.get('text_sha256') or not pform.get('text_sha256') else
                          'SAME' if m['text_sha256'] == pform['text_sha256'] else 'DIFF')
                stand_status = ('OPEN' if not pform.get('text_sha256') or not sform.get('text_sha256') else
                                'SAME' if pform['text_sha256'] == sform['text_sha256'] else 'DIFF')
                report.append(f'| `{screen}` | {parity} | {stand_status} | '
                              f'{m.get("dom_file", "—")}, {pform.get("dom_file", "—")}, {sform.get("dom_file", "—")} |')
            report.extend(['', '## Blocked browser asset attempts', '',
                           'The OS sandbox and browser route blocked every external request before HTTP; attempts are not zero.'])
            for (host, path), count in sorted(Counter(BLOCKED_BROWSER).items()):
                report.append(f'- `{host}{path}`: {count} attempted requests, 0 sent')
            report.extend(['', '## Exact screenshot pixel comparison (main vs stage prod)', '',
                           'No pixel normalization. DOM text may match while pixels differ.',
                           '', '| Case | Different pixels |', '|---|---:|'])
            pixel_diffs = {}
            for left_cases, right_cases in ((main_forms, prod_forms), (main_screens, prod_screens)):
                for name in sorted(left_cases.keys() & right_cases.keys()):
                    left, right = left_cases[name], right_cases[name]
                    if not isinstance(left, dict) or not isinstance(right, dict):
                        continue
                    if left.get('screenshot') and right.get('screenshot'):
                        pixel_diffs[name] = pixel_diff(args.evidence_dir, left, right)
                        report.append(f'| `{name}` | {pixel_diffs[name]} |')
            report.extend(['', '## Evidence registry', '',
                           'DOM text is SHA256 only here. Local evidence files are 0600 inside a 0700 directory.',
                           '', '| Mode | Case | Action / path | Fixture | DOM SHA256 | Local files |',
                           '|---|---|---|---|---|---|'])
            collections = [
                ('main', main_forms, 'CRM create/openDealEditor'),
                ('stage-prod', prod_forms, 'CRM create/openDealEditor'),
                ('stage-STAND-CRM', stand_forms, 'CRM create/openDealEditor'),
                ('stage-STAND-tasks', tasks_forms, 'tasks startManual/setDealKind/editSave'),
                ('main', main_screens, 'browser nav/click'),
                ('stage-prod', prod_screens, 'browser nav/click'),
                ('stage-STAND', stand_screens, 'browser nav/click/admin preview'),
            ]
            for mode, cases, action in collections:
                for name, item in sorted(cases.items()):
                    if not isinstance(item, dict) or not item.get('text_sha256'):
                        continue
                    url = item['url']
                    if url.startswith('/ref/'):
                        url = '/ref/<synthetic-token>'
                    elif url.startswith('/api/stand/ref-preview/'):
                        url = '/api/stand/ref-preview/<id>'
                    exact_action = action
                    if name.startswith('card_'):
                        exact_action = 'showSection(deals), showDealDetails(fixture id)'
                    elif name.startswith('create_') and 'tasks' not in mode:
                        exact_action = 'showSection(create), select dealKindSelect'
                    elif name.startswith('edit_') and 'tasks' not in mode:
                        exact_action = 'openDealEditor(fixture id), await networkidle'
                    elif name.startswith('create_') and 'tasks' in mode:
                        exact_action = 'startManual/setDealKind; rental: startCreate/createFull'
                    elif name.startswith('edit_') and 'tasks' in mode:
                        exact_action = 'editOpen; rental: editSave/reload/editOpen'
                    elif name in CRM_SECTIONS:
                        exact_action = f'click nav[data-section={name}]'
                    elif name == 'referrer_cabinet' and mode == 'stage-STAND':
                        exact_action = 'GET admin ref-preview(fixture id) redirect'
                    elif name == 'referrer_cabinet':
                        exact_action = 'GET ref(fixture token)'
                    elif name == 'calculator':
                        exact_action = 'GET /'
                    report.append(f'| `{mode}` | `{name}` | {exact_action} `{url}` | '
                                  f'`{name}` | `{item["text_sha256"]}` | '
                                  f'`{item["dom_file"]}`, `{item["screenshot"]}` '
                                  f'(PNG SHA `{item["screenshot_sha256"]}`) |')
            main_prod_diffs = [name for name in set(main_forms) | set(main_screens)
                               if (main_forms.get(name) or main_screens.get(name) or {}).get('text_sha256')
                               != (prod_forms.get(name) or prod_screens.get(name) or {}).get('text_sha256')]
            baseline_failures = ['TC-M5/F4 task freehold form', 'TC-R task rental subtype reselection']
            if BLOCKED_BROWSER:
                baseline_failures.append('TC-E external browser asset attempts')
            baseline_failures += [f'PROD_DIFF:{name}' for name in sorted(main_prod_diffs)]
            baseline_failures += [f'PIXEL_DIFF:{name}' for name, count in sorted(pixel_diffs.items()) if count]
            report.extend(['', '## Gate result', '',
                           f'Known or unexplained FAIL: {", ".join(baseline_failures)}.',
                           'No overall PASS while these FAIL remain. New source hunks require independent review.'])
            report.extend(f'| `{path}` byte-identical | {"PASS" if ok else "FAIL"} |' for path, ok in static.items())
            report.extend((f'| Stand-only controls hidden | {"PASS" if stand_hidden else "FAIL"} |',
                           f'| Source diff reviewed ({source_hunks}) | {"PASS" if source_review else "OPEN"} |',
                           f'| Tracked trees clean and SHA stable | {"PASS" if integrity else "FAIL"} |',
                           '', 'Source review applies only to the exact candidate SHA in REVIEWED_SOURCE_HUNKS; any other SHA remains OPEN.',
                           '', 'Повтор: `python3 scripts/ui_parity/safe_run.py --baseline /tmp/calccrm-t12-main --candidate /tmp/calccrm-t18 --dump <raw-dump.sql.gz> --report <new-file> --evidence-dir <private-dir>`'))
            with args.report.open('x', encoding='utf-8') as f:
                f.write('\n'.join(report) + '\n')
            print(f'UI: {sum(checks.values())}/{len(checks)} DOM, stand hidden {stand_hidden}, integrity {integrity}; report {args.report}')
            return 0 if (all(checks.values()) and all(static.values()) and stand_hidden and
                         integrity and source_review and not baseline_failures) else 1
        finally:
            for worker in workers:
                worker.close()
            if started:
                subprocess.run([str(args.pg_bin / 'pg_ctl'), '-D', str(datadir), '-m', 'immediate', 'stop'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=pg_env)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        import traceback
        traceback.print_exc()
        print(f'UI audit failed: {type(exc).__name__}', file=sys.stderr)
        sys.exit(1)
