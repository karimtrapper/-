// Open the actual task-board CRM form in a browser. API fixtures stay local.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const {chromium} = require('playwright');

const root = path.resolve(__dirname, '..');
const card = JSON.parse(fs.readFileSync(path.join(root,
  'static/stand/walkthrough/leasehold-rub/01.json'), 'utf8')).state.deals[0];
const mime = {'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8',
  '.css':'text/css; charset=utf-8','.json':'application/json; charset=utf-8'};
const server = http.createServer((req,res) => {
  const name = new URL(req.url,'http://localhost').pathname;
  const target = name === '/tasks' ? 'static/stand/tasks.html'
    : name === '/crm' ? 'static/crm/crm.html'
      : name.startsWith('/tasks/') ? 'static/stand/' + name.slice(7)
        : name.slice(1);
  const file = path.resolve(root,target);
  if (!file.startsWith(root + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
    res.writeHead(404).end('not found');return;
  }
  res.writeHead(200,{'content-type':mime[path.extname(file)]||'application/octet-stream'});
  fs.createReadStream(file).pipe(res);
});

(async () => {
  await new Promise(ok => server.listen(Number(process.env.CALCCRM_FENCE_PORT_START)||0,
    '127.0.0.1',ok));
  const origin = `http://127.0.0.1:${server.address().port}`;
  const browser = await chromium.launch({headless:true,
    executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH||undefined});
  try {
    const page = await browser.newPage();
    const errors = [];
    const historical = {...card,id:1483,code:'СД-1483',step:'s27',payType:'По реквизитам',
      rubIsNet:true,rubReceivingAccount:{mode:'flowsole'},amountRub:98500,
      amountUsdt:1231.25,manager:'Старое имя',managerUserId:null,
      _managerDraft:{files:{inv:[{uploadedById:11}],ipds:[{uploadedById:11}]}}};
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/*', route => new URL(route.request().url()).origin===origin
      ? route.continue() : route.abort());
    await page.route('**/api/**', route => {
      const url = new URL(route.request().url());
      const responses = {
        '/api/auth/me':{success:true,user:{id:1,role:'admin',stand:true,
          display_name:'Тестовый админ',username:'test'}},
        '/api/admins':{success:true,admins:[{id:11,username:'marina',
          display_name:'Елизавета',role:'manager',login_disabled:false}]},
        '/api/stand/state':{success:true,version:1,data:{deals:[historical]}},
        '/api/managers':{success:true,managers:[{id:null,user_id:11,
          name:'Елизавета',account:'marina',active:true}]},
        '/api/wallets':{success:true,wallets:[{id:7,label:'Обменный',
          address:'T123456789012345678901234567890123',purpose:'exchange',
          accepts_payin:true,not_for_new_deals:false,initiator_roles:['operator'],
          confirmer_roles:['findir'],limit_usd:10000,active:true}]},
        '/api/clients':{success:true,clients:[]},
        '/api/referrers':{success:true,referrers:[]},
        '/api/sber-incomes':{success:true,incomes:[]},
        '/api/rates':{success:true},
      };
      const payload = responses[url.pathname] || {success:true,txs:[],data:{}};
      route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(payload)});
    });
    await page.goto(origin+'/tasks',{waitUntil:'domcontentloaded'});
    await page.waitForFunction(() => typeof render==='function' && typeof crmDraftMount==='function' &&
      S.deals?.some(d=>d.id===1483));
    await page.evaluate(() => {S.edit=1483;S.open=null;S.draft=null;
      S.manualCloseDraft={};S.manualCloseForm={};STAND_EMPLOYEES=[{id:11,
        username:'marina',display_name:'Елизавета',role:'manager',login_disabled:false}];render();});
    await page.waitForFunction(() => {
      const root=document.getElementById('crmDraftHost')?.shadowRoot;
      return root?.getElementById('managerSelect')?.options.length > 0;
    },null,{timeout:10000}).catch(async error => {
      const state=await page.evaluate(() => ({host:document.getElementById('crmDraftHost')?.textContent,
        shadow:!!document.getElementById('crmDraftHost')?.shadowRoot,
        optionCount:document.getElementById('crmDraftHost')?.shadowRoot?.getElementById('managerSelect')?.options.length,
        edit:S.edit,deals:S.deals?.length,found:!!deal(S.edit),
        app:document.getElementById('app')?.textContent?.slice(0,120)}));
      throw new Error(error.message+' '+JSON.stringify({state,errors}));
    });
    const flow = await page.evaluate(() => {
      const root=document.getElementById('crmDraftHost').shadowRoot;
      return {manager:root.getElementById('managerSelect').value,
        rub:root.querySelector('[name="payin_amount_rub"]').value,
        hint:root.getElementById('payinRubHint').textContent,
        method:root.getElementById('payinMethod').value,
        walletOptions:root.getElementById('payinWalletSelect').options.length};
    });
    assert.equal(flow.manager,'user:11');
    assert.equal(flow.rub,'98500');
    assert.equal(flow.hint,'после комиссии банка');
    assert.equal(flow.method,'flow_sole_reqs');
    assert.equal(flow.walletOptions,2);
    await page.evaluate(() => {
      const root=document.getElementById('crmDraftHost').shadowRoot;
      const method=root.getElementById('payinMethod');
      method.value='crypto_direct';method.dispatchEvent(new Event('change',{bubbles:true}));
      const payinWallet=root.getElementById('payinWalletSelect');
      payinWallet.value='7';payinWallet.dispatchEvent(new Event('change',{bubbles:true}));
    });
    const wallet = await page.evaluate(() => {
      const root=document.getElementById('crmDraftHost').shadowRoot;
      return {selected:root.getElementById('payinWalletSelect').value,
        policy:root.getElementById('payinWalletPolicy').textContent,
        address:root.getElementById('payinWalletAddress').textContent};
    });
    assert.equal(wallet.selected,'7');
    assert.match(wallet.policy,/Обменный.*операционист.*финансист.*10/);
    assert.match(wallet.address,/T12345678/);
    await page.evaluate(() => {
      S.deals.push({...S.deals[0],id:1484,code:'СД-1484',manualNew:true,
        type:'Обмен валюты',kind:'',payType:'Крипта',rubReceivingAccount:null,managerUserId:11,
        _managerDraft:{files:{}}});
      S.edit=1484;render();
    });
    await page.waitForFunction(() => {
      const root=document.getElementById('crmDraftHost')?.shadowRoot;
      return root?.getElementById('managerSelect')?.value==='user:11' &&
        root?.getElementById('payinWalletSelect')?.value==='7';
    },null,{timeout:10000}).catch(async error => {
      const state=await page.evaluate(() => {
        const root=document.getElementById('crmDraftHost')?.shadowRoot;
        return {host:document.getElementById('crmDraftHost')?.textContent?.slice(0,150),
          manager:root?.getElementById('managerSelect')?.value,
          wallet:root?.getElementById('payinWalletSelect')?.value,
          walletOptions:[...(root?.getElementById('payinWalletSelect')?.options||[])].map(o=>o.value),
          manualNew:deal(S.edit)?.manualNew,
          method:root?.getElementById('payinMethod')?.value,
          policy:root?.getElementById('payinWalletPolicy')?.textContent,
          edit:S.edit};
      });
      throw new Error(error.message+' '+JSON.stringify({state,errors}));
    });
    const newPolicy=await page.evaluate(() =>
      document.getElementById('crmDraftHost').shadowRoot.getElementById('payinWalletPolicy').textContent);
    assert.match(newPolicy,/Обменный.*операционист.*финансист.*10/);
    assert.ok(!errors.some(x => /refreshPayinWalletPolicy|syncNewPayinWalletDefault/.test(x)),errors.join('\n'));
    console.log('stand CRM draft mount: Flow Sole, manager account, existing/new wallet policy PASS');
  } finally {await browser.close();server.close();}
})().catch(error => {console.error(error);process.exitCode=1;server.close();});
