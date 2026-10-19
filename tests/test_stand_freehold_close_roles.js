// s27: менеджер закрывает, оператор подтверждает инвойс, админ видит обе задачи.
const assert=require('node:assert/strict'), fs=require('node:fs'), vm=require('node:vm');
const html=fs.readFileSync('static/stand/tasks.html','utf8');
function source(name){const m=html.match(new RegExp('^function '+name+'\\([^]*?^}','m'));assert.ok(m,name);return m[0];}
const ctx={S:{role:'operator',view:'task'},STEPS:{s27:{title:'Закрытие',n:27}},
 ROLES:{manager:{t:'Менеджер'},operator:{t:'Операционист'},admin:{t:'Админ'},teodor:{t:'Теодор'}},
 SOURCES:{none:'Без переписки'},stepWho:()=> 'manager',stepTitle:()=> 'Закрытие',progress:()=>({i:13,n:13}),
 needsPayConfirm:()=>false,prepayPanel:()=>'',docSide:()=>'',assigneeBlock:()=>'',goalCard:()=>'',ctxCard:()=>'',
 dealTaskPath:()=>({steps:[],active:'s27',index:0}),dealTaskPathCard:()=>'',htmlText:String,
 stepCard:()=>'<button onclick="crmEvidence(1484,\'receipt\')">Оплата инвойса</button><button>Сохранить в CRM</button>',
 crmEvidencePanel:()=>'<button onclick="crmEvidence(1484,\'receipt\')">Оплата инвойса</button>',
 prepayCloseReason:()=>'',moneyKop:(n,c)=>`${n} ${c}`,
};
vm.createContext(ctx);vm.runInContext(source('viewDeal'),ctx);
const d={id:1484,code:'СД-1484',step:'s27',type:'Оплата недвижимости',kind:'Фрихолд',pay:{invoicePaid:true},log:[],source:'none'};
for(const role of ['operator','admin','manager']){
 ctx.S.role=role;const out=ctx.viewDeal(d);
 assert.match(out,/crmEvidence\(1484,'receipt'\)/,role+' получает подтверждения');
 if(role==='operator')assert.doesNotMatch(out,/Сохранить в CRM/,'оператору не открывается закрытие за менеджера');
}
ctx.S.role='teodor';assert.doesNotMatch(ctx.viewDeal(d),/crmEvidence/);
console.log('freehold close role visibility OK');

// Проверенные факты не показывают manager buttons; legacy receipt остаётся у оператора.
ctx.htmlText=String;ctx.econ=()=>({payin:11000,cost:10130});
ctx.payinSourceLabel=()=>'Flow Sole (СГБ) …0261';ctx.payoutHuman=()=>'IPPS → SWIFT';ctx.txShort=s=>s;
ctx.moneyKop=(v)=>String(v);
ctx.crmCloseStatus=()=>({facts:[{kind:'payin',ready:true,system:true},{kind:'payout',ready:true,system:true},{kind:'receipt',ready:false,reason:'operator_receipt_acceptance_missing'},{kind:'sent',ready:true}]});
ctx.crmCloseReason=()=> 'Нужно подтверждение оператора';
vm.runInContext(source('crmEvidenceParts'),ctx);
vm.runInContext(source('crmEvidencePanel'),ctx);
d.postConv='ipps_swift';d.serverTransferComplete=true;
for(const [role,expected] of [['operator',['receipt']],['manager',[]],['admin',['receipt']],['teodor',[]]]){
 ctx.S.role=role;
 const buttons=[...ctx.crmEvidencePanel(d).matchAll(/<button([^>]+)>/g)];
 const enabled=buttons.filter(b=>!b[1].includes('disabled')).map(b=>b[1].match(/crmEvidence\(1484,'([^']+)'/)[1]);
 assert.deepEqual(enabled,expected,role);
}

// Задача оператора доступна и из списка задач, после окончания ветки брокера.
ctx.S.deals=[d];ctx.reqOpen=()=>false;ctx.prepayRefundRole=()=>null;
vm.runInContext(source('taskBranchesForRole'),ctx);
vm.runInContext(html.match(/^function myTasks\([^]*?\n/m)[0],ctx);
assert.equal(ctx.myTasks('operator').length,1);
d.prepay={brokerStep:'done'};assert.equal(ctx.myTasks('operator').length,1);
d.closed=true;assert.equal(ctx.myTasks('operator').length,0);d.closed=false;
// У старого подтверждения без адресов есть безопасное действие повторной проверки.
d.transfer={sends:[{status:'confirmed'}]};ctx.S.role='operator';
assert.match(ctx.crmEvidencePanel(d),/checkSends\(1484\)/);
ctx.S.role='manager';assert.doesNotMatch(ctx.crmEvidencePanel(d),/checkSends/);
