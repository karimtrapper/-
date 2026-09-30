// Browser regression for the stand-only mobile CRM entry and task layout.
// Uses the workspace Playwright install and serves only local static files.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const { chromium, webkit, devices } = require(path.resolve(__dirname, '../../../node_modules/playwright'));

const root = path.resolve(__dirname, '..');
const mime = { '.html': 'text/html; charset=utf-8', '.json': 'application/json; charset=utf-8', '.js': 'text/javascript; charset=utf-8' };
const server = http.createServer((req, res) => {
  const pathname = new URL(req.url, 'http://localhost').pathname;
  const target = pathname === '/tasks' ? 'static/stand/tasks.html'
    : pathname === '/crm' ? 'static/crm/crm.html'
      : pathname.startsWith('/tasks/') ? `static/stand/${pathname.slice('/tasks/'.length)}`
        : pathname.startsWith('/walkthrough/') ? `static/stand/${pathname.slice(1)}`
        : pathname.replace(/^\//, '');
  const file = path.resolve(root, target);
  if (!file.startsWith(root + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
    res.writeHead(404).end('not found'); return;
  }
  res.writeHead(200, { 'content-type': mime[path.extname(file)] || 'application/octet-stream' });
  fs.createReadStream(file).pipe(res);
});

async function main() {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const base = `http://127.0.0.1:${server.address().port}`;
  const browserType = process.env.BROWSER === 'webkit' ? webkit : chromium;
  const browser = await browserType.launch({ headless: true });
  let apiMode = 'prod';
  const writes = [];
  try {
    const context = await browser.newContext({ ...devices['iPhone 15'] });
    const page = await context.newPage();
    await page.route('**/api/**', async route => {
      const req = route.request();
      if (req.method() !== 'GET' && req.method() !== 'HEAD') {
        writes.push(`${req.method()} ${req.url()}`); await route.abort(); return;
      }
      const url = new URL(req.url());
      let status = 404, data = { success: false };
      if (url.pathname === '/api/auth/me') {
        status = 200; data = { success: true, user: { stand: apiMode === 'stand', role: 'admin' } };
      } else if (url.pathname === '/api/stand/roles' && apiMode === 'stand') {
        status = 200; data = { success: true, roles: { manager: 'Менеджер', operator: 'Операционист' } };
      } else if (url.pathname === '/api/stand/state') {
        status = 200; data = { success: true, version: 1, data: {} };
      }
      await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) });
    });

    // Production keeps Dashboard and does not expose the stand task link.
    await page.goto(`${base}/crm`);
    await page.waitForTimeout(150);
    let nav = await page.evaluate(() => ({
      visible: [...document.querySelectorAll('#bottomNav .bottom-nav-item')]
        .filter(el => getComputedStyle(el).display !== 'none').length,
      tasks: getComputedStyle(document.querySelector('#standTasksNav')).display,
      dashboard: getComputedStyle(document.querySelector('#bottomNav [data-nav-section="dashboard"]')).display,
    }));
    assert.deepEqual(nav, { visible: 5, tasks: 'none', dashboard: 'flex' });

    // Confirm the stand and verify five visible slots, Tasks in the bar,
    // Dashboard in More, stable active state, and a working /tasks destination.
    apiMode = 'stand';
    await page.reload();
    await page.waitForFunction(() => getComputedStyle(document.querySelector('#standTasksNav')).display === 'flex');
    nav = await page.evaluate(() => ({
      visible: [...document.querySelectorAll('#bottomNav .bottom-nav-item')]
        .filter(el => getComputedStyle(el).display !== 'none').length,
      tasks: getComputedStyle(document.querySelector('#standTasksNav')).display,
      dashboard: getComputedStyle(document.querySelector('#bottomNav [data-nav-section="dashboard"]')).display,
      dashboardMore: getComputedStyle(document.querySelector('#standDashboardMore')).display,
    }));
    assert.deepEqual(nav, { visible: 5, tasks: 'flex', dashboard: 'none', dashboardMore: 'flex' });
    await page.evaluate(() => document.querySelector('#moreBtn').click());
    assert.equal(await page.locator('#standDashboardMore').isVisible(), true);
    await page.evaluate(() => closeMorePanel());
    await page.evaluate(() => document.querySelector('#bottomNav [data-nav-section="deals"]').click());
    assert.equal(await page.locator('#bottomNav [data-nav-section="deals"]').getAttribute('class'), 'bottom-nav-item active');
    await page.evaluate(() => document.querySelector('#standTasksNav').click());
    await page.waitForURL('**/tasks');
    // Synthetic mode keeps actual role switching local: save() is disabled and
    // every server request remains read-only while exercising the real handlers.
    await page.goto(`${base}/tasks?snap=walkthrough/leasehold-rub/01.json`);
    await page.evaluate(() => { standMe = 'admin'; render(); });
    await page.waitForFunction(() => document.querySelector('#roles .rolebtn'));

    // Use read-only walkthrough snapshots as synthetic deal data. Sweep every
    // role/step at the requested CSS widths, then a document card and bottom sheet.
    for (const width of [375, 390, 430]) {
      await page.setViewportSize({ width, height: 844 });
      const sweep = await page.evaluate(async () => {
        const failures = [];
        const viewportMeta = document.querySelector('meta[name="viewport"]')?.content || '';
        const roles = document.querySelector('#roles');
        const roleBtn = roles?.querySelector('.rolebtn');
        const roleLayout = {
          railWidth: roles?.getBoundingClientRect().width || 0,
          visibleButtonWidth: roleBtn?.getBoundingClientRect().width || 0,
          railClientWidth: roles?.clientWidth || 0,
          metaShrinkToFit: viewportMeta.includes('shrink-to-fit=no'),
        };
        if (roleLayout.railWidth < innerWidth - 24 || roleLayout.visibleButtonWidth < 90 || !roleLayout.metaShrinkToFit)
          failures.push({ roleLayout });
        for (let i = 1; i <= 21; i++) {
          const n = String(i).padStart(2, '0');
          const snap = await (await fetch(`/static/stand/walkthrough/leasehold-rub/${n}.json`)).json();
          S = migrate(Object.assign(load(), snap.state || {}));
          S.role = snap.role; S.open = snap.open; S.view = snap.view; S.tab = 'tasks'; S.modal = null; S.doc = null;
          render();
          const html = document.documentElement, body = document.body, app = document.querySelector('#app').getBoundingClientRect();
          if (html.scrollWidth !== innerWidth || body.scrollWidth !== innerWidth || app.right > innerWidth + 1)
            failures.push({ frame: i, role: snap.role, html: html.scrollWidth, body: body.scrollWidth, appRight: app.right });
        }
        const docs = await (await fetch('/static/stand/walkthrough/leasehold-rub/20.json')).json();
        S = migrate(Object.assign(load(), docs.state || {})); S.role = docs.role; S.open = docs.open; S.view = docs.view; S.tab = 'tasks'; render();
        const dealWithDocs = S.deals.find(x => x.id === S.open);
        S.doc = { id: dealWithDocs.id, k: 'inv' }; render();
        const documentWidth = document.querySelector('.pa')?.getBoundingClientRect().width || 0;
        const modalSnap = await (await fetch('/static/stand/walkthrough/leasehold-rub/01.json')).json();
        S = migrate(Object.assign(load(), modalSnap.state || {})); S.role = modalSnap.role; S.open = modalSnap.open; S.view = modalSnap.view;
        const d = S.deals.find(x => x.id === S.open);
        S.modal = { id: d.id, step: d.step, to: 'operator', delivery: 'pending' }; render();
        const modalWidth = document.querySelector('.modal')?.getBoundingClientRect().width || 0;
        return { failures, documentWidth, modalWidth, roleLayout, viewport: innerWidth,
          html: document.documentElement.scrollWidth, body: document.body.scrollWidth };
      });
      assert.deepEqual(sweep.failures, [], `${width}px viewport overflow: ${JSON.stringify(sweep.failures)}`);
      assert.ok(sweep.documentWidth > 0 && sweep.documentWidth <= width, `${width}px document width ${sweep.documentWidth}`);
      assert.ok(sweep.modalWidth > 0 && sweep.modalWidth <= width, `${width}px modal width ${sweep.modalWidth}`);
      assert.equal(sweep.html, width);
      assert.equal(sweep.body, width);
      assert.ok(sweep.roleLayout.railWidth >= width - 24, `${width}px role rail width ${sweep.roleLayout.railWidth}`);
      assert.ok(sweep.roleLayout.visibleButtonWidth >= 90, `${width}px role button width ${sweep.roleLayout.visibleButtonWidth}`);
      assert.equal(sweep.roleLayout.metaShrinkToFit, true);
      console.log(`${width}px: roles rail ${sweep.roleLayout.railWidth.toFixed(1)}px, first role ${sweep.roleLayout.visibleButtonWidth.toFixed(1)}px`);
    }
    // Scroll the real role rail and activate a role through its click handler.
    // SNAP makes setRole() render locally without a PUT.
    await page.evaluate(() => { standMe = 'admin'; S.role = 'manager'; S.modal = null; S.open = null; render(); });
    await page.evaluate(() => { const el = document.querySelector('#roles'); el.scrollLeft = el.scrollWidth; });
    assert.ok(await page.locator('#roles').evaluate(el => el.scrollLeft > 0), 'role rail did not scroll horizontally');
    await page.getByRole('button', { name: 'Фин дир' }).click();
    assert.equal(await page.evaluate(() => S.role), 'findir');
    assert.equal(await page.locator('#roles .rolebtn.on').innerText(), 'Фин дир');
    console.log('Role rail: horizontally scrolled and Фин дир activated by click');
    assert.deepEqual(writes, [], `unexpected mutating API calls: ${writes.join(', ')}`);
    await context.close();
    console.log('PASS: prod/stand mobile navigation, five slots, Deals active state, /tasks link, 21 synthetic frames at 375/390/430px, documents and modal widths; no API writes');
  } finally {
    await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
}

main().catch(err => { console.error(err); process.exitCode = 1; });
