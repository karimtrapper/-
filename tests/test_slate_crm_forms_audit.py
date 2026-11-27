"""Real working CRM form interaction audit, against local synthetic records."""
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

import app as A
from tests.helpers.slate_contrast import TEXT_CONTRAST_FAILURES
from tests.test_browser_crm import choose, chromium, crm_server  # noqa: F401
from tests.test_ipps_realty import _accounts

REPORT_DIR = os.environ.get('CALCCRM_FORM_AUDIT_DIR')
PRODUCTS = [
    ('exchange', 'Обычная (обмен)', None),
    ('custom', 'Кастомная — нестандартные валюты', None),
    ('mf', 'Недвижимость лизхолд', 'MF Corporation'),
    ('ipps', 'Недвижимость лизхолд', 'ИППС'),
    ('personal', 'Недвижимость лизхолд', 'Личный счёт'),
    ('freehold', 'Недвижимость фрихолд', None),
    ('rental', 'Аренда', None),
    ('auto', 'Оплата авто', None),
]


def audit(page, key):
    form = page.locator('#createDealForm')
    issues = form.evaluate('''form => Array.from(form.querySelectorAll('div, button, input, summary'))
      .filter(el => el.clientWidth > 10 && el.scrollWidth > el.clientWidth + 4 &&
        !el.matches('input,select,textarea') && getComputedStyle(el).textOverflow !== 'ellipsis')
      .map(el => [el.id || el.className || el.tagName, el.clientWidth, el.scrollWidth,
        el.innerText.trim().slice(0,70)]).slice(0,20)''')
    contrast = form.evaluate('''root => (''' + TEXT_CONTRAST_FAILURES + ''')(
      [...root.querySelectorAll('div, p, span, strong, b, h3, h4, small, label, button, summary')]
        .filter(el => el.getClientRects().length && [...el.childNodes].some(node => node.nodeType === 3 && node.textContent.trim()))
      )''')
    screen = page.locator('#customDealSubmit:visible, #createDealForm button[type="submit"]:visible').first
    screen.click(trial=True)
    if REPORT_DIR and key.split('-')[0] in {'exchange', 'custom', 'mf', 'ipps', 'freehold'}:
        page.evaluate('window.scrollTo(0, 0)')
        page.screenshot(path=str(Path(REPORT_DIR) / (key + '.png')), full_page=True)
    return {'overflow': issues, 'contrast': contrast, 'cta_visible': True}


@pytest.mark.browser
@pytest.mark.parametrize('width', [390,1440])
def test_working_forms_audit(chromium, crm_server, monkeypatch, width):
    monkeypatch.setitem(A.app.config, 'SESSION_COOKIE_SECURE', False)
    monkeypatch.setattr(A, 'TASKS_ENABLED', True)
    monkeypatch.setattr(A, 'sync_referrer_reward_to_gsheet', lambda *args, **kw: None)
    with A.get_session() as db:
        _accounts(db)
        db.add(A.Referrer(name='QA Agent',code='AUDIT',token='audit-fixture',default_percent=10,comp_model='revshare'))
        db.commit()
    base, cookie=crm_server
    with chromium.new_context(viewport={'width':width,'height':900}) as context:
        context.add_cookies([{'name':'session','value':cookie,'url':base}])
        context.route('**/*',lambda route: route.continue_()
                      if urlsplit(route.request.url).hostname == '127.0.0.1' else route.abort())
        page=context.new_page()
        page.set_default_timeout(4500)
        errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto(base+'/crm?section=deals')
        page.locator('#deals .nav-create-btn').click()
        expect(page.locator('#create')).to_be_visible()
        choose(page,'#dealSourceChannel','Telegram')
        page.locator('#dealChatManualToggle').click()
        page.locator('#dealChatManualInput').fill('Синтетическая переписка')
        page.locator('#clientSearchInput').fill('QA Audit Client')
        results={}
        for name,label,route in PRODUCTS:
            choose(page,'#dealProductSelect',label)
            if route:
                choose(page,'#leaseholdPayoutRoute',route)
            if name == 'custom':
                page.locator('#customPayinAmount').fill('900')
                choose(page,'#customPayoutCurrency','USDT')
                page.locator('#customPayoutAmount').fill('830')
                page.locator('button[onclick="customAgentsAdd()"]').click()
                choose(page,'#agentsBlockCustom select[data-agent-directory]','QA Agent')
            else:
                choose(page, '#payinMethod', 'Крипта напрямую')
                page.locator('[name="payin_amount_usdt"]').fill('1100')
                if name in ['exchange','rental']: page.locator('#payoutAmountThb').fill('30000')
                if name=='exchange':
                    page.locator('button[onclick="stdAgentsAdd()"]').click()
                    choose(page,'#agentsBlockStd select[data-agent-directory]','QA Agent')
                if name=='mf':
                    page.locator('#mfInvoiceThb').fill('32000')
                    page.locator('#mfBuyRate').fill('34.5')
                    page.locator('#mfSpread').fill('2')
                    page.locator('#mfPercent').fill('1')
                    expect(page.locator('#mfSummary .deal-form-preview')).to_be_visible()
                if name=='ipps': page.locator('#ippsPayoutThb').fill('34000')
                if name in ('freehold', 'auto'):
                    page.locator('#fhInvoiceUsd').fill('970')
                    expect(page.locator('#fhSummary .deal-form-preview')).to_be_visible()
                if name in ['mf','freehold','auto']:
                    page.locator('#mfPayoutPickerBtn').click()
                    page.locator('#mfPayoutManual summary').click()
            for mode in ['dark','light']:
                if page.locator('html').get_attribute('data-mode') != mode:
                    page.locator('[data-slate-mode]').click()
                key=f'{name}-{mode}-{width}'
                results[key]=audit(page,key)
            if name in ['mf','freehold','auto'] and page.locator('#mfPayoutPicker').is_visible():
                page.locator('#mfPayoutPickerBtn').click()
            if name in ['mf','freehold','auto'] and page.locator('#mfPayoutManual').get_attribute('open') is not None:
                page.locator('#mfPayoutManual summary').click()
        if REPORT_DIR:
            (Path(REPORT_DIR) / f'matrix-{width}.json').write_text(json.dumps(results, ensure_ascii=False, indent=2))
        assert not errors, errors
        assert not {key: report for key, report in results.items()
                    if report['contrast'] or report['overflow'] or not report['cta_visible']}
