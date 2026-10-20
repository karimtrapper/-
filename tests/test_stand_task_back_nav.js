// Read-only browser regression for the mobile task-card navigation.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const { chromium, devices } = require('playwright');

const root = path.resolve(__dirname, '..');
const mime = { '.html':'text/html', '.js':'text/javascript', '.css':'text/css', '.json':'application/json' };
const server = http.createServer((req, res) => {
  const pathname = new URL(req.url, 'http://localhost').pathname;
  if (pathname === '/crm') { res.writeHead(200, { 'content-type':'text/html' }).end('<a href="/tasks">Tasks</a>'); return; }
  if (pathname.startsWith('/api/')) { res.writeHead(404, { 'content-type':'application/json' }).end('{}'); return; }
  const rel = pathname === '/tasks' ? 'static/stand/tasks.html'
    : pathname.startsWith('/tasks/') ? `static/stand/${pathname.slice(7)}`
      : pathname.startsWith('/walkthrough/') ? `static/stand/${pathname.slice(1)}` : pathname.slice(1);
  const file = path.resolve(root, rel);
  if (!file.startsWith(root + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
    res.writeHead(404).end('not found'); return;
  }
  res.writeHead(200, { 'content-type':mime[path.extname(file)] || 'application/octet-stream' });
  fs.createReadStream(file).pipe(res);
});

async function main() {
  await new Promise(resolve => server.listen(Number(process.env.CALCCRM_FENCE_PORT_START) || 0, '127.0.0.1', resolve));
  const base = `http://127.0.0.1:${server.address().port}`;
  let browser;
  try {
    browser = await chromium.launch({ headless:true, executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || undefined });
    const context = await browser.newContext({ ...devices['iPhone 15'], viewport:{ width:375, height:812 } });
    const page = await context.newPage();
    await page.goto(`${base}/crm`);
    await page.goto(`${base}/tasks?snap=walkthrough/leasehold-rub/01.json`);
    await page.waitForFunction(() => typeof S !== 'undefined' && S.deals?.length > 0);
    await page.evaluate(() => {
      const original = S.deals[0];
      S.deals = Array.from({ length:20 }, (_, index) => {
        const d = structuredClone(original);
        d.id = 1472 + index; d.code = `СД-${d.id}`; d.client = `Клиент ${index}`;
        d.kind = index % 2 ? 'Фрихолд' : 'Лизхолд';
        return d;
      });
      S.open = null; S.role = 'admin'; S.tab = 'tasks'; S.manualCloseDraft = {}; S.manualCloseForm = {};
      render(); showTaskListSection('all'); setTaskDealFilter('leasehold');
      NavShell.mount({ stand:true, page:'tasks', active:'tasks', section:'tasks', role:'admin', name:'QA', count:0 });
      scrollTo(0, 520);
    });
    await page.waitForFunction(() => scrollY > 100);
    const before = await page.evaluate(() => ({
      scroll:scrollY, filter:taskDealFilter, section:taskListSection, role:S.role,
      ids:[...document.querySelectorAll('.task-list-panel.on [data-task-id]')].map(el => Number(el.dataset.taskId))
    }));
    assert.equal(before.filter, 'leasehold');
    assert.equal(before.section, 'all');
    assert.equal(before.ids.length, 10);

    const baseHistoryLength = await page.evaluate(() => history.length);
    await page.locator('.task-list-panel.on [data-task-id]').nth(5).click();
    assert.equal(await page.evaluate(() => S.open), before.ids[5]);
    assert.equal(await page.evaluate(() => history.state?.__calccrmTaskCard), true);
    assert.equal(await page.evaluate(() => history.length), baseHistoryLength + 1);
    for (const [width, mobile] of [[699,true], [700,true], [701,false], [767,false], [768,false]]) {
      await page.setViewportSize({ width, height:812 });
      const shown = await page.evaluate(() => ({
        mobile:getComputedStyle(document.querySelector('.task-card-nav')).display !== 'none',
        breadcrumb:getComputedStyle(document.querySelector('.deal-breadcrumb')).display !== 'none'
      }));
      assert.deepEqual(shown, { mobile, breadcrumb:!mobile }, `${width}px navigation boundary`);
    }
    await page.setViewportSize({ width:375, height:812 });
    await page.getByRole('button', { name:'Следующая задача ›' }).click();
    assert.equal(await page.evaluate(() => S.open), before.ids[6]);
    assert.equal(await page.evaluate(() => history.state?.__calccrmTaskCard), true);
    assert.equal(await page.evaluate(() => history.length), baseHistoryLength + 1);
    for (let index = 7; index < before.ids.length; index++) {
      await page.getByRole('button', { name:'Следующая задача ›' }).click();
      assert.equal(await page.evaluate(() => S.open), before.ids[index]);
    }
    assert.equal(await page.getByRole('button', { name:'Следующая задача ›' }).isDisabled(), true);
    await page.getByRole('button', { name:'‹ Все задачи' }).click();
    await page.waitForFunction(() => S.open === null);
    await page.waitForFunction(expected => Math.abs(scrollY - expected) <= 2, before.scroll);
    const returned = await page.evaluate(() => ({ scroll:scrollY, filter:taskDealFilter, section:taskListSection, role:S.role }));
    assert.deepEqual({ ...returned, scroll:before.scroll }, { scroll:before.scroll, filter:before.filter, section:before.section, role:before.role });
    assert.ok(Math.abs(returned.scroll - before.scroll) <= 2, `scroll ${returned.scroll} vs ${before.scroll}`);

    await page.setViewportSize({ width:768, height:812 });
    await page.locator('.task-list-panel.on [data-task-id]').nth(5).click();
    assert.equal(await page.evaluate(() => history.state?.__calccrmTaskCard), undefined);
    assert.equal(await page.locator('.deal-breadcrumb').evaluate(el => getComputedStyle(el).display), 'block');
    await page.evaluate(() => back());
    await page.setViewportSize({ width:375, height:812 });

    await page.locator('.task-list-panel.on [data-task-id]').nth(5).click();
    await page.locator('.site-shell-mobile-head a[href="/tasks"]').tap();
    await page.waitForFunction(() => S.open === null);
    assert.equal(await page.evaluate(() => history.state?.__calccrmTaskCard), undefined);
    await page.locator('.task-list-panel.on [data-task-id]').nth(5).click();
    const autoScroll = await page.evaluate(() => taskListScrollY);
    await page.evaluate(() => { S.open = null; render(); });
    await page.waitForFunction(() => S.open === null && !history.state?.__calccrmTaskCard);
    await page.waitForFunction(expected => Math.abs(scrollY - expected) <= 2, autoScroll);
    await page.locator('.task-list-panel.on [data-task-id]').nth(5).click();
    await page.setViewportSize({ width:768, height:812 });
    await page.evaluate(() => back());
    await page.waitForFunction(() => S.open === null && !history.state?.__calccrmTaskCard);
    await page.setViewportSize({ width:375, height:812 });
    await page.locator('.task-list-panel.on [data-task-id]').nth(5).click();
    await page.goBack();
    await page.waitForFunction(() => S.open === null);
    await page.goBack();
    await page.waitForURL(`${base}/crm`);
    await context.close();
    console.log('PASS mobile task back nav: history, scroll, filter, next, header tap, 699/700/701/767/768px');
  } finally {
    if (browser) await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
