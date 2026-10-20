// The late visual formatter must keep 400 USDT as 400 in the new proof note.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {chromium} = require('playwright');

const html = fs.readFileSync('static/crm/crm.html', 'utf8');
const formatter = fs.readFileSync('static/visual-format.js', 'utf8');
const match = html.match(/^        function flowPayinProofMarkup\([^]*?^        }/m);
assert.ok(match, 'CRM proof label function');

(async () => {
  const browser = await chromium.launch({headless:true,
    executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH||undefined});
  try {
    const page = await browser.newPage();
    await page.setContent('<div id="proof"></div>');
    await page.addScriptTag({content:formatter});
    await page.addScriptTag({content:match[0]});
    await page.evaluate(() => {
      document.getElementById('proof').innerHTML = flowPayinProofMarkup({
        payin_method:'flow_sole_reqs',payin_rub_is_net:true,status:'pending',
        payin_confirmation:{status:'mismatch',declared_usdt:400,network_usdt:500}});
    });
    await page.waitForFunction(() => document.getElementById('proof').textContent.includes('400,00 USDT'));
    const shown = await page.locator('#proof').textContent();
    assert.match(shown, /введено 400,00 USDT, в сети 500,00 USDT/);
    assert.doesNotMatch(shown, /40\s?000/);
    console.log('CRM Flow Sole proof display: PASS');
  } finally {await browser.close();}
})().catch(error => {console.error(error);process.exitCode=1;});
