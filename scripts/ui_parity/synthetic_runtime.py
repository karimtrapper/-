#!/usr/bin/env python3
"""Three-mode browser parity on synthetic local data, with no production dump."""
import argparse
import ctypes
import difflib
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

import ui_audit
from run import Worker, sha


BASELINE_SHA = '2c40e910a13ae866f5be85da35fa6e61c3bf5632'
HERE = Path(__file__).resolve().parent
PORTS = {'main': 18881, 'stage-prod': 18882, 'stage-stand': 18883}


def require_fence():
    if sys.platform != 'darwin':
        raise RuntimeError('synthetic browser audit requires macOS sandbox-exec')
    f = ctypes.CDLL('/usr/lib/libSystem.B.dylib').sandbox_check
    f.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
    f.restype = ctypes.c_int
    if f(os.getpid(), b'network-outbound', 0) != 1:
        raise RuntimeError('OS network fence absent')
    return 'macOS sandbox-exec'


def sig(item):
    """Exact rendered text, visible controls and shadow DOM; no screenshots in CI."""
    payload = {key: item.get(key) for key in ('url', 'text_sha256', 'labels',
                                              'controls', 'shadowRoots',
                                              'visible_rate', 'rate_source')}
    packed = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                        separators=(',', ':')).encode()
    schema = []
    for index, control in enumerate(item['controls']):
        selector = ('#' + control['id'] if control.get('id') else
                    f'[name="{control["name"]}"]' if control.get('name') else
                    f'{control["tag"].lower()}:visible:{index}')
        schema.append({'selector': selector, 'tag': control['tag'],
                       'type': control.get('type'), 'label': control.get('label'),
                       'required': control.get('required'),
                       'readOnly': control.get('readOnly'),
                       'disabled': control.get('disabled'),
                       'options': control.get('options')})
    return {'sha256': hashlib.sha256(packed).hexdigest(),
            'text_sha256': item['text_sha256'],
            'controls': len(item['controls']),
            'control_schema': schema,
            'visible_rate': item.get('visible_rate'),
            'rate_source': item.get('rate_source'),
            'shadow_roots': len(item['shadowRoots'])}


def exact_stand_deltas(private):
    names = {'referrers': ('crm-referrers', 'crm-referrers'),
             'referrer_cabinet': ('referrer', 'referrer-preview')}
    result = {}
    for case, (prod_name, stand_name) in names.items():
        prod = json.loads((private / f'stage-prod-{prod_name}.json').read_text())['text']
        stand = json.loads((private / f'stage-stand-{stand_name}.json').read_text())['text']
        result[case] = {'removed': [], 'added': []}
        for line in difflib.ndiff(prod.splitlines(), stand.splitlines()):
            if line.startswith('- '):
                value = line[2:]
                if case == 'referrer_cabinet':
                    parsed = urlsplit(value)
                    value = f'external-link:{parsed.hostname or "invalid"}'
                result[case]['removed'].append(value)
            elif line.startswith('+ '):
                result[case]['added'].append(line[2:])
    return result


def login_case(browser, mode, private):
    port = PORTS[mode]
    unauth = ui_audit.audited_context(browser)
    try:
        login = unauth.new_page()
        login.goto(f'http://127.0.0.1:{port}/login', wait_until='domcontentloaded')
        login.wait_for_timeout(400)
        return ui_audit.form_snapshot(login, 'body', private, f'{mode}-login')
    finally:
        unauth.close()


def capture(browser, workers, private):
    cases = {}
    for mode, worker in workers.items():
        port = PORTS[mode]
        login = login_case(browser, mode, private)
        forms = ui_audit.crm_forms(browser, port, worker, private, mode)
        screens = ui_audit.all_screens(browser, port, worker, private, mode,
                                       't18-synthetic-ref')
        cases[mode] = {name: sig(value) for name, value in {'login':login, **forms, **screens}.items()
                       if isinstance(value, dict) and value.get('text_sha256')}
    return cases


def capture_mutant(browser, private, mutation):
    """Exercise the same DOM/control extractor on one deliberately changed UI."""
    if mutation not in ('label', 'visibility', 'readonly', 'required', 'option',
                        'control', 'shadow', 'money'):
        raise ValueError('unknown mutation')
    target = 'calculator' if mutation == 'money' else (
        'create_exchange' if mutation in ('readonly', 'required', 'option') else 'deals')
    context = ui_audit.audited_context(browser)
    base = f'http://127.0.0.1:{PORTS["stage-prod"]}'
    try:
        login = context.request.post(base + '/api/auth/login',
            data={'username':'t12-parity','password':'t12-local-only'})
        if login.status != 200:
            raise RuntimeError('mutation fixture login failed')
        if mutation == 'money':
            def change_rate(route):
                response = route.fetch()
                data = response.json()
                data['bitazza_usdt_thb'] = 31.11
                route.fulfill(response=response, json=data)
            context.route('**/api/rates', change_rate)
        page = context.new_page()
        if target == 'calculator':
            page.goto(base + '/', wait_until='domcontentloaded')
            page.wait_for_timeout(500)
            shown = page.locator('#usdtThbRate').inner_text().strip()
            source = page.locator('#usdtThbLabel').inner_text().strip()
            if shown != '31.11 ฿' or 'Bitazza' not in source:
                raise RuntimeError(f'money mutation did not render the changed rate: {shown} / {source}')
            selector = 'body'
        else:
            page.goto(base + '/crm', wait_until='domcontentloaded')
            page.wait_for_timeout(900)
            if target == 'deals':
                page.locator('.nav-tab[data-section="deals"]').first.click()
                page.wait_for_timeout(500)
                selector = '#deals'
            else:
                page.evaluate("showSection('create')")
                page.wait_for_timeout(800)
                page.evaluate("document.getElementById('create').classList.add('active')")
                page.evaluate("() => { const e=document.getElementById('dealKindSelect'); e.value='exchange'; onDealKindChange(); }")
                page.wait_for_timeout(500)
                selector = '#createDealForm'
        if mutation == 'label':
            page.evaluate("() => { const e=document.createElement('label'); e.textContent='Synthetic changed label'; document.querySelector('#deals').append(e); }")
        elif mutation == 'visibility':
            page.evaluate("() => { const e=document.querySelector('#deals button'); if(!e) throw Error('fixture button missing'); e.style.display='none'; }")
        elif mutation in ('readonly', 'required'):
            page.evaluate("(key) => { const e=[...document.querySelectorAll('#createDealForm input')].find(x=>x.getClientRects().length && x.type!=='hidden'); if(!e) throw Error('fixture input missing'); e[key]=!e[key]; }", 'readOnly' if mutation == 'readonly' else 'required')
        elif mutation == 'option':
            page.evaluate("() => { const e=document.querySelector('#payinMethod'); if(!e) throw Error('fixture method select missing'); e.style.display='block'; e.add(new Option('Synthetic new method','synthetic-new')); }")
        elif mutation == 'control':
            page.evaluate("() => { const e=document.createElement('button'); e.textContent='Synthetic new control'; document.querySelector('#deals').append(e); }")
        elif mutation == 'shadow':
            page.evaluate("() => { const e=document.createElement('div'); e.id='synthetic-shadow-host'; document.querySelector('#deals').append(e); e.attachShadow({mode:'open'}).innerHTML='<span>Synthetic shadow text</span><button>Shadow action</button>'; }")
        item = ui_audit.form_snapshot(page, selector, private, f'mutant-{mutation}')
        return target, sig(item)
    finally:
        context.close()


def render_changes(actual, expected, emit=True):
    changes = []
    for mode in sorted(set(actual) | set(expected)):
        old, new = expected.get(mode, {}), actual.get(mode, {})
        for case in sorted(set(old) | set(new)):
            if old.get(case) != new.get(case):
                changes.append((mode, case))
                if emit:
                    print(f'NEW_UI_DIFF {mode}/{case}: rendered text/control/shadow signature changed')
    return changes


def compare(actual, registry):
    changes = render_changes(actual, registry['cases'])
    main, prod = actual['main'], actual['stage-prod']
    prod_text_diffs = sorted(case for case in main.keys() | prod.keys()
                             if main.get(case, {}).get('text_sha256') !=
                                prod.get(case, {}).get('text_sha256'))
    cross_changed = prod_text_diffs != registry['known_prod_text_diffs']
    if cross_changed:
        print(f'NEW_UI_DIFF main/stage-prod text delta set: {prod_text_diffs}')
    control_diffs = sorted(case for case in main.keys() | prod.keys()
                           if main.get(case, {}).get('control_schema') !=
                              prod.get(case, {}).get('control_schema'))
    if control_diffs:
        print(f'NEW_UI_DIFF main/stage-prod visible control schema: {control_diffs}')
    for failure in registry['known_baseline_fails']:
        print(f'BASELINE_FAIL {failure["case"]} owner={failure["owner"]}: {failure["reason"]}')
    for item in registry['open']:
        print(f'OPEN {item["case"]}: {item["reason"]}')
    print(f'RENDER_GATE cases={sum(map(len,actual.values()))} new_ui_diffs={len(changes)} '
          f'known_baseline_fails={len(registry["known_baseline_fails"])}')
    return 1 if changes or cross_changed or control_diffs else 0


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--baseline', type=Path, required=True)
    p.add_argument('--candidate', type=Path, required=True)
    p.add_argument('--registry', type=Path, default=HERE / 'synthetic_runtime_registry.json')
    p.add_argument('--capture-out', type=Path)
    p.add_argument('--mutation-test', action='store_true')
    p.add_argument('--login-only', action='store_true')
    p.add_argument('--evidence-dir', type=Path)
    args = p.parse_args()
    fence = require_fence()
    if sha(args.baseline) != BASELINE_SHA:
        p.error('main baseline must be the pinned 2c40e91 commit')
    os.umask(0o077)
    with tempfile.TemporaryDirectory(prefix='calccrm-t18-synthetic-', dir='/tmp') as tmp:
        private = Path(tmp)
        private.chmod(0o700)
        evidence = private
        if args.evidence_dir:
            if args.evidence_dir.exists():
                p.error('evidence directory already exists')
            args.evidence_dir.mkdir(mode=0o700, parents=True)
            args.evidence_dir.chmod(0o700)
            evidence = args.evidence_dir
        workers = {}
        try:
            for mode, worktree in (('main', args.baseline),
                                   ('stage-prod', args.candidate),
                                   ('stage-stand', args.candidate)):
                db = private / f'{mode}.sqlite'
                worker = Worker(worktree, f'sqlite:///{db}',
                                '1' if mode == 'stage-stand' else None,
                                private, mode, '1' * 64, synthetic=True)
                workers[mode] = worker
                auth = worker.ask(op='auth')
                if auth['status'] != 200:
                    raise RuntimeError(f'{mode} synthetic admin auth failed')
                worker.ask(op='seed_synthetic')
                worker.ask(op='serve', port=PORTS[mode])
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                try:
                    if args.login_only:
                        cases = {mode:{'login':sig(login_case(browser,mode,evidence))}
                                 for mode in workers}
                        stand_deltas = {}
                    else:
                        cases = capture(browser, workers, evidence)
                        stand_deltas = exact_stand_deltas(evidence)
                    mutants = {}
                    if args.mutation_test and not args.login_only:
                        for mutation in ('label', 'visibility', 'readonly', 'required',
                                         'option', 'control', 'shadow', 'money'):
                            mutants[mutation] = capture_mutant(browser, evidence, mutation)
                finally:
                    browser.close()
            if args.capture_out:
                if args.capture_out.exists():
                    p.error('capture output already exists')
                args.capture_out.write_text(json.dumps({'baseline_sha': BASELINE_SHA,
                    'candidate_sha': sha(args.candidate), 'cases': cases,
                    'approved_stand_diffs_candidate': stand_deltas},
                    ensure_ascii=False, indent=2) + '\n')
                args.capture_out.chmod(0o600)
                print(f'SYNTHETIC_CAPTURE_ONLY cases={sum(map(len,cases.values()))} '
                      f'fence={fence}; no acceptance status')
                return 0
            if args.login_only:
                p.error('--login-only requires --capture-out; it is evidence, not acceptance')
            registry = json.loads(args.registry.read_text())
            if registry['baseline_sha'] != BASELINE_SHA:
                p.error('registry pinned main SHA differs')
            result = compare(cases, registry)
            if stand_deltas != registry['approved_stand_diffs']:
                print('NEW_UI_DIFF approved STAND delta: exact lines changed')
                result = 1
            if args.mutation_test:
                for mutation, (target, changed) in mutants.items():
                    probe = {mode: dict(items) for mode, items in cases.items()}
                    probe['stage-prod'][target] = changed
                    gate_exit = 1 if render_changes(probe, registry['cases'], emit=False) else 0
                    if gate_exit != 1:
                        print(f'MUTATION_MISSED {mutation} {target}')
                        result = 1
                    else:
                        print(f'MUTATION_DETECTED {mutation} {target}: NEW_UI_DIFF -> exit {gate_exit}')
                if result == 0:
                    print('MUTATION_TEST PASS: 8 rendered UI mutations detected')
            return result
        finally:
            for worker in workers.values():
                worker.close()


if __name__ == '__main__':
    sys.exit(main())
