// S27 renders from server readiness and binds its sole close button to the shown version.
const assert=require('node:assert/strict'), fs=require('node:fs'), vm=require('node:vm');
const html=fs.readFileSync('static/stand/tasks.html','utf8');
const source=name=>html.match(new RegExp('^(?:async )?function '+name+'\\([^]*?^}','m'))[0];
const block=html.slice(html.indexOf('  s27:()=>{'),html.indexOf('  }[d.step];',html.indexOf('  s27:()=>{'))).trim();
const s27='function renderS27(){return ('+block.slice('s27:'.length,-1)+')();}';
const d={id:1487,step:'s27',type:'Оплата недвижимости',kind:'Лизхолд',payType:'Крипта',
  pay:{invoicePaid:true,tx:'outgoing'},rates:{client:30},payinHashes:[{hash:'incoming'}],
  files:{receipt:[{file:'receipt.pdf',size:'1 КБ'}]},sentToClient:true};
let status={version:7,missing:[],facts:['payin','payout','receipt','sent'].map(kind=>({kind,ready:true,
  system:kind!=='sent',checked_at:'2026-10-18T10:11:12Z'}))};
const ctx={d,ap:{thb:100},S:{role:'manager'},standVer:7,standBusy:false,standSaveScheduled:false,
  htmlText:String,filesOf:(d,k)=>d.files[k],receiptDocs:d=>d.files.receipt.map((f,i)=>({f,kind:'receipt',i})),isCrypto:()=>true,sendList:()=>[],
  money:(n,c)=>n+' '+c,crmGaps:()=>[],crmGapsBlock:()=>'',crmForm:()=>'',prepayCloseReason:()=>'',
  crmCloseStatus:()=>status};
vm.createContext(ctx);
vm.runInContext(['crmCloseReason','crmCloseBlockers','crmEvidenceParts'].map(source).join('\n')+s27,ctx);
ctx.dealSummaryBlock=d=>{const p=ctx.crmEvidenceParts(d,true);return p.payinBtn+p.payoutBtn+p.receiptBtn+p.sentBtn;};
let out=ctx.renderS27();
assert.equal((out.match(/onclick="crmPushClose/g)||[]).length,1);
assert.match(out,/<button class="btn btn-primary"\s+onclick="crmPushClose\(1487,7\)">Сохранить в CRM и закрыть/);
assert.doesNotMatch(out,/onclick="crmEvidence|onclick="sentToggle/);
assert.match(out,/проверено системой/);
assert.match(out,/18\.10\.2026/);
assert.equal((out.match(/Чек отправлен клиенту/g)||[]).length,1,'one sent status, no repeated attestation date');
status.facts[1]={kind:'payout',ready:false,reason:'network_payout_proof_missing'};
out=ctx.renderS27();
assert.match(out,/<button class="btn btn-primary" disabled onclick="crmPushClose/);
assert.equal((out.match(/Нет подтверждённого в сети хеша выплаты/g)||[]).length,1);
assert.match(out,/<div class="s27-close-warning" role="status">/);
assert.match(out,/<span class="s27-fact-pending">Не подтверждено<\/span>/);
const missingPayoutHtml=out;
status.facts[2]={kind:'receipt',ready:false,reason:'operator_receipt_acceptance_missing'};
const longReceiptStatus=ctx.crmEvidenceParts(d).receiptBtn;
status.facts[2]={kind:'receipt',ready:true,system:true,checked_at:'2026-10-18T10:11:12Z'};
status.facts[1]={kind:'payout',ready:true,system:true,checked_at:null};
out=ctx.renderS27();
assert.match(out,/дата проверки не сохранена/);
d.sentToClient=false;
status.facts[3]={kind:'sent',ready:false,reason:'sent_receipt_missing'};
out=ctx.renderS27();
assert.equal((out.match(/onclick="sentToggle/g)||[]).length,1);
assert.doesNotMatch(out,/onclick="crmEvidence/);
assert.match(out,/<button class="btn btn-primary" disabled onclick="crmPushClose/);
status={pending:true};
assert.match(ctx.renderS27(),/Проверяем факты закрытия на сервере/);
console.log('s27 single confirmation: readiness, timestamps, missing payout, sent once PASS');

// Real browser geometry: long missing proof labels must wrap at the requested mobile width.
(async()=>{
  const {chromium}=require('playwright');
  const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH||undefined});
  try {
    const page=await browser.newPage({viewport:{width:375,height:812}});
    await page.route('**/*',route=>route.abort());
    const styles=html.match(/<style>([\s\S]*?)<\/style>/)[1];
    await page.setContent('<style>'+styles+'</style>'+missingPayoutHtml+
      '<div class="card"><div class="sumrow"><div class="sumlab">Выплата</div><div class="sumval">'+longReceiptStatus+
      '</div><div class="sumsrc">подтверждение</div><span></span></div></div>');
    const size=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));
    assert.ok(size.scroll<=size.width,JSON.stringify(size));
    const status=await page.locator('.s27-fact-pending').last().evaluate(el=>getComputedStyle(el).whiteSpace);
    assert.equal(status,'normal');
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
