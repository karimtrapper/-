// Document review is local navigation; only relevant file changes reset it.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const html=fs.readFileSync('static/stand/tasks.html','utf8');
const source=name=>html.match(new RegExp('^function '+name+'\\([^]*?^}','m'))[0];
const block=html.slice(html.indexOf('  s27:()=>{'),html.indexOf('  }[d.step];',html.indexOf('  s27:()=>{'))).trim();
const card='function renderS27(){return ('+block.slice('s27:'.length,-1)+')();}';
const file=(id,name)=>({id,storageId:id,file:name,mime:'application/pdf',bytes:100,
  data:'__detached__',size:'1 КБ',sha256:id});
const ctx={d:{id:12,step:'s27',type:'Оплата недвижимости',kind:'Фрихолд',autoPayment:true,
  invoiceUsd:12000,payTo:{dev:'Seller <Co>',amount:999},pay:{tx:'out'},rates:{client:80,broker:80},
  payinHashes:[{hash:'in'}],sentToClient:false,log:[],files:{
    payment_order:[file('pp','order.pdf')],receipt:[file('swift','swift.pdf')],
    additional:[{...file('swift2','swift-extra.pdf'),documentType:'receipt'}]}},
  S:{role:'manager'},ap:{thb:999999},standVer:7,standBusy:false,standSaveScheduled:false,standClosing:false,
  htmlText:s=>String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'),
  usd:n=>'$'+n,money:(n,c)=>n+' '+c,isCrypto:()=>false,sendList:()=>[],
  filesOf:(d,k)=>d.files[k]||[],crmClosePanel:()=>'<div>close status recovery</div>',
  crmGaps:()=>[],crmGapsBlock:()=>'',crmClosePendingGet:()=>null,
  crmCloseReadiness:()=>{ctx.checks++;return {ready:true};},
  dealSummaryBlock:()=>'<div>summary</div>',
  crmForm:d=>{ctx.forms++;return '<input id="crm_client_name" value="'+(d.crmEdit?.client_name||'')+'">';},
  checks:0,forms:0,focused:[],document:{getElementById:id=>({focus:()=>ctx.focused.push(id),scrollIntoView:()=>{}})},
};
ctx.deal=id=>id===ctx.d.id?ctx.d:null;
ctx.render=()=>{ctx.markup=ctx.renderS27();};
vm.createContext(ctx);
vm.runInContext('const S27_DOCUMENT_REVIEW=new Map();\n'+
  ['isNativeCashPartner','receiptDocs','s27ReviewState','s27ReviewNavigate','s27ReviewDocuments'].map(source).join('\n')+card,ctx);

ctx.render();
assert.match(ctx.markup,/Платёжное поручение \/ чек/);
assert.match(ctx.markup,/SWIFT \/ MT103/);
assert.match(ctx.markup,/\$12000/);assert.doesNotMatch(ctx.markup,/999999|999 ฿/);
assert.match(ctx.markup,/Seller &lt;Co&gt;/);
for(const [kind,index] of [['payment_order',0],['receipt',0],['additional',0]]){
  assert.ok(ctx.markup.includes(`docOpen(12,'${kind}',${index})`));
  assert.ok(ctx.markup.includes(`docDownload(12,'${kind}',${index})`));
}
assert.equal(ctx.forms,0);assert.equal(ctx.checks,0,'review screen does not mount closing checks/form');
assert.doesNotMatch(ctx.markup,/crmPushClose|crm_client_name/);
assert.match(ctx.markup,/close status recovery/,'pending recovery/errors remain available');
const before=JSON.stringify(ctx.d);
ctx.s27ReviewNavigate(12,true);
assert.equal(JSON.stringify(ctx.d),before,'navigation does not mutate board or sentToClient');
assert.equal(ctx.d.sentToClient,false);
assert.equal(ctx.focused.at(-1),'s27-close-12');
assert.match(ctx.markup,/crmPushClose\(12,7\)/,'existing final close handler is retained');

// Polling creates new objects and changes logs/version; neither resets review or edits.
ctx.d=structuredClone(ctx.d);ctx.d.log.push({text:'unrelated update'});ctx.standVer=8;
ctx.d.crmEdit={client_name:'Draft client'};ctx.render();
assert.match(ctx.markup,/value="Draft client"/);assert.match(ctx.markup,/crmPushClose\(12,8\)/);
ctx.d.files.additional.push({...file('other','other.pdf'),documentType:'other'});ctx.render();
assert.match(ctx.markup,/crm_client_name/,'unrelated attachments do not reset review');
ctx.s27ReviewNavigate(12,false);
assert.equal(ctx.focused.at(-1),'s27-documents-12');assert.doesNotMatch(ctx.markup,/crm_client_name/);
ctx.s27ReviewNavigate(12,true);assert.match(ctx.markup,/value="Draft client"/,'back/forward retains draft');
let changed=0;
const editedControl={tagName:'INPUT',value:'Typed client',defaultValue:'Draft client',
  closest:()=>true,onchange(){changed++;ctx.d.crmEdit.client_name=this.value;ctx.render();},
  blur(){ctx.document.activeElement=null;this.onchange();}};
ctx.document.activeElement=editedControl;
ctx.s27ReviewNavigate(12,false);
assert.equal(changed,1,'typed edit uses existing onchange before navigation');
assert.doesNotMatch(ctx.markup,/crm_client_name/,'first navigation completes despite onchange rerender');
editedControl.value=editedControl.defaultValue='Typed client';ctx.document.activeElement=editedControl;
ctx.s27ReviewNavigate(12,true);
assert.equal(changed,1,'unchanged focused field causes no save');
assert.match(ctx.markup,/value="Typed client"/);
ctx.document.activeElement=null;

ctx.d.files.additional.push({...file('new','new-swift.pdf'),documentType:'receipt'});ctx.render();
assert.doesNotMatch(ctx.markup,/crmPushClose|crm_client_name/,'new SWIFT returns to document review');
ctx.s27ReviewNavigate(12,true);ctx.d.files.payment_order[0].sha256='replaced';ctx.render();
assert.doesNotMatch(ctx.markup,/crmPushClose/,'replaced payment document resets review');
ctx.d.files.payment_order=[];ctx.render();ctx.s27ReviewNavigate(12,true);
assert.match(ctx.markup,/crmPushClose/,'legacy case does not require optional payment order');
ctx.s27ReviewNavigate(12,false);ctx.S.role='admin';ctx.render();
assert.doesNotMatch(ctx.markup,/crmPushClose/,'admin sees the same review sequence');
ctx.S.role='operator';const operatorBefore=ctx.markup;ctx.s27ReviewNavigate(12,true);
assert.equal(ctx.markup,operatorBefore,'review navigation does not grant operator closing access');
ctx.S.role='manager';ctx.d.kind='Лизхолд';ctx.d.autoPayment=false;ctx.render();
assert.match(ctx.markup,/crmPushClose/,'leasehold keeps its existing closing flow');
assert.doesNotMatch(ctx.markup,/s27ReviewNavigate/);
console.log('s27 document review: files, local navigation, polling/draft retention, change reset, roles and legacy PASS');
