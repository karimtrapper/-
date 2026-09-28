#!/usr/bin/env python3
"""Synthetic, dump-free UI drift gate.  It never imports the application."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile

from bs4 import BeautifulSoup


HERE = Path(__file__).resolve().parent
REGISTRY = HERE / 'synthetic_registry.json'
CRM_SELECTORS = [f'section#{name}' for name in (
    'dashboard', 'deals', 'documents', 'closing', 'exchangers', 'balance',
    'incomes', 'conversions', 'reimbursements', 'transactions', 'managers',
    'verification', 'kyc', 'partners', 'referrers', 'payoutRequests', 'admins', 'create')]
CRM_SELECTORS += ['#createDealForm', '#dealModal', '.nav-tabs']
TASK_SELECTORS = ['#tabs', '#app']


def sha(data):
    return hashlib.sha256(data.encode()).hexdigest()


def inventory(crm_file, tasks_file):
    out = {}
    repo = HERE.parents[1]
    for name, path in [('crm', crm_file), ('tasks', tasks_file),
                       ('calculator', repo / 'static/calculator/index.html'),
                       ('referrer', repo / 'static/referrer/index.html'),
                       ('login', repo / 'static/auth/login.html')]:
        out[f'{name}:full-source'] = sha(path.read_text())
    for group, path, selectors in [('crm', crm_file, CRM_SELECTORS),
                                   ('tasks', tasks_file, TASK_SELECTORS)]:
        raw = path.read_text()
        soup = BeautifulSoup(raw, 'html.parser')
        for selector in selectors:
            node = soup.select_one(selector)
            out[f'{group}:{selector}'] = sha(str(node)) if node else None
        # Runtime-generated forms live in JS template strings. Keep their exact
        # source fingerprint as a separate selector, with no broad normalization.
        if group == 'tasks':
            start = raw.index('function viewEdit(){')
            end = raw.index('function editApply(', start)
            out['tasks:js:viewEdit'] = sha(raw[start:end])
            start = raw.index('function crmPayload(d){')
            end = raw.index('function crmPayloadFinal(d){', start)
            out['tasks:js:crmPayload'] = sha(raw[start:end])
            start = raw.index('function setDealKind(id,v){')
            end = raw.index('function txPoolInit()', start)
            out['tasks:js:setDealKind'] = sha(raw[start:end])
    return out


def known_failures(crm_file, tasks_file):
    raw = tasks_file.read_text()
    crm_raw = crm_file.read_text()
    view = raw[raw.index('function viewEdit(){'):raw.index('function editApply(', raw.index('function viewEdit(){'))]
    return {
        'TC-M5/F4 tasks freehold finance branch missing':
            "dealKind(d)==='mf_freehold'" not in view,
        'TC-M5/F4 tasks invoiceUsd/ippsTariff absent from full form':
            'invoiceUsd' not in view or 'ippsTariff' not in view,
        'TC-R rental subtype loss on setDealKind(mf_realty)':
            "d.kind=(v==='mf_freehold'?'Фрихолд':'Лизхолд')" in raw,
        'TC-E browser static asset egress to Google Fonts / jsDelivr':
            'fonts.googleapis.com' in crm_raw or 'cdn.jsdelivr.net' in crm_raw,
    }


def gate(crm_file, tasks_file, registry):
    actual = inventory(crm_file, tasks_file)
    expected = registry['selectors']
    changed = sorted(key for key in expected.keys() | actual.keys()
                     if expected.get(key) != actual.get(key))
    for key in changed:
        print(f'NEW_DIFF {key}')
    failures = known_failures(crm_file, tasks_file)
    for key, failed in failures.items():
        print(f'{"BASELINE_FAIL" if failed else "RESOLVED_REVIEW_REQUIRED"} {key}')
    print(f'new_diffs={len(changed)} known_baseline_failures={sum(failures.values())}')
    return 1 if changed else 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--crm', type=Path, default=HERE.parents[1] / 'static/crm/crm.html')
    parser.add_argument('--tasks', type=Path, default=HERE.parents[1] / 'static/stand/tasks.html')
    parser.add_argument('--record', action='store_true')
    parser.add_argument('--mutation-test', action='store_true')
    args = parser.parse_args()
    if args.record:
        payload = {'schema': 1, 'fixtures': ['synthetic-exchange', 'synthetic-leasehold',
                   'synthetic-freehold-0.8', 'synthetic-freehold-1.5', 'synthetic-rental'],
                   'selectors': inventory(args.crm, args.tasks)}
        REGISTRY.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + '\n')
        return 0
    registry = json.loads(REGISTRY.read_text())
    if args.mutation_test:
        with tempfile.TemporaryDirectory(prefix='t18-mutation-') as tmp:
            mutated = Path(tmp) / 'crm.html'
            raw = args.crm.read_text()
            target = '<section id="deals" class="section">'
            if target not in raw:
                raise RuntimeError('mutation target missing')
            mutated.write_text(raw.replace(target, target + '<label data-test="new-ui-diff">NEW UI DIFF</label>', 1))
            result = gate(mutated, args.tasks, registry)
            if result != 1:
                raise RuntimeError('mutation did not fail closed')
            print('MUTATION_TEST PASS: new deals DOM field -> nonzero')
            return 0
    return gate(args.crm, args.tasks, registry)


if __name__ == '__main__':
    sys.exit(main())
