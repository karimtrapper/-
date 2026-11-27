// Browser regression for the stand-only mobile CRM entry and task layout.
// Uses the workspace Playwright install and serves only local static files.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const { chromium, webkit, devices } = require('playwright');

const root = path.resolve(__dirname, '..');
// Shared navigation now loads external CSS; browsers reject octet-stream stylesheets.
const mime = { '.html': 'text/html; charset=utf-8', '.json': 'application/json; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8' };
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
  await new Promise(resolve => server.listen(Number(process.env.CALCCRM_FENCE_PORT_START)||0, '127.0.0.1', resolve));
  const base = `http://127.0.0.1:${server.address().port}`;
  const browserType = process.env.BROWSER === 'webkit' ? webkit : chromium;
  const browser = await browserType.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH||undefined });
  let apiMode = 'prod';
  let sessionRole = 'admin';
  const snapshot = JSON.parse(fs.readFileSync(path.join(root, 'static/stand/walkthrough/leasehold-rub/01.json'), 'utf8')).state;
  const fixture = { ...snapshot, deals: Array.from({length: 9}, (_, index) => ({
    ...snapshot.deals[0], id: 1500 + index, code: 'СД-' + (1500 + index),
    step: 's4', client: 'Тестовый клиент ' + (index + 1),
    manager: index % 2 ? 'Марина' : 'Ирина',
  })) };
  const writes = [];
  try {
    const context = await browser.newContext({ ...devices['iPhone 13'], isMobile:true, hasTouch:true });
    const page = await context.newPage();
    await page.route('**/*', route => new URL(route.request().url()).origin === base ? route.continue() : route.abort());
    await page.setViewportSize({ width: 375, height: 812 });
    await page.route('**/api/**', async route => {
      const req = route.request();
      const url = new URL(req.url());
      // crm-preview uses POST for a read-only calculation; still abort it locally.
      if (req.method() !== 'GET' && req.method() !== 'HEAD' && url.pathname !== '/api/stand/crm-preview') {
        writes.push(`${req.method()} ${req.url()}`); await route.abort(); return;
      }
      if (url.pathname === '/api/stand/crm-preview') { await route.abort(); return; }
      let status = 404, data = { success: false };
      if (url.pathname === '/api/auth/me') {
        status = 200; data = { success: true, user: { stand: apiMode === 'stand', tasks_enabled: apiMode === 'working', role: sessionRole } };
      } else if (url.pathname === '/api/stand/roles' && apiMode === 'stand') {
        status = 200; data = { success: true, roles: { manager: 'Менеджер', operator: 'Операционист' } };
      } else if (url.pathname === '/api/stand/state') {
        status = 200; data = { success: true, version: 1, role: sessionRole, data: apiMode === 'working' ? fixture : {} };
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

    // Stand now mounts the shared four-link shell; the legacy five-slot bar is hidden.
    apiMode = 'stand';
    await page.reload();
    await page.waitForFunction(() => document.body.classList.contains('nav-shell-on'));
    nav = await page.evaluate(() => ({
      visible: [...document.querySelectorAll('.site-shell-bottom [data-shell-link]')]
        .filter(el => getComputedStyle(el).display !== 'none').length,
      tasks: document.querySelector('.site-shell-bottom [data-shell-link="tasks"]').getAttribute('href'),
      active: document.querySelector('.site-shell-bottom [aria-current="page"]')?.dataset.shellLink,
      legacy: getComputedStyle(document.querySelector('#bottomNav')).display,
    }));
    assert.deepEqual(nav, { visible: 4, tasks: '/tasks', active: 'crm', legacy: 'none' });
    const crmLayout = await page.evaluate(() => ({
      viewport: innerWidth,
      html: document.documentElement.scrollWidth,
      body: document.body.scrollWidth,
      nav: document.querySelector('.site-shell-bottom').getBoundingClientRect().width,
      viewportMeta: document.querySelector('meta[name="viewport"]').content,
    }));
    assert.deepEqual(crmLayout, { viewport: 375, html: 375, body: 375, nav: 375,
      viewportMeta: 'width=device-width, initial-scale=1.0, shrink-to-fit=no' });
    await page.locator('.site-shell-sections [data-shell-section="documents"]').click();
    assert.equal(await page.locator('.site-shell-sections [data-shell-section="documents"]').getAttribute('aria-current'), 'page');
    await Promise.all([
      page.waitForURL(url => url.origin === base && url.pathname === '/tasks', {timeout: 10000}),
      page.locator('.site-shell-bottom [data-shell-link="tasks"]').tap(),
    ]);
    assert.equal(new URL(page.url()).search, '');
    apiMode = 'working';
    for (const width of [390, 1440]) {
      await page.setViewportSize({width, height: 844});
      await page.goto(`${base}/tasks`);
      const rows = page.locator('.task-list-panel[data-section="mine"] .task-list-row');
      await rows.first().waitFor();
      assert.equal(await rows.count(), 9);
      const profile = page.locator('.slate-user');
      const drawer = page.locator('.slate-drawer');
      const drawerTrigger = page.locator('[data-slate-sidebar]');
      async function openProfile() {
        if (width < 768) await drawerTrigger.click();
        await profile.locator('summary').click();
      }
      await openProfile();
      assert.equal(await profile.locator('[data-shell-admin-tools]').count(), 0);
      await profile.getByRole('button', {name: 'Менеджер'}).click();
      assert.match(await page.locator('.task-preview-status').innerText(), /Менеджер/);
      assert.equal(await rows.count(), 9);
      assert.equal(await page.locator('.task-list-create').count(), 0);
      await rows.first().click();
      await page.locator('.deal-head').waitFor();
      assert.equal(await page.locator('.deal-screen .btn[onclick]:not(.task-card-nav button, .branch-tabs button)').count(), 0);
      await openProfile();
      await profile.getByRole('button', {name: 'Операционист'}).click();
      await page.getByText('Просмотр · Операционист').waitFor();
      assert.equal(await rows.count(), 0);
      await openProfile();
      await profile.getByRole('button', {name: /Все задачи/}).click();
      assert.equal(await page.locator('.task-preview-status').count(), 0);
      assert.equal(await rows.count(), 9);
      if (width < 768) await drawerTrigger.click();
      assert.equal(await page.locator('.slate-side-nav .site-shell-count').innerText(), '9');
      assert.equal(await page.locator('.slate-side-nav [role="group"]').count(), 2);
      assert.equal(await page.locator('.slate-side-nav a').count(), 8);
      if (width < 768) {
        await page.keyboard.press('Escape');
        assert.equal(await drawer.isVisible(), false);
        assert.equal(await drawerTrigger.evaluate(el => document.activeElement === el), true);
      }

      await page.goto(`${base}/crm?section=documents`);
      const active = page.locator('.slate-side-nav [aria-current="page"]');
      await page.locator('.slate-topbar [aria-current="page"]').waitFor();
      assert.equal(await active.getAttribute('data-slate-route'), 'documents');
      const colors = await active.evaluate(el => ({
        color: getComputedStyle(el).color, background: getComputedStyle(el).backgroundColor,
      }));
      assert.notEqual(colors.color, colors.background);
      await page.keyboard.press('Control+k');
      const palette = page.locator('.slate-palette');
      const search = palette.getByRole('searchbox');
      await search.waitFor();
      assert.equal(await search.evaluate(el => document.activeElement === el), true);
      for (const key of ['dashboard','analytics','payoutRequests','admins']) {
        assert.equal(await palette.locator(`[data-slate-route="${key}"]`).count(), 1);
      }
      await search.fill('сверка');
      await search.press('ArrowDown');
      await page.keyboard.press('Enter');
      await page.locator('#verification.active').waitFor();
      assert.equal(await palette.isVisible(), false);
      const openSearch = page.locator('[data-slate-search]');
      await openSearch.click();
      await search.fill('Раздел, которого нет');
      await palette.getByText('Ничего не найдено', {exact:true}).first().waitFor();
      await search.press('Escape');
      await palette.waitFor({state:'hidden'});
      await page.waitForFunction(() => document.activeElement.matches('[data-slate-search]'));

      if (width >= 768) {
        await drawerTrigger.click();
        assert.equal(await page.locator('html').getAttribute('data-sidebar'), 'rail');
      }
      const mode = page.locator('[data-slate-mode]');
      const initialMode = await page.locator('html').getAttribute('data-mode');
      await mode.click();
      const selectedMode = initialMode === 'dark' ? 'light' : 'dark';
      assert.equal(await page.locator('html').getAttribute('data-mode'), selectedMode);
      await page.getByLabel('Цветовая схема', { exact:true }).first().click();
      await page.getByRole('button',{name:'Tangerine'}).click();
      await page.reload();
      await page.locator('.slate-topbar').waitFor();
      assert.equal(await page.locator('html').getAttribute('data-mode'), selectedMode);
      assert.equal(await page.locator('html').getAttribute('data-preset'), 'tangerine');
      if (width >= 768) assert.equal(await page.locator('html').getAttribute('data-sidebar'), 'rail');
    }
    sessionRole = 'manager';
    await page.goto(`${base}/tasks`);
    await page.locator('.task-list-row').first().waitFor();
    assert.equal(await page.locator('[data-shell-roles]').count(), 0);
    assert.equal(await page.locator('.slate-side-nav [data-slate-route="dashboard"]').getAttribute('href'),
      '/crm?section=dashboard');
    sessionRole = 'admin';
    apiMode = 'stand';

    // Synthetic mode keeps actual role switching local: save() is disabled and
    // every server request remains read-only while exercising the real handlers.
    await page.goto(`${base}/tasks?snap=walkthrough/leasehold-rub/01.json`);
    await page.locator('#app .deal-head').waitFor({timeout: 10000});
    assert.equal(await page.getByText('Снимок шага не загрузился.').count(), 0);
    await page.evaluate(() => { standMe = 'admin'; render(); });
    await page.waitForFunction(() => document.querySelector('#roles .rolebtn'));

    // Use read-only walkthrough snapshots as synthetic deal data. Sweep every
    // role/step at the requested CSS widths, then a document card and bottom sheet.
    for (const width of [375, 390, 430]) {
      await page.setViewportSize({ width, height: 844 });
      const sweep = await page.evaluate(async () => {
        const snapshotState = snapshot => migrate({...load(), ...snapshot.state});
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
          S = snapshotState(snap);
          S.role = snap.role; S.open = snap.open; S.view = snap.view; S.tab = 'tasks'; S.modal = null; S.doc = null;
          render();
          const html = document.documentElement, body = document.body, app = document.querySelector('#app').getBoundingClientRect();
          if (html.scrollWidth !== innerWidth || body.scrollWidth !== innerWidth || app.right > innerWidth + 1)
            failures.push({ frame: i, role: snap.role, html: html.scrollWidth, body: body.scrollWidth, appRight: app.right });
        }
        const docs = await (await fetch('/static/stand/walkthrough/leasehold-rub/20.json')).json();
        S = snapshotState(docs); S.role = docs.role; S.open = docs.open; S.view = docs.view; S.tab = 'tasks'; render();
        const dealWithDocs = S.deals.find(x => x.id === S.open);
        S.doc = { id: dealWithDocs.id, k: 'inv' }; render();
        const documentWidth = document.querySelector('.pa')?.getBoundingClientRect().width || 0;
        const modalSnap = await (await fetch('/static/stand/walkthrough/leasehold-rub/01.json')).json();
        S = snapshotState(modalSnap); S.role = modalSnap.role; S.open = modalSnap.open; S.view = modalSnap.view;
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
    console.log('PASS: prod nav and stand shared shell, four stand links, /tasks link, 21 synthetic frames at 375/390/430px, documents and modal widths; no API writes');
  } finally {
    await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
}

main().catch(err => { console.error(err); process.exitCode = 1; });
