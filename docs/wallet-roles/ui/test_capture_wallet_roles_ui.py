"""UI/дизайн-QA: кошельки по ролям (s18w, s22, s23, s24, CRM-выплата) на 375 и 1280.

Живой локальный Flask (STAND_MODE), синтетическая SQLite, по пользователю на
каждую роль, у каждой роли своя подписанная cookie: роль и «Беру» определяет
сервер, а не переключатель в интерфейсе. Любой запрос не на 127.0.0.1
отклоняется на уровне браузера и записывается как нарушение.

Запуск ТОЛЬКО через ограждённый раннер (сеть закрыта внутри):
  <py311> scripts/run_fenced_pytest.py -p tests.conftest --browser \
      --chromium-executable "<chromium>" \
      docs/wallet-roles/ui/test_capture_wallet_roles_ui.py -q -s
Скриншоты и метрики: docs/wallet-roles/ui/shots/ (или WALLET_UI_OUT).

Сценарии, зависящие от полей реализации (раздел SCENARIOS), правятся после
готового SHA; механика (серверы, контексты, метрики) от них не зависит.
"""
import hashlib
import json
import os
import subprocess
import time
import re
import secrets
import threading
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

import app as m
import stand_egress

pytestmark = pytest.mark.browser

OUT = Path(os.environ.get('WALLET_UI_OUT') or Path(__file__).parent / 'shots')
WIDTHS = {'375': (375, 812), '1280': (1280, 800)}
ROLES = {'operator': 'Операционист', 'findir': 'Фин. директор', 'teodor': 'Теодор',
         'manager': 'Клиентский менеджер', 'admin': 'Админ'}

REALTY = 'TDuDeRiwrLLN3hnnA57G5yM6ibg58A6wZk'     # Груша Недвижимость
EXCHANGE = 'TA6S3RBEY57jq8fXEVVsU6H9JZ18inenG4'   # Груша Обменник
LEGACY = 'TKkeEVf2zySaWTLyX2qPwvi6kcdHRuPxkJ'     # старый мультисиг
SIGNERS = {'operator': 'TAXgSzqBJzcstEkTBu4FJvEBH8SdxfV3QC',
           'findir': 'TDsLTB3uHKhTcB3hWRaKByg3pLtrMAHcgd',
           'teodor': 'TUzvaUjzRN5XLqDqbWB2VRKWQRtukXFYrN'}
# Только браузерные статические ресурсы; к деньгам отношения не имеют. На стенде
# stand_browser.transform_html подменяет их локальными (Inter v20, Chart.js 4.4.7),
# поэтому любое обращение сюда — признак того, что оверлей стенда не сработал.
OPTIONAL_STATIC_HOSTS = {'fonts.googleapis.com', 'fonts.gstatic.com', 'cdn.jsdelivr.net'}
IPPS = 'TQgQCBXkewuW4RoieDKFP9Ko2SopBh8jso'
SENDER_KNOWN = 'TXFqZbXCqoq5QVxRpp9EGLSzkeLMz8iG5D'

# Скрипт метрик: выполняется в странице, ничего не меняет.
METRICS_JS = r'''(expected) => {
  const vis = n => n.getClientRects().length > 0 && getComputedStyle(n).visibility !== 'hidden' &&
    !(n.closest('details:not([open])') && !n.closest('summary'));   // содержимое закрытого details не видно
  const own = n => [...n.childNodes].some(c => c.nodeType === 3 && c.textContent.trim());
  const sizes = {}, weights = {}, families = new Set();
  for (const n of document.querySelectorAll('body *')) {
    if (!vis(n) || !own(n)) continue;
    const cs = getComputedStyle(n);
    sizes[cs.fontSize] = (sizes[cs.fontSize] || 0) + 1;
    weights[cs.fontWeight] = (weights[cs.fontWeight] || 0) + 1;
    families.add(cs.fontFamily.split(',')[0].replace(/["']/g, '').trim());
  }
  const SCALE = new Set(['36px', '24px', '22px', '16px', '14px', '12px']);
  const scaleViolations = [];
  for (const n of document.querySelectorAll('body *')) {
    if (!vis(n) || !own(n)) continue;
    const cs = getComputedStyle(n);
    if (!SCALE.has(cs.fontSize) || !['400', '600', '700'].includes(cs.fontWeight)) {
      scaleViolations.push({node: n.tagName.toLowerCase() + (n.id ? '#' + n.id : '') +
        (typeof n.className === 'string' && n.className ? '.' + n.className.trim().split(/\s+/).slice(0, 2).join('.') : ''),
        fontSize: cs.fontSize, fontWeight: cs.fontWeight, text: n.textContent.trim().slice(0, 40)});
      if (scaleViolations.length >= 12) break;
    }
  }
  const text = document.body.innerText;
  const addrRe = /\bT[1-9A-HJ-NP-Za-km-z]{33}\b/g;
  const fullAddresses = [...new Set(text.match(addrRe) || [])];
  const addrNodes = [...document.querySelectorAll('.addr, .tx-hash, [data-address]')].filter(vis).map(n => {
    const cs = getComputedStyle(n), r = n.getBoundingClientRect();
    const lh = parseFloat(cs.lineHeight) || parseFloat(cs.fontSize) * 1.4;
    const t = n.textContent.trim();
    return {text: t, title: n.getAttribute('title') || '', mono: /mono|menlo|courier/i.test(cs.fontFamily),
      lines: Math.round(r.height / lh), whiteSpace: cs.whiteSpace, wrapAnywhere: cs.overflowWrap,
      shortForm: /^.{8}(…|\.\.\.).{8}(\s*[▾▸▼])?$/.test(t), full: t.length >= 34, cutAtEdge: n.tagName !== 'SUMMARY' && n.scrollWidth > n.clientWidth + 1};
  });
  const isBlue = c => { const m = c.match(/rgba?\((\d+), (\d+), (\d+)(?:, ([\d.]+))?/); if (!m || (m[4] !== undefined && +m[4] === 0)) return false;
    const r = +m[1] / 255, g = +m[2] / 255, b = +m[3] / 255, mx = Math.max(r, g, b), mn = Math.min(r, g, b), l = (mx + mn) / 2;
    if (mx === mn) return false;
    const d = mx - mn, s = d / (1 - Math.abs(2 * l - 1));
    let h = mx === r ? ((g - b) / d) % 6 : mx === g ? (b - r) / d + 2 : (r - g) / d + 4; h = (h * 60 + 360) % 360;
    return h >= 190 && h <= 260 && s > 0.6; };   // slate/navy палитры имеют насыщенность ~0.3-0.47
  const bluePlaques = [...document.querySelectorAll('body *')].filter(n => vis(n) && n.getBoundingClientRect().height > 20 &&
    n.id !== 'toast' && (isBlue(getComputedStyle(n).backgroundColor) ||
      (parseFloat(getComputedStyle(n).borderTopWidth) > 0 && getComputedStyle(n).borderTopStyle !== 'none' && isBlue(getComputedStyle(n).borderTopColor))))
    .slice(0, 6).map(n => ({node: n.tagName.toLowerCase() + (typeof n.className === 'string' && n.className ? '.' + n.className.trim().split(/\s+/)[0] : ''),
      bg: getComputedStyle(n).backgroundColor, border: getComputedStyle(n).borderTopColor, text: n.textContent.trim().slice(0, 50)}));
  const blueText = [...document.querySelectorAll('body *')].filter(n => vis(n) && [...n.childNodes].some(c => c.nodeType === 3 && c.textContent.trim()) &&
    isBlue(getComputedStyle(n).color)).slice(0, 6).map(n => ({node: n.tagName.toLowerCase() + (typeof n.className === 'string' && n.className ? '.' + n.className.trim().split(/\s+/)[0] : ''),
      color: getComputedStyle(n).color, text: n.textContent.trim().slice(0, 40)}));
  const coral = [...document.querySelectorAll('button, a, input[type=submit]')].filter(n => vis(n) &&
    getComputedStyle(n).backgroundColor === 'rgb(194, 65, 12)').map(n => n.textContent.trim().slice(0, 60));
  const small = [...document.querySelectorAll('button, a[href], input:not([type=hidden]), select, textarea, summary')]
    .filter(n => vis(n) && n.getBoundingClientRect().height > 0 && n.getBoundingClientRect().height < 44 &&
      !n.closest('.btn-sm,[class*=sm]')).slice(0, 12).map(n => ({tag: n.tagName,
      text: (n.textContent || n.value || '').trim().slice(0, 40), h: Math.round(n.getBoundingClientRect().height)}));
  const smallSm = [...document.querySelectorAll('button.btn-sm')].filter(vis).length;
  const emoji = (text.match(/\p{Extended_Pictographic}/gu) || []).slice(0, 8);
  const moneyPrefixBad = (text.match(/(?:₽|USDT)[ \u00a0]?\d[\d \u00a0]*/g) || []).slice(0, 8);
  const dollarSuffixBad = (text.match(/\d[\d \u00a0,.]*[ \u00a0]?\$(?!\d)/g) || []).slice(0, 8);
  const addrClipped = addrNodes.filter(x => x.cutAtEdge).map(x => x.text);
  const addrUnshortened = addrNodes.filter(x => x.full && !x.shortForm).map(x => x.text);
  const mfstr = fullAddresses.filter(a => a.startsWith('TR68'));
  const signerAddrs = {};
  for (const [role, a] of Object.entries(__SIGNERS__)) signerAddrs[role] = fullAddresses.includes(a) ||
    addrNodes.some(x => x.title === a || x.text === a || (x.shortForm && x.text.startsWith(a.slice(0, 8)) && x.text.endsWith(a.slice(-8))));
  const toastEl = document.getElementById('toast');
  const toast = toastEl && toastEl.classList.contains('on') ? {text: toastEl.textContent, error: toastEl.classList.contains('error')} : null;
  const root = document.documentElement;
  // Что именно шире ожидаемой ширины экрана (закреплённые элементы не считаем): источник переполнения.
  const overflowOffenders = [...document.querySelectorAll('body *')].filter(n => {
    if (!vis(n)) return false;
    const cs = getComputedStyle(n);
    if (cs.position === 'fixed') return false;
    // внутри намеренно прокручиваемой полосы (overflow-x:auto|scroll) широкие элементы — не переполнение страницы
    for (let p = n.parentElement; p && p !== document.body; p = p.parentElement) {
      const ox = getComputedStyle(p).overflowX;
      if (ox === 'auto' || ox === 'scroll' || ox === 'hidden') return false;
    }
    const r = n.getBoundingClientRect();
    return r.right > expected + 1 || r.width > expected + 1;
  }).sort((a, b) => b.getBoundingClientRect().right - a.getBoundingClientRect().right).slice(0, 12).map(n => {
    const r = n.getBoundingClientRect(), chain = [];
    for (let p = n, i = 0; p && i < 4; p = p.parentElement, i++)
      chain.push(p.tagName.toLowerCase() + (p.id ? '#' + p.id : '') + (p.className && typeof p.className === 'string' ? '.' + p.className.trim().split(/\s+/).slice(0, 2).join('.') : ''));
    return {path: chain.join(' < '), left: Math.round(r.left), right: Math.round(r.right), width: Math.round(r.width),
      minWidth: getComputedStyle(n).minWidth, whiteSpace: getComputedStyle(n).whiteSpace,
      snippet: n.outerHTML.slice(0, 160)};
  });
  const fontFaces = [...document.fonts].map(f => f.family.replace(/["']/g, '') + ':' + f.status);
  const styleSheets = [...document.styleSheets].map(x => x.href || 'inline').filter(h => h !== 'inline');
  return {blueText, bluePlaques, scaleViolations, toast, fontFaces, interLoaded: document.fonts.check('16px Inter'), stylesheets: styleSheets,
    url: location.pathname + location.search, innerWidth, scrollWidth: root.scrollWidth,
    bodyScrollWidth: document.body.scrollWidth, hScroll: root.scrollWidth > innerWidth + 1 || innerWidth > expected + 1 || root.scrollWidth > expected + 1,
    expectedWidth: expected, layoutViewportExpanded: innerWidth > expected + 1,
    visualViewportWidth: window.visualViewport ? Math.round(window.visualViewport.width) : null,
    docClientWidth: root.clientWidth, overflowOffenders,
    fontSizes: sizes, fontWeights: weights, families: [...families],
    addrNodes, addrClipped, addrUnshortened, fullAddresses, mfstrAddresses: mfstr, signerAddrsVisible: signerAddrs,
    coralButtons: coral, smallTargets: small, smallSmCount: smallSm, emoji, moneyPrefixBad, dollarSuffixBad,
    title: (document.querySelector('.card-title, h1, h2') || {}).textContent || ''};
}'''.replace('__SIGNERS__', json.dumps(SIGNERS))

FOCUS_JS = '''() => { const n = document.activeElement; if (!n || n === document.body) return null;
  const cs = getComputedStyle(n); const r = n.getBoundingClientRect();
  return {tag: n.tagName, text: (n.textContent || n.value || '').trim().slice(0, 40),
    outlineWidth: cs.outlineWidth, outlineStyle: cs.outlineStyle, outlineColor: cs.outlineColor,
    outlineOffset: cs.outlineOffset, boxShadow: cs.boxShadow, visible: r.width > 0}; }'''


FOCUS_TARGETS_JS = '''() => {
  const vis = n => n && n.getClientRects().length > 0 && getComputedStyle(n).visibility !== 'hidden' && !n.disabled &&
    !(n.closest('details:not([open])') && !n.closest('summary'));   // закрытый details и disabled не фокусируются
  const kinds = {primary: 'button.btn-primary', outline: 'button.btn-outline, button.btn-secondary',
    input: 'input:not([type=hidden]):not([type=checkbox]):not([type=radio]):not([type=file])',
    select: 'select', textarea: 'textarea', checkbox: 'input[type=checkbox]', summary: 'summary'};
  const out = {};
  for (const [kind, sel] of Object.entries(kinds)) {
    const n = [...document.querySelectorAll(sel)].find(vis);
    if (!n) { out[kind] = null; continue; }
    n.focus();
    const cs = getComputedStyle(n);
    out[kind] = {focused: document.activeElement === n, text: (n.textContent || n.value || n.id || '').trim().slice(0, 40), id: n.id || null,
      focusVisible: n.matches(':focus-visible'), outlineWidth: cs.outlineWidth, outlineStyle: cs.outlineStyle,
      outlineColor: cs.outlineColor, outlineOffset: cs.outlineOffset, boxShadow: cs.boxShadow.slice(0, 60)};
    n.blur();
  }
  return out;
}'''

HARNESS_VERSION = 'wallet-roles-ui r8 (2026-10-19): r7 + full untruncated state diffs (normalised path summary), combined final assertion (nothing masked), regex endsWith fix'

SEMANTIC_PATH = re.compile(
    r'^deals/\d+/(transfer|payout|prepay|transferClaim|transferConfirmation|transferOwnerApproval|recipientWarnings|'
    r'payinHashes|pay|step|walletId|payinCustom|ippsPayoutOrder|outgoingReview|serverTransferComplete|outgoingOrderAt|postConv)(/|$)|'
    r'^convs/\d+/(recipientWarnings|txs|walletId|status|sources)(/|$)')


def _canon(value):
    """Каноническое сравнение: 5000.0 == 5000, порядок ключей не важен."""
    if isinstance(value, dict):
        return {k: _canon(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_canon(v) for v in value]
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _state_view(data):
    data = data or {}
    view = {k: v for k, v in data.items() if k not in ('deals', 'convs', 'notes')}
    view['deals'] = {str(d.get('id')): d for d in data.get('deals') or []}
    view['convs'] = {str(c.get('id')): c for c in data.get('convs') or []}
    return _canon(view)


def diff_paths(before, after, path='', out=None, limit=60):
    out = [] if out is None else out
    if len(out) >= limit:
        return out
    if isinstance(before, dict) and isinstance(after, dict):
        for key in sorted(set(before) | set(after)):
            diff_paths(before.get(key), after.get(key), f'{path}/{key}' if path else str(key), out, limit)
    elif before != after:
        out.append(path)
    return out


def summarize_paths(paths):
    """Счётчик путей без id сделки/пачки: deals/1601/agents -> deals/*/agents."""
    counts = {}
    for path in paths:
        key = re.sub(r'^(deals|convs)/\d+/', r'\1/*/', path)
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:60])


def state_delta(before_data, after_data):
    """Пути, которыми различаются два снимка доски, и подмножество «финансово/подписное» (смысловое)."""
    paths = diff_paths(_state_view(before_data), _state_view(after_data), limit=2000)
    return paths, [p for p in paths if SEMANTIC_PATH.match(p)]


class Capture:
    def __init__(self, browser, base, cookies):
        self.browser, self.base, self.cookies = browser, base, cookies
        self.contexts, self.external, self.optional_static = {}, [], []
        self.console, self.log, self.shots = [], [], []
        self.opens, self.last_open, self.put_log, self.http_errors = [], {}, [], []
        self.phase, self.failed, self.crm_facts = 'setup', [], []

    def page(self, role, width):
        key = (role, width)
        if key not in self.contexts:
            w, h = WIDTHS[width]
            ctx = self.browser.new_context(
                viewport={'width': w, 'height': h}, device_scale_factor=2 if width == '375' else 1,
                is_mobile=width == '375', has_touch=width == '375', locale='ru-RU', timezone_id='Europe/Moscow')
            ctx.grant_permissions(['clipboard-read', 'clipboard-write'], origin=self.base)
            ctx.add_cookies([{'name': 'session', 'value': self.cookies[role], 'url': self.base,
                              'httpOnly': True, 'sameSite': 'Lax'}])

            def gate(route):
                host = urlsplit(route.request.url).hostname
                if host == '127.0.0.1':
                    route.continue_()
                else:
                    # Необязательные статические ресурсы (шрифты, Chart.js) отделены от
                    # прочих внешних обращений: последние считаются нарушением.
                    bucket = self.optional_static if host in OPTIONAL_STATIC_HOSTS else self.external
                    bucket.append(route.request.url)
                    route.abort()
            ctx.route('**/*', gate)

            def put_probe(route):
                # Диагностика автосохранения клиента: тело, статус и ответ сервера.
                if route.request.method != 'PUT':
                    route.fallback()
                    return
                reply = route.fetch()
                try:
                    body = reply.json()
                except Exception:
                    body = {}
                sent = route.request.post_data or ''
                try:
                    cur = ctx.request.get(f'{self.base}/api/stand/state').json()
                    sent_data = json.loads(sent).get('data') if sent else None
                    dpaths, dsem = state_delta(cur.get('data'), sent_data)   # что клиент пытался изменить
                except Exception as exc:
                    dpaths, dsem = [f'diff-error:{exc!r}'], []
                self.put_log.append({'diffPaths': dpaths[:25], 'diffCount': len(dpaths), 'diffSummary': summarize_paths(dpaths),
                                     'diffDealIds': sorted({p.split('/')[1] for p in dpaths if p.startswith('deals/')})[:30],
                                     'topLevelDiff': [p for p in dpaths if not p.startswith(('deals/', 'convs/'))][:20],
                                     'semanticPaths': dsem[:25], 'semanticSummary': summarize_paths(dsem), 'phase': self.phase, 'role': key[0], 'width': key[1], 'status': reply.status,
                                     'error': body.get('error'), 'detail': body.get('detail'),
                                     'sentVersion': (json.loads(sent).get('version') if sent else None),
                                     'sent': sent})
                route.fulfill(response=reply)
            ctx.route('**/api/stand/state', put_probe)
            page = ctx.new_page()
            page.on('pageerror', lambda e, k=key: self.console.append((k, 'pageerror', str(e))))
            page.on('response', lambda r, k=key: self.http_errors.append((k, r.status, urlsplit(r.url).path))
                    if r.status >= 400 else None)
            page.on('console', lambda msg, k=key: self.console.append((k, 'console.error', msg.text))
                    if msg.type == 'error' else None)
            self.contexts[key] = page
        return self.contexts[key]

    def state_version(self, page):
        reply = page.request.get(f'{self.base}/api/stand/state')
        return reply.json().get('version')

    def open_deal(self, role, width, deal_id):
        """Открывает карточку по ссылке. Просмотр не должен менять stand_state.version."""
        page = self.page(role, width)
        snap_before = page.request.get(f'{self.base}/api/stand/state').json()
        before = snap_before.get('version')
        page.goto(f'{self.base}/tasks?deal={deal_id}')
        page.wait_for_selector('#app .card, #app .task, #app .deal-screen', timeout=15000)
        page.wait_for_timeout(3200)               # дольше периода опроса/автосохранения (2,5 с)
        snap_after = page.request.get(f'{self.base}/api/stand/state').json()
        after = snap_after.get('version')
        paths, semantic = state_delta(snap_before.get('data'), snap_after.get('data'))
        self.last_open = {'deal': deal_id, 'role': role, 'width': width,
                          'versionBefore': before, 'versionAfter': after, 'viewMutated': before != after,
                          'deltaPaths': paths[:20], 'deltaSummary': summarize_paths(paths), 'deltaDealIds': sorted({p.split('/')[1] for p in paths if p.startswith('deals/')})[:30],
                          'topLevelDelta': [p for p in paths if not p.startswith(('deals/', 'convs/'))][:20], 'semanticPaths': semantic[:20],
                          'semanticChange': bool(semantic), 'noopVersionBump': before != after and not paths}
        if semantic and self.phase == 'capture':
            self.failed.append(f'просмотр {role}/{width} сделки {deal_id} изменил смысловые поля: {semantic[:4]}')
        self.opens.append(self.last_open)
        return page

    def try_click(self, page, patterns, note, required=True, expect_disabled=False):
        """Нажимает первую найденную кнопку; нет кнопки — фиксируем это, а не падаем."""
        for pattern in patterns:
            loc = page.get_by_role('button', name=re.compile(pattern, re.I))
            if loc.count() and loc.first.is_visible():
                if expect_disabled:
                    ok = loc.first.is_disabled()
                    self.log.append({'note': note, 'button': pattern, 'disabled': ok, 'ok': ok})
                    if not ok:
                        self.failed.append(note + ' (кнопка должна быть недоступна)')
                    return ok
                try:
                    loc.first.click(timeout=8000)
                except Exception as exc:  # перекрытие/блокировка клика фиксируем, не зависаем на 30 с
                    self.log.append({'note': note, 'clicked': pattern, 'ok': False, 'error': str(exc)[:300]})
                    if required:
                        self.failed.append(note)
                    return False
                page.wait_for_timeout(700)
                self.log.append({'note': note, 'clicked': pattern, 'ok': True})
                return True
        self.log.append({'note': note, 'clicked': None, 'ok': False, 'tried': patterns})
        if required:
            self.failed.append(note)
        return False

    def shot(self, name, page, role, width, focus_tabs=0):
        OUT.mkdir(parents=True, exist_ok=True)
        stem = f'{name}__{role}__{width}'
        metrics = page.evaluate(METRICS_JS, WIDTHS[width][0])
        if focus_tabs:
            # Режим клавиатуры включаем настоящим Tab, затем фокусируем по одному элементу каждого вида:
            # :focus-visible у кнопок, полей, списков, чекбоксов, summary (а не только у ссылок меню).
            page.keyboard.press('Tab')
            metrics['focusTargets'] = page.evaluate(FOCUS_TARGETS_JS)
            for kind, probe in metrics['focusTargets'].items():
                # Элемент, который реально получил фокус, обязан иметь кольцо 2px сплошное коралловое, отступ 2px.
                if probe and probe['focused'] and not (probe['focusVisible'] and probe['outlineWidth'] == '2px' and
                        probe['outlineStyle'] == 'solid' and probe['outlineColor'] == 'rgb(194, 65, 12)' and
                        probe['outlineOffset'] == '2px'):
                    self.failed.append(f'фокус {name}/{role}/{width}: {kind} без кольца 2px coral offset 2px ({probe})')
            metrics['focusProbe'] = []
            page.evaluate('() => window.scrollTo(0, 0)')
            for _ in range(focus_tabs):
                page.keyboard.press('Tab')
                probe = page.evaluate(FOCUS_JS)
                if probe:
                    metrics['focusProbe'].append(probe)
            page.evaluate('() => document.activeElement && document.activeElement.blur()')
        metrics['open'] = dict(self.last_open)
        w, h = WIDTHS[width]
        # Первый экран в исходном viewport (для 375 это настоящий телефонный размер, без растяжки):
        # именно он — дизайн-доказательство «кнопка на первом экране» и закреплённой панели.
        page.evaluate('() => window.scrollTo(0, 0)')
        page.screenshot(path=str(OUT / f'{stem}__first-screen.png'))
        # Высокий кадр целиком: viewport ВРЕМЕННО растягивается, закреплённое меню не попадает в
        # середину страницы. Это отмечено в метриках; метрики сняты ДО растяжки на исходном viewport.
        full = page.evaluate('() => document.documentElement.scrollHeight')
        tall = min(full + 40, 9000)
        page.set_viewport_size({'width': w, 'height': tall})
        page.wait_for_timeout(250)
        page.screenshot(path=str(OUT / f'{stem}.png'))
        page.set_viewport_size({'width': w, 'height': h})
        metrics['capture'] = {'metricsViewport': [w, h], 'tallImageViewport': [w, tall],
                              'tallImageIsResizedViewport': True,
                              'firstScreenFile': f'{stem}__first-screen.png'}
        (OUT / f'{stem}.json').write_text(json.dumps(metrics, ensure_ascii=False, indent=1))
        self.shots.append({'name': name, 'role': role, 'width': width, 'file': f'{stem}.png',
                           'hScroll': metrics['hScroll'], 'innerWidth': metrics['innerWidth']})
        return metrics




    def api_post(self, page, path, payload, note):
        """Прямой запрос от имени аутентифицированной роли; ответ сервера — в run.json."""
        if page.url.startswith('about:'):
            page.goto(f'{self.base}/tasks')
            page.wait_for_timeout(500)
        result = page.evaluate('''async ([path, payload]) => {
            const v = (await (await fetch('/api/stand/state')).json()).version;
            const r = await fetch(path, {method: 'POST', headers: {'Content-Type': 'application/json'},
              body: JSON.stringify(Object.assign({version: v}, payload))});
            let body = null; try { body = await r.json(); } catch (e) {}
            if (body && body.data) body.data = '[state omitted]';
            return {status: r.status, body};
        }''', [path, payload])
        self.log.append({'note': note, 'api': path, 'payload': payload, 'response': result})
        return result


# ---------------------------------------------------------------- окружение

@pytest.fixture
def app_env(monkeypatch):
    monkeypatch.setattr(m, 'STAND_MODE', True)
    monkeypatch.setenv('STAND_ALLOW_DEMO', '0')
    monkeypatch.setattr(m, '_stand_deliver_notes', lambda: [])
    monkeypatch.setattr(m, '_tronscan_fetch_incoming', lambda *a, **k: ([], [], []))
    monkeypatch.setattr(m.stand_notify, 'notify_profile', lambda: 'disabled')
    monkeypatch.setattr(m.stand_notify, 'mode', lambda: 'all')

    async def rates():
        return {'usdt_thb': 34.5, 'rub_usdt': 92.5}
    monkeypatch.setattr(m.ExchangeRateProvider, 'get_all_rates', rates)
    monkeypatch.setattr(m, '_bitazza_calc_quote', lambda *a, **k: None)
    for name in ('sync_deals_to_gsheet', '_send_deal_telegram', 'send_deal_completed_webhook',
                 'notify_agents_new_deal'):
        if hasattr(m, name):
            monkeypatch.setattr(m, name, lambda *a, **k: None)
    # Нижний транспорт исходящих чтений подменён пустыми ответами (как в tests/): DNS и сокеты
    # не открываются вовсе, журнал ограждения остаётся чистым без «ожидаемых» исключений.
    egress_calls = []

    def fake_read_get(op, params=None, *a, **k):
        egress_calls.append(op)
        return 200, {'token_transfers': [], 'total': 0, 'data': []}, None

    def fake_blocked(*a, **k):
        egress_calls.append('blocked-channel')
        raise ConnectionError('synthetic transport unavailable')
    monkeypatch.setattr(stand_egress, 'read_get', fake_read_get)
    for name in ('docparse_post', 'lk_call', 'tg_call'):
        if hasattr(stand_egress, name):
            monkeypatch.setattr(stand_egress, name, fake_blocked)
    def fake_verify_transfer(ref, network, sender, receiver, amount, *a, **k):
        # Граница проверки сети: сеть не открывается, Success не выдаётся — только «ждём».
        egress_calls.append(f'verify_transfer:{str(ref)[:10]}')
        return {'status': 'pending', 'checkError': 'Синтетика QA: перевод в сети не подтверждён'}
    monkeypatch.setattr(m, 'verify_transfer', fake_verify_transfer)
    import stand_transfers
    monkeypatch.setattr(stand_transfers, 'verify_transfer', fake_verify_transfer)
    m.EGRESS_CALLS = egress_calls
    m.app.config.update(TESTING=True, PROPAGATE_EXCEPTIONS=False)
    m.Session.remove()
    m.Base.metadata.create_all(m.engine)
    m._stand_migrate()
    m._stand_seed_wallets()   # на стенде вызывается при старте; в тестовой БД — явно
    db = m.get_session()
    cookies, ids = {}, {}
    try:
        serializer = m.app.session_interface.get_signing_serializer(m.app)
        for role, title in ROLES.items():
            user = db.query(m.AdminUser).filter_by(username=f'ui_{role}').first()
            if not user:
                user = m.AdminUser(username=f'ui_{role}', display_name=f'{title} (QA)',
                                   role=role, password_hash='unused')
                db.add(user)
                db.flush()
            ids[role] = user.id
            cookies[role] = serializer.dumps({'user_id': user.id})
        db.commit()
    finally:
        db.close()
    server = make_server('127.0.0.1', 0, m.app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{server.server_port}', cookies, ids
    server.shutdown()
    thread.join(5)
    server.server_close()


def registry_wallets():
    """Кошельки реестра как их отдаёт /api/wallets; id — строкой, как зеркало в задачнике."""
    db = m.get_session()
    try:
        found = {}
        for address in (REALTY, EXCHANGE, LEGACY):
            row = db.query(m.Wallet).filter_by(address=address).first()
            assert row is not None, f'в реестре нет {address}: миграция не засеяла кошелёк'
            found[address] = row.to_dict()
        return found
    finally:
        db.close()


def mirror(wallet):
    """Зеркало кошелька в общем состоянии стенда (сервер сверяет его с реестром)."""
    return {'id': str(wallet['id']), 'name': wallet['label'], 'owner': wallet['owner'] or 'компания',
            'addr': wallet['address'], 'multisig': wallet['is_multisig'],
            'role': 'findir' if wallet['is_multisig'] else 'teodor',
            **{k: wallet[k] for k in ('purpose', 'limit_usd', 'initiator_roles', 'confirmer_roles',
                                      'owner_can_alone', 'signer_addresses', 'not_for_new_deals')}}


def seed_state(state):
    db = m.get_session()
    try:
        row = m._stand_row(db)
        row.data, row.version, row.generation = json.dumps(state), 1, secrets.token_hex(16)
        db.commit()
    finally:
        db.close()


def synthetic_deal(deal_id, step, wallet_id, exchange=False, amount=5000.0):
    """Синтетическая сделка с отправкой USDT с кошелька реестра."""
    amount = int(amount) if float(amount).is_integer() else amount   # как после JSON-круга браузера
    return {'id': deal_id, 'code': f'СД-{deal_id}', 'client': f'Синтетика {deal_id}', 'step': step,
            'type': 'Обмен валюты' if exchange else 'Оплата недвижимости',
            'kind': None if exchange else 'Фрихолд', 'payType': 'По реквизитам',
            'invoiceUsd': amount, 'ippsTariff': 'bank', 'amountRub': amount * 90, 'incomeAmount': amount * 90,
            'amountUsdt': amount if exchange else None, 'cnvId': None, 'conv': [],
            'rates': {'broker': '80'}, 'payinParts': [], 'payinHashes': [], 'pay': {}, 'payout': {},
            'transfer': {'addr': IPPS, 'amount': amount, 'net': 'TRC-20', 'to': 'IPPS', 'sends': []},
            'walletId': str(wallet_id), 'log': [], 'docs': {}, 'reqTask': 'done', 'demoTransfers': False,
            'payToConfirm': {'at': 'confirmed'}, 'postConv': 'ipps_swift',
            'ippsPayoutOrder': {'amount': amount, 'address': IPPS, 'network': 'TRC-20',
                                'confirmedAt': '2026-10-19T10:00:00Z'},
            'payTo': {'dev': 'Developer', 'bank': 'Bank', 'swift': 'BANKXX', 'acc': 'SYNTHETIC',
                      'purpose': 'Invoice', 'amount': amount}}


def build_state(reg):
    realty, exchange, legacy = (reg[REALTY], reg[EXCHANGE], reg[LEGACY])
    wr, we, wl = realty['id'], exchange['id'], legacy['id']
    deals = {
        # s18w: ожидаемый кошелёк по типу сделки, предупреждение о неверном кошельке
        1601: synthetic_deal(1601, 's18w', wr),
        1602: synthetic_deal(1602, 's18w', we, exchange=True),
        1609: synthetic_deal(1609, 's18w', wr),
        1619: synthetic_deal(1619, 's18w', wr),
        # s22 и s23: правило кошелька, легаси-кошелёк, свыше лимита
        1603: synthetic_deal(1603, 's22', wr),
        1604: synthetic_deal(1604, 's22', we, exchange=True),
        1605: synthetic_deal(1605, 's23', wl),
        1610: synthetic_deal(1610, 's23', we, exchange=True, amount=15000.0),
        1611: synthetic_deal(1611, 's23', wr),
        1612: synthetic_deal(1612, 's23', we, exchange=True),
    }
    # мутирующие сценарии: по сделке на ширину (+10 для 1280)
    for base, wallet, ex in ((1620, wr, False), (1621, we, True), (1622, wr, False)):
        for shift in (0, 10):
            deals[base + shift] = synthetic_deal(base + shift, 's23', wallet, exchange=ex)
    for did in (1601, 1602, 1609, 1619):
        deals[did]['cnvId'] = did
    convs = [{'id': did, 'name': f'ЦНВ-{did}', 'broker': 'Брокер QA', 'at': '19.10, 10:00', 'rate': '80',
              'walletId': str(deals[did]['walletId']), 'status': 'sent', 'txs': [],
              'sent': deals[did]['amountRub'], 'held': 0, 'rubTotal': deals[did]['amountRub'],
              'sources': [{'dealId': did, 'rub': deals[did]['amountRub'], 'usdt': deals[did]['invoiceUsd']}]}
             for did in (1601, 1602, 1609, 1619)]
    # деньги пришли на чужой кошелёк реестра: устойчивое предупреждение без зачисления
    for conv in convs[2:]:
        conv['recipientWarnings'] = [{'hash': 'a' * 64, 'expected': realty['address'],
            'actual': exchange['address'], 'acknowledgedById': None, 'acknowledgedAt': None}]
    return {'deals': list(deals.values()), 'incomes': [], 'notes': [], 'convs': convs,
            'wallets': [mirror(realty), mirror(exchange), mirror(legacy)]}


def seed_crm_deals(exchange_wallet_id):
    """Две сделки обмена с выплатой с кошелька обменника: 5000 и 15000 USDT (порог — 10000 включительно)."""
    db = m.get_session()
    try:
        ids = {'wallet': exchange_wallet_id}
        for tag, amount in (('small', 5000), ('big', 15000)):
            deal = m.Deal(client_name=f'CRM synthetic {tag}', deal_type=m.DealType.PAY_IN,
                          payin_amount_usdt=amount + 100, payout_amount_usdt=amount,
                          payout_source=m.PayOutSource.BINANCE, payout_wallet_id=exchange_wallet_id,
                          payin_method=m.PayInMethod.CRYPTO_DIRECT, payin_wallet_id=exchange_wallet_id)
            db.add(deal)
            db.flush()
            ids[tag] = deal.id
        db.commit()
        return ids
    finally:
        db.close()


def add_referrer(code):
    """Синтетический реферер для проверки refsSync (источник — /api/referrers)."""
    db = m.get_session()
    try:
        db.add(m.Referrer(name=f'QA Referrer {code}', code=code, token=secrets.token_hex(16), telegram='@qa_synthetic'))
        db.commit()
    finally:
        db.close()


def scenario_refs_sync(cap):
    """refsSync: изменение справочника сохраняется, повторный просмотр без изменений версию не растит."""
    page = cap.page('admin', '1280')

    def refs_and_version():
        st = page.request.get(f'{cap.base}/api/stand/state').json()
        return st['version'], [r for r in (st['data'].get('refs') or []) if r.get('prod')]

    v0, refs0 = refs_and_version()
    expect(cap, any(r.get('code') == 'QAREF1' for r in refs0), f'реферер QAREF1 из справочника сохранён в доске после первой синхронизации (refs={[r.get("code") for r in refs0]})')
    page.goto(f'{cap.base}/tasks')
    page.wait_for_timeout(4500)
    v1, _ = refs_and_version()
    cap.log.append({'note': 'refs unchanged reload', 'versionBefore': v0, 'versionAfter': v1})
    expect(cap, v1 == v0, f'повторная загрузка без изменений справочника не растит версию ({v0} -> {v1})')
    add_referrer('QAREF2')
    # standBoot does not refresh an already populated prod registry on reload.
    # Exercise the actual sync explicitly, without inventing automatic refresh.
    page.evaluate('() => refsSync(true)')
    page.wait_for_timeout(4500)
    v2, refs2 = refs_and_version()
    expect(cap, any(r.get('code') == 'QAREF2' for r in refs2) and v2 == v1 + 1,
           f'реальное изменение справочника сохраняется (refs={[r.get("code") for r in refs2]}, версия {v1} -> {v2})')
    page.evaluate('() => refsSync(true)')
    page.wait_for_timeout(1500)
    v_repeat, _ = refs_and_version()
    expect(cap, v_repeat == v2, f'повторный refsSync без изменений не растит версию ({v2} -> {v_repeat})')
    page.goto(f'{cap.base}/tasks')
    page.wait_for_timeout(4500)
    v3, _ = refs_and_version()
    cap.log.append({'note': 'refs changed then unchanged reload', 'versions': [v1, v2, v3]})
    expect(cap, v3 == v2, f'после сохранения изменения повторная загрузка версию не растит ({v2} -> {v3})')


# ---------------------------------------------------------------- SCENARIOS

CLAIM = [r'^беру']
SIGN_S23 = [r'передать на подтверждение', r'подписал']
SIGN_S24 = [r'подписал', r'одобр', r'подтверд']


def per_width(deal_id, width):
    """Мутирующие сценарии получают отдельную сделку на каждую ширину (+10 для 1280)."""
    return deal_id + (0 if width == '375' else 10)


def scenario_s18w_s22(cap):
    for width in WIDTHS:
        for deal, step in ((1601, 's18w'), (1602, 's18w'), (1603, 's22'), (1604, 's22')):
            for role in ('operator', 'manager'):
                page = cap.open_deal(role, width, deal)
                cap.shot(f'deal{deal}_{step}', page, role, width, focus_tabs=4 if role == 'operator' else 0)
        ack_deal = per_width(1609, width)
        warn = cap.open_deal('operator', width, ack_deal)
        cap.shot('wrong_wallet_warning_before_ack', warn, 'operator', width)
        if cap.try_click(warn, [r'подтверждаю расхождение'], f'ack recipient {width}'):
            cap.shot('wrong_wallet_warning_after_ack', warn, 'operator', width)


def scenario_s23_views(cap):
    for width in WIDTHS:
        for deal in (1611, 1612, 1605, 1610):
            for role in ('operator', 'findir', 'teodor', 'manager'):
                page = cap.open_deal(role, width, deal)
                cap.shot(f'deal{deal}_s23', page, role, width, focus_tabs=4 if role == 'operator' else 0)
        over = cap.open_deal('operator', width, 1610)       # 15000 > лимита обменника
        cap.try_click(over, CLAIM, f'claim over limit disabled {width}', expect_disabled=True)
        cap.shot('deal1610_claim_over_limit', over, 'operator', width)
        # адрес подписанта раскрывается по клику (первые 8…последние 8 -> полный)
        sign = cap.open_deal('operator', width, 1611)
        summary = sign.locator('details.deal-detail summary.addr').first
        if summary.count():
            summary.click()
            sign.wait_for_timeout(300)
            cap.shot('signer_address_expanded', sign, 'operator', width)


def scenario_claim_race(cap):
    """Один выигрывает «Беру», второй видит имя взявшего (устаревшая и свежая страница)."""
    for width in WIDTHS:
        did = per_width(1620, width)
        stale = cap.open_deal('findir', width, did)          # загружена ДО клейма
        winner = cap.open_deal('operator', width, did)
        cap.shot('claim_before', winner, 'operator', width)
        address_checks(cap, winner, '#app', REALTY, f'tasks s23 «С кошелька» {width}', require_hidden=False,
                       copy_expected=[REALTY, IPPS, *SIGNERS.values()])
        won = cap.try_click(winner, CLAIM, f'claim operator {width}')
        # проигравший жмёт сразу, пока его устаревшая страница ещё не обновилась опросом
        # Устаревшая страница могла уже обновиться опросом — кнопки тогда законно нет.
        lost = cap.try_click(stale, CLAIM, f'claim findir (stale click, optional) {width}', required=False)
        cap.shot('claim_loser_toast', stale, 'findir', width)
        winner_name = (deal_state(cap, winner, did).get('transferClaim') or {}).get('byName')
        # Обязательное доказательство проигрыша: сервер от имени финансиста отвечает 409 с именем победителя.
        loser_proof = cap.api_post(stale, '/api/stand/transfer/claim', {'dealId': did},
                                   f'findir second claim must lose {width}')
        expect(cap, loser_proof['status'] == 409 and (loser_proof.get('body') or {}).get('taken_by') == winner_name,
               f'проигравший получает 409 с именем победителя «{winner_name}» ({width}), получен {loser_proof}')
        stale.wait_for_timeout(3200)            # опрос состояния раз в 2,5 с
        expect(cap, winner_name and winner_name in stale.inner_text('body'),
               f'на странице проигравшего стоит имя взявшего «{winner_name}» ({width})')
        cap.shot('claim_winner', winner, 'operator', width)
        stale.wait_for_timeout(3200)                          # опрос состояния раз в 2,5 с
        cap.shot('claim_loser_after_poll', stale, 'findir', width)
        cap.shot('claim_loser_fresh_owner', cap.open_deal('teodor', width, did), 'teodor', width)
        cap.log.append({'note': f'race {width}', 'winner_clicked': won, 'loser_clicked': lost})


def stage_s24(did):
    """ФИКСТУРА БД (не UI-переход): после настоящего «Беру» переводим сделку на s24 так, как это делает шаг
    s23, когда хеши добавлены. Настоящий переход требует хешей на полную сумму и сети; он покрыт тестами
    основного QA. Здесь: pending-перевод БЕЗ Success, заявка/кошелёк/сумма прежние, claim не трогаем."""
    db = m.get_session()
    try:
        row = m._stand_row(db)
        state = json.loads(row.data)
        deal = next(x for x in state['deals'] if x['id'] == did)
        ref = secrets.token_hex(32)
        deal['transfer']['sends'] = [{'ref': ref, 'hash': ref, 'net': 'TRC20',
                                      'amount': deal['transfer']['amount'], 'status': 'pending'}]
        deal['step'] = 's24'
        deal['pay'] = dict(deal.get('pay') or {}, check='Синтетическая сверка QA', tx=ref)
        deal.setdefault('log', []).append({'at': int(time.time() * 1000), 'role': 'operator',
            'text': 'QA-фикстура: передано на подтверждение (pending, без Success в сети)'})
        row.data = json.dumps(state, ensure_ascii=False)
        row.version = (row.version or 0) + 1
        db.commit()
    finally:
        db.close()


def deal_state(cap, page, did):
    state = page.request.get(f'{cap.base}/api/stand/state').json()
    return next((x for x in state['data']['deals'] if x['id'] == did), {})


def address_checks(cap, page, scope, full, label, require_hidden=True, copy_expected=None):
    """В области scope: короткий адрес 8…8 (моноширинный), по клику полный адрес, кнопка копирования кладёт полный адрес в буфер."""
    result = page.evaluate('''([scope, full]) => {
      const root = document.querySelector(scope); if (!root) return {error: 'нет области ' + scope};
      const vis = n => n.getClientRects().length > 0;
      const norm = t => t.trim().replace(/\\s*[▾▸▼]$/, '');
      const shorts = [...root.querySelectorAll('*')].filter(n => vis(n) && [...n.childNodes].some(c => c.nodeType === 3) &&
        /^[A-Za-z0-9]{8}(…|\\.\\.\\.)[A-Za-z0-9]{8}$/.test(norm(n.textContent)) &&
        norm(n.textContent).startsWith(full.slice(0, 8)) && norm(n.textContent).endsWith(full.slice(-8)));
      return {shortCount: shorts.length, fullShownBeforeClick: root.innerText.includes(full)};
    }''', [scope, full])
    expect(cap, not result.get('error') and result.get('shortCount', 0) >= 1,
           f'{label}: виден короткий адрес first8…last8 ({result})')
    if require_hidden:
        expect(cap, not result.get('fullShownBeforeClick'), f'{label}: полный адрес не выведен без клика ({result})')
    # по клику — полный адрес (клик по короткому узлу или его summary)
    clicked = page.evaluate('''([scope, full]) => {
      const root = document.querySelector(scope); if (!root) return false;
      const norm = t => t.trim().replace(/\\s*[▾▸▼]$/, '');
      const n = [...root.querySelectorAll('summary, [title], span, code, a, div')].find(x => x.getClientRects().length > 0 &&
        /^[A-Za-z0-9]{8}(…|\\.\\.\\.)[A-Za-z0-9]{8}$/.test(norm(x.textContent)) && norm(x.textContent).startsWith(full.slice(0, 8)));
      if (!n) return false; n.click(); return true; }''', [scope, full])
    page.wait_for_timeout(300)
    after = page.evaluate('([scope, full]) => (document.querySelector(scope) || {innerText: \'\'}).innerText.includes(full)', [scope, full])
    expect(cap, clicked and after, f'{label}: по клику показан полный адрес (клик={clicked}, полный={after})')
    copy = page.locator(f'{scope} button', has_text=re.compile('копир', re.I)).first
    if copy.count() and copy.is_visible():
        copy.click(timeout=8000)
        page.wait_for_timeout(300)
        clip = page.evaluate('() => navigator.clipboard.readText().catch(e => "ERR:" + e.message)')
        allowed = copy_expected or [full]
        expect(cap, clip in allowed, f'{label}: «Копировать» кладёт полный адрес в буфер (буфер={clip[:60]!r})')
    else:
        expect(cap, False, f'{label}: нет видимой кнопки «Копировать»')


def expect(cap, condition, message):
    cap.log.append({'note': 'assert', 'message': message, 'ok': bool(condition)})
    if not condition:
        cap.failed.append(message)


def scenario_s24(cap):
    for width in WIDTHS:
        did = per_width(1621, width)
        op = cap.open_deal('operator', width, did)
        cap.try_click(op, CLAIM, f's24 claim {width}')
        claimed = deal_state(cap, op, did)
        expect(cap, (claimed.get('transferClaim') or {}).get('role') == 'operator',
               f'{did}: клейм оператора записан сервером ({width})')
        stage_s24(did)
        op = cap.open_deal('operator', width, did)
        expect(cap, deal_state(cap, op, did).get('step') == 's24', f'{did}: сделка на шаге s24 ({width})')
        expect(cap, 'Одобрить перевод' in op.inner_text('body') or 'Одобрите перевод' in op.inner_text('body'),
               f'{did}: на экране заявителя именно s24, а не s23 ({width})')
        cap.shot('s24_claimer_cannot_confirm', op, 'operator', width)
        proof = cap.api_post(op, '/api/stand/transfer/confirm', {'dealId': did}, f'forged self-confirm {width}')
        expect(cap, proof['status'] == 403, f'заявитель не подтверждает собственную отправку: 403 ({width}), получен {proof["status"]}')
        for role in ('manager', 'operator'):
            other = cap.api_post(cap.page(role, width), '/api/stand/transfer/confirm', {'dealId': did},
                                 f'{role} confirm (role not a confirmer or claimer) {width}')
            expect(cap, other['status'] in (400, 403), f'{role} не подтверждает: 400/403 ({width}), получен {other["status"]}')
        for role in ('findir', 'teodor'):
            view = cap.open_deal(role, width, did)
            expect(cap, deal_state(cap, view, did).get('step') == 's24', f'{role} видит шаг s24 ({width})')
            cap.shot('s24_confirmer', view, role, width, focus_tabs=4)
        fin = cap.open_deal('findir', width, did)
        cap.try_click(fin, SIGN_S24, f's24 findir confirms {width}')
        confirmed = deal_state(cap, fin, did).get('transferConfirmation') or {}
        expect(cap, confirmed.get('role') == 'findir' and not confirmed.get('ownerAlone'),
               f'подтверждение финансиста записано сервером ({width})')
        cap.shot('s24_after_confirm', fin, 'findir', width)
        alone = per_width(1622, width)
        owner = cap.open_deal('teodor', width, alone)
        cap.try_click(owner, CLAIM, f'owner alone claim {width}')
        own_state = deal_state(cap, owner, alone)
        expect(cap, (own_state.get('transferConfirmation') or {}).get('ownerAlone') is True,
               f'{alone}: владелец сам — подтверждение ownerAlone записано сервером ({width})')
        expect(cap, own_state.get('step') == 's23', f'{alone}: заявка владельца ещё на s23 до сети ({width})')
        cap.shot('owner_alone_claimed', owner, 'teodor', width)
        # Подтверждённый сетью Success (пропуск s24 при verified-хеше) в UI не моделируем:
        # нужен реальный перевод; это доказывают pytest основного QA.


def api_call(cap, page, method, path, payload, note, expect):
    """Прямой вызов CRM API от имени роли; статус обязан входить в expect, иначе сценарий провален."""
    result = page.evaluate('''async ([method, path, payload]) => {
        const r = await fetch(path, {method, headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(payload)});
        let body = null; try { body = await r.json(); } catch (e) {}
        return {status: r.status, error: body && (body.error || body.message), success: body && body.success};
    }''', [method, path, payload])
    cap.log.append({'note': note, 'api': f'{method} {path}', 'payload': payload, 'response': result})
    if result['status'] not in expect:
        cap.failed.append(f'{note}: статус {result["status"]}, ожидалось {sorted(expect)}')
    return result


def crm_facts(page):
    return page.evaluate('''() => { const q = id => document.getElementById(id);
      const visible = n => !!n && n.getClientRects().length > 0;
      const sel = q('payoutWalletSelect'), pay = q('payinWalletSelect');
      return {editingDealId: typeof editingDealId !== 'undefined' ? editingDealId : null,
        payoutSelectVisible: visible(sel), payoutSelected: sel && sel.selectedOptions[0] ? sel.selectedOptions[0].textContent : null,
        payoutPolicyText: q('payoutWalletPolicy') ? q('payoutWalletPolicy').textContent : null,
        approvalCheckboxVisible: visible(q('payoutOwnerApprovalGroup')),
        approvalChecked: q('payoutOwnerApproved') ? q('payoutOwnerApproved').checked : null,
        payinGroupVisible: visible(q('payinWalletGroup')),
        payinSelected: pay && pay.selectedOptions[0] ? pay.selectedOptions[0].textContent : null,
        payinPolicyText: q('payinWalletPolicy') ? q('payinWalletPolicy').textContent : null}; }''')


def scenario_crm(cap, base, crm_ids):
    """CRM-блок выплаты и получения обменника: реальный редактор сделки под каждой ролью."""
    small, big = crm_ids['small'], crm_ids['big']
    for width in WIDTHS:   # сама страница CRM без редактора: реальная ширина на 375 у каждой роли
        for role in ROLES:
            page = cap.page(role, width)
            page.goto(f'{base}/crm?section=deals')
            page.wait_for_timeout(1800)
            cap.shot('crm_page_deals', page, role, width)
    for width in WIDTHS:
        for role, deal, tag in (('operator', big, 'big'), ('findir', big, 'big'), ('teodor', big, 'big'),
                                ('manager', big, 'big'), ('admin', big, 'big'), ('operator', small, 'small')):
            page = cap.page(role, width)
            page.goto(f'{base}/crm?section=deals')
            page.wait_for_timeout(1500)
            page.evaluate(f'openDealEditor({deal})')
            page.wait_for_selector('#payoutWalletSelect', state='attached', timeout=15000)
            page.wait_for_timeout(1800)
            page.evaluate("() => { const g = document.getElementById('binanceGroup'); if (g) g.scrollIntoView(); }")
            facts = crm_facts(page)
            facts.update(role=role, width=width, deal=tag)
            cap.crm_facts.append(facts)
            if role == 'findir' and tag == 'big':
                address_checks(cap, page, '#binanceGroup', EXCHANGE, f'CRM выплата, кошелёк списания {width}')
                address_checks(cap, page, '#payinWalletGroup', EXCHANGE, f'CRM приход, кошелёк получения {width}')
            cap.shot(f'crm_exchange_payout_{tag}', page, role, width,
                     focus_tabs=0)
            group = page.locator('#binanceGroup')
            if group.count() and group.is_visible():
                group.screenshot(path=str(OUT / f'crm_binance_group_{tag}__{role}__{width}.png'))
            else:
                cap.failed.append(f'CRM {role}/{width}/{tag}: блок «Кошелёк списания» не виден')
            pay = page.locator('#payinWalletGroup')
            if pay.count() and pay.is_visible():
                pay.screenshot(path=str(OUT / f'crm_payin_group_{tag}__{role}__{width}.png'))
    # Серверное доказательство правил (роль берётся из cookie, не из тела запроса)
    page = cap.page('operator', '1280')
    page.goto(f'{base}/crm?section=deals')
    page.wait_for_timeout(800)
    exchange_id = crm_ids['wallet']
    base_payload = {'payout_wallet_id': exchange_id, 'payout_source': 'binance'}
    api_call(cap, page, 'PUT', f'/api/deals/{small}', dict(base_payload, payout_amount_usdt=5000),
             'operator: 5000 без флага проходит', {200})
    api_call(cap, page, 'PUT', f'/api/deals/{big}', dict(base_payload, payout_amount_usdt=15000),
             'operator: 15000 без флага -> 400', {400})
    api_call(cap, page, 'PUT', f'/api/deals/{big}', dict(base_payload, payout_amount_usdt=15000, payout_owner_approved=True),
             'operator: флаг одобрения ставить не может', {400, 403})
    manager = cap.page('manager', '1280')
    manager.goto(f'{base}/crm?section=deals')
    manager.wait_for_timeout(800)
    api_call(cap, manager, 'PUT', f'/api/deals/{big}', dict(base_payload, payout_amount_usdt=15000, payout_owner_approved=True),
             'manager: флаг одобрения ставить не может', {400, 403})
    fin = cap.page('findir', '1280')
    fin.goto(f'{base}/crm?section=deals')
    fin.wait_for_timeout(800)
    api_call(cap, fin, 'PUT', f'/api/deals/{big}', dict(base_payload, payout_amount_usdt=15000, payout_owner_approved=True),
             'findir: 15000 с флагом проходит', {200})
    api_call(cap, page, 'PUT', f'/api/deals/{big}', dict(base_payload, payout_amount_usdt=15000),
             'operator: правка суммы без нового флага сбрасывает/блокирует (не обходит)', {200, 400})
    # после одобрения владельцем/финансистом — показать состояние флага в форме
    owner = cap.page('teodor', '1280')
    owner.goto(f'{base}/crm?section=deals')
    owner.wait_for_timeout(1500)
    owner.evaluate(f'openDealEditor({big})')
    owner.wait_for_selector('#payoutWalletSelect', state='attached', timeout=15000)
    owner.wait_for_timeout(1800)
    owner.evaluate("() => { const g = document.getElementById('binanceGroup'); if (g) g.scrollIntoView(); }")
    cap.crm_facts.append(dict(crm_facts(owner), role='teodor', width='1280', deal='big-after-approval'))
    cap.shot('crm_exchange_payout_big_after_approval', owner, 'teodor', '1280')


def source_freeze():
    """Какой код снимали: HEAD и чистота исходников UI/приложения. Грязное дерево — не финальная съёмка."""
    root = Path(__file__).resolve().parents[3]
    sources = ['app.py', 'static/stand/tasks.html', 'static/crm/crm.html', 'stand_transfers.py',
               'stand_prepay.py', 'stand_browser.py']
    info = {'sha256': {name: hashlib.sha256((root / name).read_bytes()).hexdigest()[:16] for name in sources}}
    try:
        git = lambda *args: subprocess.run(['git', *args], cwd=root, capture_output=True, text=True, timeout=20).stdout.strip()
        info['head'] = git('rev-parse', 'HEAD')
        info['dirty_sources'] = [line for line in git('status', '--porcelain', '--', *sources).splitlines()]
        info['clean'] = not info['dirty_sources']
    except Exception as exc:
        info['git_error'] = repr(exc)
        info['clean'] = None
    return info


# ---------------------------------------------------------------- тест

def test_capture_wallet_roles_ui(app_env, pytestconfig):
    base, cookies, _ids = app_env
    freeze = source_freeze()
    if OUT.exists():   # кадры предыдущих прогонов (другой код) смешивать нельзя
        for old in list(OUT.glob('*.png')) + list(OUT.glob('*.json')):
            old.unlink()
    reg = registry_wallets()
    seed_state(build_state(reg))
    crm_ids = seed_crm_deals(reg[EXCHANGE]['id'])
    add_referrer('QAREF1')
    executable = pytestconfig.getoption('--chromium-executable')
    errors = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=executable) if executable else p.chromium.launch()
        cap = Capture(browser, base, cookies)
        # Разогрев: админ один раз открывает задачник, клиент дописывает в синтетическую доску
        # значения по умолчанию (migrate), как в реально сохранённых сделках. Без него просмотр под
        # другой ролью давал отклонённое автосохранение (409) — артефакт фикстуры, не поведение продукта.
        cap.phase = 'warmup-admin'
        warm = cap.page('admin', '1280')
        warm.goto(f'{base}/tasks')
        warm.wait_for_timeout(6000)
        cap.phase = 'capture'
        for name, scenario in (('s18w_s22', scenario_s18w_s22), ('s23_views', scenario_s23_views),
                               ('claim_race', scenario_claim_race), ('s24', scenario_s24), ('refs_sync', scenario_refs_sync),
                               ('crm', lambda c: scenario_crm(c, base, crm_ids))):
            try:
                scenario(cap)
            except Exception as exc:  # один сценарий не должен прятать остальные
                errors[name] = repr(exc)
        browser.close()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'run.json').write_text(json.dumps({
        'shots': cap.shots, 'actions': cap.log, 'external_requests_blocked': cap.external,
        'optional_static_blocked': cap.optional_static,
        'console': [list(map(str, x)) for x in cap.console], 'scenario_errors': errors,
        'harness_version': HARNESS_VERSION, 'source_freeze': freeze, 'failed_required_actions': cap.failed, 'crm_facts': cap.crm_facts, 'version_gate': {'views': len(cap.opens), 'viewsWithVersionBump': sum(o['viewMutated'] for o in cap.opens),
                         'semanticViews': sum(o['semanticChange'] for o in cap.opens), 'noopVersionBumps': sum(o['noopVersionBump'] for o in cap.opens)},
        'views': cap.opens, 'views_that_mutated_state': [o for o in cap.opens if o['viewMutated']],
        'state_put_log': [{k: v for k, v in e.items() if k != 'sent'} for e in cap.put_log],
        'http_errors': [list(map(str, x)) for x in cap.http_errors],
        'stubbed_egress_ops': sorted(set(getattr(m, 'EGRESS_CALLS', [])))},
        ensure_ascii=False, indent=1))
    (OUT / 'state_put_payloads.json').write_text(json.dumps(
        [e for e in cap.put_log if e['status'] != 200][:6], ensure_ascii=False))
    viewer_rejects = [e for e in cap.put_log if e['phase'] != 'warmup-admin' and e['status'] != 200]
    problems = []
    if cap.failed:
        problems.append(f'обязательные действия/проверки не выполнены ({len(cap.failed)}): {cap.failed}')
    if viewer_rejects:
        problems.append(f'просмотр вызвал отклонённое автосохранение: {len(viewer_rejects)} '
                        f'({sorted({(e["role"], e["status"], e["error"]) for e in viewer_rejects})})')
    if cap.external:
        problems.append(f'внешние запросы из браузера: {cap.external[:5]}')
    assert not problems, ' || '.join(problems)


def test_capture_crm_addresses_only(app_env, pytestconfig):
    """Только проверки адресов CRM (r7b): запуск `-k crm_addresses_only`. Не стирает кадры основного прогона."""
    base, cookies, _ids = app_env
    reg = registry_wallets()
    seed_state(build_state(reg))
    crm_ids = seed_crm_deals(reg[EXCHANGE]['id'])
    executable = pytestconfig.getoption('--chromium-executable')
    out = Path(__file__).parent / 'shots-crm-addresses'   # отдельный каталог: кадры полного r7 не трогаем
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=executable) if executable else p.chromium.launch()
        cap = Capture(browser, base, cookies)
        cap.phase = 'capture'
        for width in WIDTHS:
            page = cap.page('findir', width)
            page.goto(f'{base}/crm?section=deals')
            page.wait_for_timeout(1500)
            page.evaluate(f"openDealEditor({crm_ids['big']})")
            page.wait_for_selector('#payoutWalletSelect', state='attached', timeout=15000)
            page.wait_for_timeout(1800)
            page.evaluate("() => { const g = document.getElementById('binanceGroup'); if (g) g.scrollIntoView(); }")
            address_checks(cap, page, '#binanceGroup', EXCHANGE, f'CRM выплата, кошелёк списания {width}')
            address_checks(cap, page, '#payinWalletGroup', EXCHANGE, f'CRM приход, кошелёк получения {width}')
            page.locator('#binanceGroup').screenshot(path=str(out / f'crm_addresses_only__binance__{width}.png'))
        browser.close()
    (out / 'crm_addresses_only.json').write_text(json.dumps(
        {'harness_version': HARNESS_VERSION + ' + crm-only', 'source_freeze': source_freeze(), 'actions': cap.log,
         'failed': cap.failed, 'external_requests_blocked': cap.external}, ensure_ascii=False, indent=1))
    assert not cap.failed, cap.failed
    assert not cap.external


def test_capture_refs_sync_only(app_env, pytestconfig):
    """Supplement to raw UI8; keeps shots/run.json and all matrix PNGs intact."""
    base, cookies, _ids = app_env
    seed_state(build_state(registry_wallets()))
    add_referrer('QAREF1')
    out = Path(__file__).parent / 'shots-refs-sync'
    out.mkdir(parents=True, exist_ok=True)
    executable = pytestconfig.getoption('--chromium-executable')
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=executable) if executable else p.chromium.launch()
        cap = Capture(browser, base, cookies)
        cap.phase = 'warmup-admin'
        page = cap.page('admin', '1280')
        page.goto(f'{base}/tasks')
        page.wait_for_timeout(6000)
        cap.phase = 'capture'
        scenario_refs_sync(cap)
        page.screenshot(path=str(out / 'refs-sync__admin__1280.png'))
        browser.close()
    rejected = [e for e in cap.put_log if e['status'] != 200]
    (out / 'refs-sync.json').write_text(json.dumps({
        'harness_version': HARNESS_VERSION + ' + refs-only correction 2026-10-20',
        'source_freeze': source_freeze(), 'actions': cap.log, 'failed': cap.failed,
        'rejected_puts': [{k: v for k, v in e.items() if k != 'sent'} for e in rejected],
        'external_requests_blocked': cap.external,
    }, ensure_ascii=False, indent=1))
    assert not cap.failed, cap.failed
    assert not rejected, rejected
    assert not cap.external


MONEY_WRAP_JS = '''(selectors) => {
  const out = [];
  for (const sel of selectors) {
    const root = document.querySelector(sel);
    if (!root || root.getClientRects().length === 0) { out.push({sel, visible: false}); continue; }
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const node = walker.currentNode, text = node.nodeValue;
      for (const m of text.matchAll(/\\$[ \\u00a0]?\\d[\\d \\u00a0]*(?:,\\d{2})?/g)) {
        const range = document.createRange();
        range.setStart(node, m.index); range.setEnd(node, m.index + m[0].length);
        const tops = [...new Set([...range.getClientRects()].map(r => Math.round(r.top)))];
        out.push({sel, amount: m[0], lines: tops.length, hasNbsp: m[0].includes('\\u00a0'), broken: tops.length > 1});
      }
    }
  }
  return out;
}'''


def test_capture_crm_money_wrap_only(app_env, pytestconfig):
    """Диагностика (r8b): сумма в CRM-блоке выплаты не переносится внутри числа на 375. Запуск: -k crm_money_wrap_only."""
    base, cookies, _ids = app_env
    reg = registry_wallets()
    seed_state(build_state(reg))
    crm_ids = seed_crm_deals(reg[EXCHANGE]['id'])
    executable = pytestconfig.getoption('--chromium-executable')
    out = Path(__file__).parent / 'shots-crm-money-wrap'
    out.mkdir(parents=True, exist_ok=True)
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=executable) if executable else p.chromium.launch()
        cap = Capture(browser, base, cookies)
        cap.phase = 'capture'
        for width in WIDTHS:
            page = cap.page('findir', width)
            page.goto(f'{base}/crm?section=deals')
            page.wait_for_timeout(1500)
            page.evaluate(f"openDealEditor({crm_ids['big']})")
            page.wait_for_selector('#payoutWalletSelect', state='attached', timeout=15000)
            page.wait_for_timeout(1800)
            page.evaluate("() => { const g = document.getElementById('binanceGroup'); if (g) g.scrollIntoView(); }")
            found = page.evaluate(MONEY_WRAP_JS, ['#payoutWalletPolicy', '#payoutOwnerApprovalGroup', '#payinWalletPolicy'])
            results.append({'width': width, 'amounts': found})
            page.locator('#binanceGroup').screenshot(path=str(out / f'crm_money_wrap__{width}.png'))
            for item in found:
                if item.get('broken'):
                    cap.failed.append(f'CRM {width}: сумма {item["amount"]!r} переносится внутри числа в {item["sel"]} (nbsp в тексте: {item["hasNbsp"]})')
        browser.close()
    (out / 'crm_money_wrap.json').write_text(json.dumps(
        {'harness_version': HARNESS_VERSION + ' + money-wrap', 'source_freeze': source_freeze(), 'results': results,
         'failed': cap.failed}, ensure_ascii=False, indent=1))
    assert not cap.failed, cap.failed


EXPANDED_ADDRESS_JS = '''(scope) => {
  const box = document.querySelector(scope);
  const code = box && box.querySelector('code');
  if (!code || code.getClientRects().length === 0) return {visible: false};
  const range = document.createRange(); range.selectNodeContents(code);
  const tops = [...new Set([...range.getClientRects()].map(r => Math.round(r.top)))];
  const cs = getComputedStyle(code), rect = code.getBoundingClientRect();
  return {visible: true, text: code.textContent, lines: tops.length, whiteSpace: cs.whiteSpace, overflowX: cs.overflowX,
    scrollWidth: code.scrollWidth, clientWidth: code.clientWidth, right: Math.round(rect.right),
    docScrollWidth: document.documentElement.scrollWidth, innerWidth: innerWidth};
}'''


def test_capture_crm_residual_final(app_env, pytestconfig):
    """Финальная точечная проверка CRM (только findir и teodor, 375 и 1280): суммы не рвутся внутри числа;
    развёрнутый полный адрес в одной строке без переполнения страницы; «Копировать» кладёт полный адрес.
    Запуск: -k crm_residual_final. Пишет в shots-crm-residual/, остальные каталоги не трогает."""
    base, cookies, _ids = app_env
    reg = registry_wallets()
    seed_state(build_state(reg))
    crm_ids = seed_crm_deals(reg[EXCHANGE]['id'])
    executable = pytestconfig.getoption('--chromium-executable')
    out = Path(__file__).parent / 'shots-crm-residual'
    out.mkdir(parents=True, exist_ok=True)
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=executable) if executable else p.chromium.launch()
        cap = Capture(browser, base, cookies)
        cap.phase = 'capture'
        for role in ('findir', 'teodor'):
            for width in WIDTHS:
                tag = f'{role}__{width}'
                page = cap.page(role, width)
                page.goto(f'{base}/crm?section=deals')
                page.wait_for_timeout(1500)
                page.evaluate(f"openDealEditor({crm_ids['big']})")
                page.wait_for_selector('#payoutWalletSelect', state='attached', timeout=15000)
                page.wait_for_timeout(1800)
                page.evaluate("() => { const g = document.getElementById('binanceGroup'); if (g) g.scrollIntoView(); }")
                entry = {'role': role, 'width': width}
                # 1) суммы: ни одна не переносится внутри числа; чекбокс виден владельцу/финансисту
                money = page.evaluate(MONEY_WRAP_JS, ['#payoutWalletPolicy', '#payoutOwnerApprovalGroup', '#payinWalletPolicy'])
                entry['money'] = money
                tokens = [m_ for m_ in money if m_.get('amount')]
                expect(cap, any(m_['sel'] == '#payoutOwnerApprovalGroup' for m_ in tokens),
                       f'{tag}: сумма в подписи согласования найдена и измерена')
                for item in tokens:
                    expect(cap, not item['broken'], f'{tag}: сумма {item["amount"]!r} в {item["sel"]} не рвётся внутри числа (строк: {item["lines"]})')
                # 2) адреса: свёрнуто -> развернуто; одна строка, без переполнения страницы; копирование
                for scope, label in (('#payoutWalletAddress', 'выплата'), ('#payinWalletAddress', 'приход')):
                    before = page.evaluate(EXPANDED_ADDRESS_JS, scope)
                    summary = page.locator(f'{scope} summary').first
                    expect(cap, summary.count() > 0 and summary.is_visible(), f'{tag}/{label}: виден короткий адрес (summary)')
                    summary.click()
                    page.wait_for_timeout(300)
                    after = page.evaluate(EXPANDED_ADDRESS_JS, scope)
                    entry[f'address_{label}'] = {'beforeClickVisible': before.get('visible'), 'expanded': after}
                    expect(cap, after.get('visible') and after.get('text') == EXPANDED_FULL,
                           f'{tag}/{label}: после клика показан полный адрес ({after})')
                    expect(cap, after.get('lines') == 1,
                           f'{tag}/{label}: развёрнутый полный адрес в ОДНУ строку (строк: {after.get("lines")}, white-space={after.get("whiteSpace")})')
                    expect(cap, after.get('docScrollWidth', 0) <= after.get('innerWidth', 0) + 1,
                           f'{tag}/{label}: страница не шире экрана после раскрытия ({after.get("docScrollWidth")} > {after.get("innerWidth")})')
                    copy = page.locator(f'{scope} button', has_text=re.compile('копир', re.I)).first
                    if copy.count() and copy.is_visible():
                        copy.click(timeout=8000)
                        page.wait_for_timeout(300)
                        clip = page.evaluate('() => navigator.clipboard.readText().catch(e => "ERR:" + e.message)')
                        expect(cap, clip == EXPANDED_FULL, f'{tag}/{label}: «Копировать» кладёт полный адрес в буфер (буфер={clip[:50]!r})')
                    else:
                        expect(cap, False, f'{tag}/{label}: нет видимой кнопки «Копировать»')
                facts = crm_facts(page)
                entry['facts'] = facts
                expect(cap, facts['approvalCheckboxVisible'] is True, f'{tag}: чекбокс согласования виден роли {role}')
                page.locator('#binanceGroup').screenshot(path=str(out / f'crm_residual__{tag}.png'))
                results.append(entry)
        browser.close()
    (out / 'crm_residual_final.json').write_text(json.dumps(
        {'harness_version': HARNESS_VERSION + ' + residual-final', 'source_freeze': source_freeze(), 'results': results,
         'actions': cap.log, 'failed': cap.failed, 'external_requests_blocked': cap.external}, ensure_ascii=False, indent=1))
    assert not cap.failed and not cap.external, ' || '.join(cap.failed) + (f' external={cap.external[:3]}' if cap.external else '')


EXPANDED_FULL = EXCHANGE
