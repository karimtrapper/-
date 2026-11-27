"""Check how the calculator drawer uses a saved desktop icon rail preference."""
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

import app as A
from tests.test_browser_crm import chromium, crm_server  # noqa: F401


@pytest.mark.browser
def test_saved_rail_keeps_calculator_mobile_sidebar_labels(chromium, crm_server, monkeypatch):
    monkeypatch.setattr(A, 'TASKS_ENABLED', True)
    monkeypatch.setattr(A, 'STAND_MODE', False)
    base, cookie = crm_server
    with chromium.new_context(viewport={'width': 390, 'height': 844},
                              is_mobile=True, has_touch=True) as context:
        context.add_cookies([{'name': 'session', 'value': cookie, 'url': base}])
        context.add_init_script("""localStorage.setItem('calccrm:slate-preferences',
            JSON.stringify({sidebar: 'rail', mode: 'dark'}));""")
        context.route('**/*', lambda route: route.continue_()
                      if urlsplit(route.request.url).hostname == '127.0.0.1' else route.abort())
        page = context.new_page()
        page.goto(base + '/')
        root = page.locator('html')
        expect(root).to_have_attribute('data-sidebar', 'rail')
        trigger = page.locator('[data-slate-sidebar]')
        sidebar = page.locator('#slate-sidebar')
        drawer = page.locator('.slate-drawer')
        label_selector = ('.slate-identity, .slate-group-label, .slate-link-label, '
                          '.slate-user summary > .slate-icon')
        label_state = '''els => els.map(el => {
          const box = el.getBoundingClientRect();
          const style = getComputedStyle(el);
          return [box.width, box.height, style.clipPath, style.visibility, style.position];
        })'''

        for width in (390, 767):
            page.set_viewport_size({'width': width, 'height': 844})
            trigger.click()
            expect(drawer).to_be_visible()
            expect(trigger).to_have_attribute('aria-expanded', 'true')
            expect(sidebar.locator('.slate-workspace .slate-identity')).to_contain_text('CalcCRM')
            expect(sidebar.locator('.slate-user .slate-identity')).to_contain_text('QA Browser')
            expect(sidebar.locator('.slate-link[aria-current="page"]')).to_contain_text('Калькулятор')
            labels = sidebar.locator(label_selector).evaluate_all(label_state)
            assert len(labels) >= 12
            assert all(w > 1 and h > 1 and clip == 'none' and visible == 'visible'
                       for w, h, clip, visible, _ in labels)
            if width == 390:
                drawer.locator('.slate-drawer-close').click()
                expect(drawer).to_be_hidden()

        # Resizing with the mobile drawer open restores the desktop icon rail.
        for width in (768, 1440):
            page.set_viewport_size({'width': width, 'height': 844})
            expect(drawer).to_be_hidden()
            expect(sidebar).to_be_visible()
            expect(trigger).to_have_attribute('aria-expanded', 'false')
            labels = sidebar.locator(label_selector).evaluate_all(label_state)
            assert all(clip == 'inset(50%)' and position == 'absolute'
                       for _, _, clip, _, position in labels), (width, labels)

        page.set_viewport_size({'width': 390, 'height': 844})
        trigger.click()
        expect(drawer).to_be_visible()
        expect(root).to_have_attribute('data-sidebar', 'rail')
        assert all(w > 1 and h > 1 and clip == 'none'
                   for w, h, clip, _, _ in sidebar.locator(label_selector).evaluate_all(label_state))
