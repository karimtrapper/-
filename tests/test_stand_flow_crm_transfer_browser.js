// Real browser smoke: task CRM draft keeps typed USDT through the close POST.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const {chromium} = require('playwright');

const root = path.resolve(__dirname, '..');
const source = JSON.parse(fs.readFileSync(path.join(root,
  'static/stand/walkthrough/leasehold-rub/01.json'), 'utf8')).state.deals[0];
const hash = 'a'.repeat(64);
const card = {...source, id:9041, code:'СД-9041', type:'Обмен валюты', kind:'',
  step:'s27', closed:false, sentToClient:true, client:'Flow browser',
  manager:'Елизавета', managerUserId:11, payType:'По реквизитам',
  rubIsNet:true, rubReceivingAccount:{mode:'flowsole'}, amountRub:40000,
  amountUsdt:400, rates:{broker:100}, payinParts:[], payinExtra:[],
  payinHashes:[{hash,network:'TRC20',amount:500}], paySrc:'cash',
  payout:{usdt:350,thb:10000}, crmEdit:{}};
const mime = {'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8',
  '.css':'text/css; charset=utf-8'};
const server = http.createServer((req,res) => {
  const name = new URL(req.url,'http://localhost').pathname;
  const target = name === '/tasks' ? 'static/stand/tasks.html'
    : name === '/crm' ? 'static/crm/crm.html'
      : name.startsWith('/tasks/') ? 'static/stand/' + name.slice(7) : name.slice(1);
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
  const origin=`http://127.0.0.1:${server.address().port}`;
  const browser=await chromium.launch({headless:true,
    executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH||undefined});
  try {
    const page=await browser.newPage();
    const requests=[],errors=[];
    page.on('pageerror',error=>errors.push(error.message));
    await page.route('**/*',route=>new URL(route.request().url()).origin===origin
      ?route.continue():route.abort());
    await page.route('**/api/**',route=>{
      const url=new URL(route.request().url());
      if(url.pathname==='/api/stand/deals/9041/crm-close'){
        requests.push(route.request().postDataJSON());
        route.fulfill({status:409,contentType:'application/json',
          body:JSON.stringify({success:false,error:'payin_amount_mismatch'})});return;
      }
      const data={
        '/api/auth/me':{success:true,user:{id:1,role:'admin',stand:true,
          display_name:'Test admin',username:'test'}},
        '/api/admins':{success:true,admins:[{id:11,username:'marina',
          display_name:'Елизавета',role:'manager',login_disabled:false}]},
        '/api/stand/state':{success:true,version:1,data:{deals:[card]}},
        '/api/managers':{success:true,managers:[{id:null,user_id:11,
          name:'Елизавета',account:'marina',active:true}]},
        '/api/wallets':{success:true,wallets:[]},
        '/api/clients':{success:true,clients:[]},
        '/api/referrers':{success:true,referrers:[]},
      }[url.pathname]||{success:true,data:{},incomes:[],txs:[]};
      route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)});
    });
    await page.goto(origin+'/tasks',{waitUntil:'domcontentloaded'});
    await page.waitForFunction(()=>typeof crmDraftMount==='function'&&S.deals?.some(d=>d.id===9041));
    await page.evaluate(()=>{STAND_EMPLOYEES=[{id:11,username:'marina',
      display_name:'Елизавета',role:'manager',login_disabled:false}];S.edit=9041;render();});
    await page.waitForFunction(()=>document.getElementById('crmDraftHost')?.shadowRoot
      ?.getElementById('managerSelect')?.options.length>0,null,{timeout:10000}).catch(async error=>{
      const state=await page.evaluate(()=>({edit:S.edit,host:document.getElementById('crmDraftHost')?.textContent?.slice(0,100),
        shadow:!!document.getElementById('crmDraftHost')?.shadowRoot,
        select:document.getElementById('crmDraftHost')?.shadowRoot?.getElementById('managerSelect')?.outerHTML?.slice(0,300)}));
      throw new Error(error.message+' '+JSON.stringify({state,errors}));
    });
    const draft=await page.evaluate(()=>{
      const root=document.getElementById('crmDraftHost').shadowRoot;
      return {rub:root.querySelector('[name="payin_amount_rub"]').value,
        usdt:root.querySelector('[name="payin_amount_usdt"]').value,
        method:root.getElementById('payinMethod').value};
    });
    assert.equal(draft.rub,'40000');
    assert.equal(draft.usdt,'400');
    assert.equal(draft.method,'flow_sole_reqs');
    const saved=await page.evaluate(()=>crmDraftCommit(9041));
    assert.notEqual(saved,false,'draft form must save');
    await page.evaluate(()=>{S.edit=null;window.crmGaps=()=>[];
      window.standRequireSaved=async()=>true;render();});
    await page.evaluate(()=>crmPushClose(9041,1));
    assert.equal(requests.length,1,errors.join('\n'));
    assert.equal(requests[0].crm.payin_amount_usdt,400);
    assert.equal(requests[0].crm.payin_tx_hashes[0].amount_usdt,500);
    assert.equal(await page.evaluate(()=>deal(9041).closed),false);
    assert.deepEqual(errors,[]);
    console.log('stand Flow Sole CRM browser transfer: PASS');
  } finally {await browser.close();server.close();}
})().catch(error=>{console.error(error);process.exitCode=1;server.close();});
