"""Exact, stage-only browser asset and integration presentation overlays.

The source HTML is shared with production. This module changes only the served
STAND_MODE response and leaves the source files and production response intact.
"""

import re


VENDOR_PREFIX = '/static/stand/vendor/'
INTER_CSS = VENDOR_PREFIX + 'inter-v20/font.css'
JAKARTA_CSS = VENDOR_PREFIX + 'plus-jakarta-sans-v12/font.css'
CHART_JS = VENDOR_PREFIX + 'chartjs-4.4.7/chart.umd.min.js'
STATUS_JS = '/static/stand/browser-status.js'
PAGE_SOURCES = {
    'calculator': 'static/calculator/index.html',
    'crm': 'static/crm/crm.html',
    'referrer': 'static/referrer/index.html',
    'partner': 'static/partner/index.html',
    'kyc': 'static/kyc/index.html',
    'login': 'static/auth/login.html',
    'tasks': 'static/stand/tasks.html',
    'walkthrough': 'static/stand/walkthrough/leasehold-rub.html',
}

# Keep inline scripts, styles, blob PDF previews, data images and same-origin
# document requests working. The browser may still navigate to external links
# explicitly clicked by a user; page-initiated resource and API egress is closed.
STAND_CSP = (
    "default-src 'self' data: blob:; "
    "script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
    "font-src 'self' data:; img-src 'self' data: blob:; "
    "connect-src 'self'; frame-src 'self' blob: data:; "
    "worker-src 'self' blob:; object-src 'self' blob: data:; "
    "form-action 'self'; base-uri 'self'"
)

_FONT_LINK = re.compile(r'<link\b[^>]*\bhref="https://fonts\.googleapis\.com/css2\?family=([^"&]+)[^"]*"[^>]*>', re.I)
_PRECONNECT = re.compile(r'<link\b[^>]*\brel="preconnect"[^>]*\bhref="https://fonts\.(?:googleapis|gstatic)\.com"[^>]*>\s*', re.I)
_CHART_LINK = '<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>'
_LOGIN_WIDGET_CONDITION = 'if (!(window.Telegram && window.Telegram.Login)) {'


def page_kind(path):
    if path in ('/', '/calculator/index.html', '/static/calculator/index.html'):
        return 'calculator'
    if path in ('/crm', '/crm/crm.html', '/static/crm/crm.html'):
        return 'crm'
    if path in ('/login', '/auth/login.html', '/static/auth/login.html'):
        return 'login'
    if path in ('/kyc/', '/kyc/index.html', '/static/kyc/index.html'):
        return 'kyc'
    if path in ('/tasks', '/tasks/tasks.html', '/static/stand/tasks.html'):
        return 'tasks'
    if path in ('/tasks/walkthrough/leasehold-rub.html',
                '/static/stand/walkthrough/leasehold-rub.html'):
        return 'walkthrough'
    if re.fullmatch(r'/partner/[^/]+(?:/index\.html)?', path):
        return 'partner'
    if re.fullmatch(r'/ref/[^/]+', path) or path == '/static/referrer/index.html':
        return 'referrer'
    return None


def transform_html(kind, html):
    """Replace only registered asset tags and two stage-specific UI behaviors."""
    html = _PRECONNECT.sub('', html)

    def local_font(match):
        family = match.group(1)
        if family.startswith('Inter:'):
            href = INTER_CSS
        elif family.startswith('Plus+Jakarta+Sans:'):
            href = JAKARTA_CSS
        else:
            raise ValueError('Unregistered external font: ' + family)
        return '<link href="' + href + '" rel="stylesheet">'

    html, font_count = _FONT_LINK.subn(local_font, html)
    if font_count != 1:
        raise ValueError(f'{kind}: expected one registered font link, got {font_count}')
    if kind == 'crm':
        if html.count(_CHART_LINK) != 1:
            raise ValueError('crm: Chart.js source changed')
        html = html.replace(_CHART_LINK, '<script src="' + CHART_JS + '"></script>')
        html = html.replace('</body>', '<script src="' + STATUS_JS + '"></script>\n</body>', 1)
    if kind == 'login':
        if html.count(_LOGIN_WIDGET_CONDITION) != 1:
            raise ValueError('login: Telegram widget condition changed')
        # tg-config returns stand_blocked; do not insert a remote widget script.
        html = html.replace(_LOGIN_WIDGET_CONDITION,
                            'if (cfg.bot_id && !(window.Telegram && window.Telegram.Login)) {')
    return html
