/* CRM form as a stand draft. Fetching/parsing HTML does not run CRM scripts.
   Only named, local form actions below execute; no CRM bootstrap or links run. */
let crmDraftSourcePromise = null;
let crmDraftActive = null;
const crmDraftLive = new Map();

function crmDraftSource() {
  if (!crmDraftSourcePromise) crmDraftSourcePromise = fetch('/crm', {credentials:'same-origin'})
    .then(async r => {
      if (!r.ok) throw new Error('CRM form unavailable');
      const page = new DOMParser().parseFromString(await r.text(), 'text/html');
      const form = page.querySelector('#createDealForm');
      if (!form || !form.querySelector('#sberReqsGroup') ||
          !form.querySelector('#realtyPayoutTxBlock') || !form.querySelector('#fhDealSection'))
        throw new Error('CRM form structure changed');
      return page;
    });
  return crmDraftSourcePromise;
}
function crmDraftEsc(v) {
  return String(v ?? '').replace(/[&<>"']/g, c =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function crmDraftNum(v) {
  const n = Number(String(v ?? '').replace(/\s/g,'').replace(',','.'));
  return v === '' || v == null || !Number.isFinite(n) ? null : n;
}
function crmDraftCalculatedCost(root) {
  // CRM's own calculateProfit() writes the FIFO/card cost here. Keep that
  // result in the board; econ(d) and the final CRM payload then use one fact.
  const display=crmDraftRead(root,'cashBatchCostUsdt');
  const match=/^\$\s*([\d\s]+(?:[.,]\d{1,2})?)$/.exec(display.trim());
  return match ? crmDraftNum(match[1]) : null;
}
function crmDraftField(root,key) {
  return root.getElementById(key) || root.querySelector(`[name="${key}"]`);
}
function crmDraftValue(root,key,value) {
  const el=crmDraftField(root,key);
  if(el) el.value=value == null ? '' : String(value);
}
function crmDraftRead(root,key) {
  return crmDraftField(root,key)?.value ?? '';
}
function crmDraftFreeholdLocked(d) {
  return d.kind==='Фрихолд' && (
    ['s11','s11b','s12','s14','s14m','s15','s18','s18w','s22','s23','s24',
     's25','s26','s27','done'].includes(d.step) || !!d.docPack || !!d.closed ||
    !!d.crmDealId || !!d.serverTransferComplete ||
    (d.transfer?.sends||[]).some(x=>x.status==='confirmed'));
}
function crmDraftParts(d) {
  return (d.payinParts||[]).map(p=>({
    uuid:p.uuid || (String(p.incId||'').startsWith('sber:')?String(p.incId).slice(5):null),
    amount_rub:p.amountRub||0,payer:p.payer||'',date:(p.date||'').slice(0,10),
    note:p.note||'',kind:p.kind==='acquiring'?'acquiring':'transfer',
    fee_rub:p.fee||0,net_rub:p.net??p.amountRub,
  }));
}
function crmDraftSafeFetch(url,options) {
  const u=new URL(url,location.origin);
  const allowed=['/api/sber-incomes','/api/transactions/outgoing','/api/tx/lookup',
    '/api/transactions/incoming','/api/wl-transactions',
    '/api/payout-tx','/api/tron/payout-tx',
    '/api/cash/batches','/api/cards/balance','/api/wallets',
    '/api/rates',
    '/api/deals/mf-realty/preview','/api/deals/mf-freehold/preview',
    '/api/managers','/api/clients','/api/referrers','/api/payin-txs'];
  if(u.origin!==location.origin || !(allowed.includes(u.pathname)||u.pathname.startsWith('/api/payin-txs/')))
    return Promise.reject(new Error('CRM draft request blocked'));
  const method=(options?.method||'GET').toUpperCase();
  if(method!=='GET' && !(method==='POST' && u.pathname.endsWith('/preview')))
    return Promise.reject(new Error('CRM draft mutation blocked'));
  return window.fetch(u.href,{...options,credentials:'same-origin'});
}
function crmDraftSanitize(form) {
  const calls=new Set(['sberLoadIncomes()','sberAddManual()',
    'payinExtraAdd()','toggleMfPayoutPicker()','mfPayoutCheckAll(true)','mfPayoutCheckAll(false)',
    'addMfPayoutChecked()','addMfPayoutManual()','stdAgentsPreset(\'cascade\')',
    'stdAgentsPreset(\'flat\')','stdAgentsAdd()',
    "customAgentsPreset('cascade')","customAgentsPreset('flat')","customAgentsAdd()",
    'createCustomDeal()','loadOutgoingTxForSelect(true)',
    'loadOutgoingTxForBinance(true)','mfSuggestPercent()']);
  for(const el of [form,...form.querySelectorAll('*')]) {
    for(const attr of [...el.attributes]) {
      if(attr.name==='onclick'&&calls.has(attr.value))el.dataset.crmCall=attr.value;
      if(/^on/i.test(attr.name)||['href','target','formaction','action'].includes(attr.name))
        el.removeAttribute(attr.name);
    }
    if(el.tagName==='A')el.removeAttribute('href');
  }
  form.querySelectorAll('script,iframe,object,embed').forEach(el=>el.remove());
}
function crmDraftLayout(active) {
  const {root}=active,kind=crmDraftRead(root,'dealKindSelect');
  const custom=kind==='custom', mf=kind==='mf_realty', fh=kind==='mf_freehold';
  for(const [id,on] of [['customDealSection',custom],['standardDealSection',!custom],
      ['mfDealSection',mf],['mfDealHint',mf],['fhDealSection',fh],['fhDealHint',fh],
      ['payoutSectionStd',!mf&&!fh],['profitCalcHr',!mf&&!fh],
      ['profitCalcTitle',!mf&&!fh],['profitCalcRows',!mf&&!fh]]) {
    const el=root.getElementById(id);if(el)el.style.display=on?'block':'none';
  }
  for(const [id,on] of [['customDealToggle',custom],['mfDealToggle',mf],['fhDealToggle',fh]]) {
    const el=root.getElementById(id);if(el)el.checked=on;
  }
  // Same required-state transition as CRM applyRealtyLayout(). The save button
  // is outside the cloned form, so commit calls CRM reportInvalidField itself.
  for(const name of ['payout_method','payout_source']){
    const el=root.querySelector(`#standardDealSection [name="${name}"]`);
    if(el)el.required=!custom&&!mf&&!fh;
  }
  const payin=root.querySelector('#standardDealSection [name="payin_method"]');
  if(payin)payin.required=!custom;
  const tx=root.getElementById('realtyPayoutTxBlock');
  const slot=root.getElementById(fh?'fhPayoutSlot':'mfPayoutSlot');
  if(slot&&tx&&tx.parentElement!==slot)slot.appendChild(tx);
  const label=root.getElementById('realtyPayoutTxLabel');
  if(label)label.textContent=fh?'Переводы застройщику (факт)':'Переводы в MF Corp (факт)';
  active.core.applyPayinMethodFields();
  if(custom)active.core.calcCustomProfit();
  const src=crmDraftRead(root,'payoutSource');
  for(const [id,value] of [['cashBatchGroup','cash_batch'],['bankCardGroup','bank_card'],
      ['binanceGroup','binance'],['binanceGroup2','binance'],['founderGroup','founder_personal']]) {
    const el=root.getElementById(id);if(el)el.style.display=src===value?'flex':'none';
  }
  const noConv=root.getElementById('noConversionBox');
  if(noConv)noConv.style.display=root.getElementById('payoutNoConversion')?.checked?'block':'none';
  const transfers=root.getElementById('payoutTransfersBox');
  if(transfers)transfers.style.display=root.getElementById('payoutNoConversion')?.checked?'none':'block';
  const subtype=document.getElementById('crmDraftRealtySubtypeBox');
  if(subtype)subtype.style.display=mf?'block':'none';
  const tariffBox=document.getElementById('crmDraftTariffBox');
  if(tariffBox)tariffBox.style.display=fh?'block':'none';
  const invoiceBox=document.getElementById('crmDraftInvoiceCurrencyBox');
  if(invoiceBox)invoiceBox.style.display=fh?'block':'none';
  const thbBox=document.getElementById('crmDraftInvoiceThbBox');
  if(thbBox)thbBox.style.display=fh&&document.getElementById('crmDraftInvoiceCurrency')?.value==='thb'?'block':'none';
  const locked=crmDraftFreeholdLocked(deal(active.id));
  for(const id of ['crmDraftTariff','crmDraftInvoiceCurrency','crmDraftInvoiceThb']){
    const el=document.getElementById(id);if(el)el.disabled=locked;
  }
  for(const id of ['fhInvoiceUsd','fhFeePercent','fhFeeFixed']){
    const el=root.getElementById(id);if(el)el.disabled=locked;
  }
}
function crmDraftFill(active,d) {
  const {root}=active;
  const method=PAYIN_CRM[d.payType]||'sber_reqs';
  const kind=dealKind(d);
  crmDraftValue(root,'managerSelect',d.manager||'');
  crmDraftValue(root,'clientSearchInput',d.client||'');
  crmDraftValue(root,'clientIdHidden',d.crmClientId||'');
  crmDraftValue(root,'dealKindSelect',kind);
  crmDraftValue(root,'payinMethod',method);
  crmDraftValue(root,'payin_amount_rub',d.amountRub);
  crmDraftValue(root,'payin_amount_usdt',d.amountUsdt);
  crmDraftValue(root,'payin_rate_rub_usdt',d.rates?.broker);
  crmDraftValue(root,'payin_partner_name',d.payinPartner);
  crmDraftValue(root,'mfPurpose',d.realtyPurpose||d.object);
  crmDraftValue(root,'mfInvoiceThb',d.amountThb);
  crmDraftValue(root,'mfBuyRate',d.rates?.usdtThb);
  crmDraftValue(root,'mfSellRate',d.rates?.client);
  // The stand's 0.3 exchange default belongs only to exchange. A new realty
  // draft starts as exchange for workflow reasons; its MF input must remain
  // empty until the manager enters a spread (CRM only shows 1.5 placeholder).
  crmDraftValue(root,'mfSpread',kind==='mf_realty'?d.spread:null);
  crmDraftValue(root,'mfPercent',d.companyPct);
  crmDraftValue(root,'mfSentThb',d.sentThb);
  for(const [field,key] of [['mfDocInvoice','invoice'],['mfDocContract','contract'],['mfDocPayment','payment'],
      ['fhDocInvoice','invoice'],['fhDocContract','contract'],['fhDocPayment','payment']])
    crmDraftValue(root,field,d.docLinks?.[key]||'');
  crmDraftValue(root,'fhPurpose',d.realtyPurpose||d.object);
  crmDraftValue(root,'fhInvoiceUsd',d.invoiceUsd);
  crmDraftValue(root,'fhSentUsd',d.sentUsd);
  const tariff=IPPS_TARIFFS[d.ippsTariff];
  crmDraftValue(root,'fhFeePercent',tariff?.percent);
  crmDraftValue(root,'fhFeeFixed',tariff?.fixed);
  crmDraftValue(root,'payout_method',d.payout?.method==='курьер'?'courier':
    d.payout?.method==='банкомат'?'atm':d.payout?.method==='перевод на тайский счёт'?'transfer':'office');
  const src={cash:'cash_batch',ipps:'cash_batch',scb:d.payout?.bankCardId?'bank_card':'cash_batch',coins:'binance',
    client:'binance',founder:'founder_personal'}[d.paySrc]||'cash_batch';
  crmDraftValue(root,'payoutSource',src);
  crmDraftValue(root,'payout_amount_thb',d.payout?.thb??d.amountThb);
  crmDraftValue(root,'binanceUsdt',d.payout?.usdt);
  crmDraftValue(root,'binanceTxInput',d.payout?.hashes?.[0]?.hash||'');
  crmDraftValue(root,'bankCardSelect',d.payout?.bankCardId);
  crmDraftValue(root,'payoutWalletSelect',d.payout?.walletId);
  const noConv=root.getElementById('payoutNoConversion');if(noConv)noConv.checked=!!d.payout?.ownBaht;
  crmDraftValue(root,'noConvUsdt',d.payout?.usdt);
  crmDraftValue(root,'noConvWallet',d.payout?.walletId);
  const settled=root.getElementById('payoutSettledByPayin');if(settled)settled.checked=!!d.payout?.settledByPayin;
  crmDraftValue(root,'payout_founder_name',d.payout?.founder);
  crmDraftValue(root,'notes',d.notes);
  const c=d.customData||{};
  for(const [field,key] of [['customPayinAmount','payinAmount'],['customPayinRate','payinRate'],
    ['customPayinUsdt','payinUsdt'],['customPayoutAmount','payoutAmount'],
    ['customPayoutRate','payoutRate'],['customPayoutUsdt','payoutUsdt'],
    ['customPayinTxHash','payinTxHash'],['customDealDate','date']])
    crmDraftValue(root,field,c[key]);
  crmDraftValue(root,'customPayinCurrency',c.payinCurrency||'USDT');
  crmDraftValue(root,'customPayoutCurrency',c.payoutCurrency||'THB');
  crmDraftValue(root,'customPayinMethod',c.payinMethod||'crypto_direct');
  crmDraftValue(root,'customPayoutMethod',c.payoutMethod||'office');
  crmDraftValue(root,'customNotes',c.notes??d.notes);
  if(c.usdtMode?.payin==='usdt')active.core.onCustomUsdtInput('payin');
  if(c.usdtMode?.payout==='usdt')active.core.onCustomUsdtInput('payout');
  crmDraftLayout(active);
}
function crmDraftSnapshot(active) {
  const values={};
  active.form.querySelectorAll('input,select,textarea').forEach((el,i)=>{
    values[el.id||el.name||`#${i}`]=el.type==='checkbox'?el.checked:el.value;
  });
  return {values,sberParts:active.core.sberParts.map(x=>({...x})),
    payinTxPool:active.core.payinTxPool.map(x=>({...x})),
    payinExtra:active.core.payinExtra.map(x=>({...x})),
    agents:active.core.stdAgents.map(x=>({...x})),
    customAgents:active.core.customAgents.map(x=>({...x})),
    customUsdtMode:active.core.customUsdtMode,
    mfPayoutTxPool:active.core.mfPayoutTxPool.map(x=>({...x})),
    payoutTxPool:active.core.payoutTxPool.map(x=>({...x})),
    source:document.getElementById('crmDraftSource')?.value,
    sourceRef:document.getElementById('crmDraftSourceRef')?.value,
    subtype:document.getElementById('crmDraftRealtySubtype')?.value,
    tariff:document.getElementById('crmDraftTariff')?.value,
    invoiceCurrency:document.getElementById('crmDraftInvoiceCurrency')?.value,
    invoiceThb:document.getElementById('crmDraftInvoiceThb')?.value};
}
function crmDraftCapture() {
  if(crmDraftActive)crmDraftLive.set(crmDraftActive.id,crmDraftSnapshot(crmDraftActive));
}
function crmDraftRestore(active,snapshot) {
  if(!snapshot)return;
  active.form.querySelectorAll('input,select,textarea').forEach((el,i)=>{
    const v=snapshot.values[el.id||el.name||`#${i}`];
    if(v!==undefined){if(el.type==='checkbox')el.checked=!!v;else el.value=v;}
  });
  active.core.sberParts=snapshot.sberParts;
  active.core.resetPayinTxPool(snapshot.payinTxPool||[]);
  active.core.payinExtra=snapshot.payinExtra||[];
  active.core.mfPayoutTxPool=snapshot.mfPayoutTxPool;
  active.core.payoutTxPool=snapshot.payoutTxPool||[];
  active.core.stdAgentsLoad(snapshot.agents||[]);
  active.core.customAgentsLoad(snapshot.customAgents||[]);
  if(snapshot.customUsdtMode?.payin==='usdt')active.core.onCustomUsdtInput('payin');
  if(snapshot.customUsdtMode?.payout==='usdt')active.core.onCustomUsdtInput('payout');
  if(snapshot.source!=null)document.getElementById('crmDraftSource').value=snapshot.source;
  if(snapshot.sourceRef!=null)document.getElementById('crmDraftSourceRef').value=snapshot.sourceRef;
  if(snapshot.subtype!=null){const s=document.getElementById('crmDraftRealtySubtype');if(s)s.value=snapshot.subtype;}
  if(snapshot.tariff!=null)document.getElementById('crmDraftTariff').value=snapshot.tariff;
  if(snapshot.invoiceCurrency!=null)document.getElementById('crmDraftInvoiceCurrency').value=snapshot.invoiceCurrency;
  if(snapshot.invoiceThb!=null)document.getElementById('crmDraftInvoiceThb').value=snapshot.invoiceThb;
  crmDraftLayout(active);
}
async function crmDraftPreview(active) {
  const {root}=active,kind=crmDraftRead(root,'dealKindSelect');
  if(kind!=='mf_realty'&&kind!=='mf_freehold')return;
  if(kind==='mf_realty')return active.core.mfRecalcNow();
  if(kind==='mf_freehold'&&!IPPS_TARIFFS[document.getElementById('crmDraftTariff')?.value]){
    const box=root.getElementById('fhSummary');if(box)box.textContent='Выберите тариф IPPS из сделки';
    return;
  }
  return active.core.fhRecalcNow();
}
async function crmDraftMount(id) {
  const host=document.getElementById('crmDraftHost');
  if(!host){crmDraftActive=null;return;}
  try{
    const page=await crmDraftSource();
    if(S.edit!==id||document.getElementById('crmDraftHost')!==host)return;
    const shadow=host.attachShadow({mode:'open'});
    const css=page.querySelector('head style')?.textContent||'';
    const style=document.createElement('style');
    style.textContent=css.replace(/:root\s*\{/g,':host {')+'\n:host{display:block;font-family:Inter,sans-serif;color:#0f172a}';
    shadow.append(style);
    const form=page.querySelector('#createDealForm').cloneNode(true);
    crmDraftSanitize(form);
    shadow.append(form);
    const active={id,host,root:shadow,form,core:null};
    crmDraftActive=active;
    const d=deal(id);
    const subtype=document.getElementById('crmDraftRealtySubtype');
    if(subtype)subtype.value=d.kind==='Аренда'?'Аренда':'Лизхолд';
    const formFields={
      payin_amount_rub:crmDraftField(shadow,'payin_amount_rub'),
      payin_rate_rub_usdt:crmDraftField(shadow,'payin_rate_rub_usdt'),
      payin_amount_usdt:crmDraftField(shadow,'payin_amount_usdt'),
      payout_amount_thb:crmDraftField(shadow,'payout_amount_thb'),
      payout_source:crmDraftField(shadow,'payout_source'),
    };
    active.core=createCrmDraftCore(shadow,{
      form:formFields,editingDealId:d.manualNew?null:id,
      fetch:crmDraftSafeFetch,toast:message=>toast(message),escapeHtml:crmDraftEsc,
      formatNumber:v=>Number(v||0).toLocaleString('ru-RU',{maximumFractionDigits:2}),
      loadCurrentRate:()=>crmDraftLoadRate(active),realtyPayinRecalc:()=>crmDraftPreview(active),
      realtyPayoutRecalc:()=>crmDraftPreview(active),
      sberParts:crmDraftParts(d),
      payinTxPool:(d.payinHashes||[]).map(x=>({hash:x.hash,
        network:String(x.network||'trc20').toLowerCase().replace('-',''),
        amount_usdt:x.amount,date:x.date||''})),
      mfPayoutTxPool:(d.mfPayout||[]).map(x=>({
        hash:x.hash,network:String(x.net||'trc20').toLowerCase().replace('-',''),
        amount_usdt:x.amount,to_address:x.to_address||'',date:x.date||''})),
      payoutTxPool:(d.payout?.hashes||[]).map(x=>({hash:x.hash,
        amount_usdt:x.amount??x.amount_usdt??null,
        from_address:x.from_address||'',to_address:x.to_address||'',
        wallet_label:x.wallet_label||'',wallet_id:x.wallet_id||null})),
    });
    crmDraftFill(active,d);
    active.core.stdAgentsLoad((d.agents||[]).map(x=>({
      referrer_id:x.refId||null,name:x.name||'',tier:x.tier||1,
      comp_model:x.comp||'revshare',percent:x.percent??0,fixed_usdt:x.fixed??0,
    })));
    active.core.customAgentsLoad((d.agents||[]).map(x=>({
      referrer_id:x.refId||null,name:x.name||'',tier:x.tier||1,
      comp_model:x.comp||'revshare',percent:x.percent??0,fixed_usdt:x.fixed??0,
    })));
    active.core.payinExtra=(d.payinExtra||[]).map(x=>({
      method:x.method||'partners_cash',amount_rub:x.amount_rub??x.amountRub??null,
      rate_rub_usdt:x.rate_rub_usdt??crmDraftNum(x.rate),
      amount_usdt:x.amount_usdt??x.amountUsdt??null,
      partner_name:x.partner_name??x.partner??'',
      tx_hashes:(x.tx_hashes||x.hashes||[]).map(h=>({hash:h.hash,amount_usdt:h.amount_usdt??h.amount??null})),
      sber_parts:x.sber_parts||[],note:x.note||'',
    }));
    crmDraftRestore(active,crmDraftLive.get(id));
    crmDraftWire(active);
    active.core.sberRender();
    active.core.renderPayinTxPool();
    active.core.renderMfPayoutTxPool();
    active.core.renderPayoutTxPool();
    await Promise.all([active.core.sberLoadIncomes(),active.core.loadMfPayoutTx(),
      active.core.loadCashBatchesForSelect(),active.core.loadBankCardsForSelect(),
      crmDraftLoadPayinTx(active),crmDraftLoadLists(active),crmDraftLoadWallets(active),crmDraftLoadRate(active)]);
    if(crmDraftActive!==active)return;
    if(d.payout?.bankCardId != null)
      crmDraftValue(shadow,'bankCardSelect',d.payout.bankCardId);
    active.core.upgradeAllSelects();
    if(crmDraftRead(shadow,'payoutSource')==='binance')active.core.loadOutgoingTxForBinance();
    if(crmDraftRead(shadow,'payoutSource')==='founder_personal'){
      active.core.loadOutgoingTxForSelect(false);
      active.core.loadFounderWallets(d.payout?.walletId);
    }
    active.core.calculateProfit();
    active.core.calcBinanceRate();
    active.core.calcCustomProfit();
    crmDraftPreview(active);
  }catch(e){host.textContent='Форма CRM недоступна: '+e.message;}
}
async function crmDraftLoadRate(active) {
  if(active.rateRequested)return;
  active.rateRequested=true;
  try{
    const response=await crmDraftSafeFetch('/api/rates');
    const data=await response.json();
    if(data.usdt_thb&&crmDraftActive===active){
      active.core.currentUsdtThbRate=Number(data.usdt_thb);
      active.core.calculateProfit();
    }
  }catch(e){/* The CRM calculation retains its explicit fallback warning. */}
}
async function crmDraftLoadWallets(active) {
  try{
    const response=await crmDraftSafeFetch('/api/wallets');
    const data=await response.json();
    if(crmDraftActive!==active)return;
    const list=(data.wallets||[]).filter(w=>w.active!==false);
    for(const id of ['payoutWalletSelect','noConvWallet']){
      const select=active.root.getElementById(id);if(!select)continue;
      select.replaceChildren(new Option('-- Выбрать кошелёк --',''),
        ...list.map(w=>new Option(w.label||w.address||String(w.id),String(w.id))));
      select.value=String(deal(active.id).payout?.walletId||'');
    }
  }catch(e){/* Local wallet list unavailable; no external fallback. */}
}
async function crmDraftLoadPayinTx(active) {
  const select=active.root.getElementById('payinTxSelect');if(!select)return;
  try{
    const response=await crmDraftSafeFetch('/api/payin-txs?unallocated=1');
    const data=await response.json();
    select.replaceChildren(new Option('-- Выбрать из входящих --',''),
      ...(data.txs||[]).map(tx=>{
        const option=new Option(`+$${Number(tx.free_usdt||0).toFixed(2)} | ${String(tx.tx_hash||'').slice(0,16)}…`,tx.tx_hash);
        option.dataset.amount=tx.free_usdt;
        option.dataset.date=(tx.created_at||'').slice(0,10);
        return option;
      }));
    active.core.payinExtraTxCache=(data.txs||[]).map(tx=>({
      tx_hash:tx.tx_hash,amount_usdt:Number(tx.free_usdt||0),
      from_address:tx.from_address||'',timestamp:tx.created_at||'',
    }));
  }catch(e){select.title='Локальный реестр входящих недоступен';}
}
async function crmDraftLoadLists(active) {
  const {root}=active,d=deal(active.id);
  const get=async path=>{try{const r=await crmDraftSafeFetch(path);return r.ok?await r.json():{};}catch{return {};}};
  const [managers,clients,refs]=await Promise.all([get('/api/managers'),get('/api/clients'),get('/api/referrers')]);
  if(crmDraftActive!==active)return;
  const manager=root.getElementById('managerSelect');
  const names=(managers.managers||[]).filter(x=>x.active).map(x=>x.name);
  manager.replaceChildren(...names.map(name=>new Option(name,name)));
  // CRM's setManagerSelectValue() keeps a historical inactive/renamed manager
  // visible during edit, with the same label rather than silently replacing it.
  if(d.manager&&!names.includes(d.manager))
    manager.add(new Option(d.manager+' (не в списке)',d.manager));
  manager.value=d.manager||names[0]||'';
  active.clients=clients.clients||[];
  active.core.referrers=refs.referrers||[];
}
function crmDraftWire(active) {
  const {root,form}=active;
  form.addEventListener('submit',e=>{e.preventDefault();editSave(active.id);});
  root.addEventListener('change',e=>{
    const el=e.target;
    if(el.dataset.crmEvent==='change')crmDraftAction(active,el.dataset.crmAction,el);
    if(el.id==='dealKindSelect'){
      crmDraftLayout(active);crmDraftPreview(active);
      if(el.value==='custom')active.core.onCustomPayinMethodChange();
    }
    if(el.id==='customPayinMethod')active.core.onCustomPayinMethodChange();
    if(el.id==='customPayinTxSelect')active.core.selectCustomPayinTx(el);
    if(el.id==='binanceTxSelect')active.core.selectBinanceTx();
    if(el.id==='payoutTxSelect')active.core.selectPayoutTx(el);
    if(el.id==='sberKindSelectC')active.core.sberKindChanged(el.value);
    if(['customPayinCurrency','customPayoutCurrency'].includes(el.id))active.core.calcCustomProfit();
    if(el.id==='payinMethod')crmDraftLayout(active);
    if(el.id==='sberKindSelect')active.core.sberKindChanged(el.value);
    if(el.id==='payinTxSelect')active.core.selectPayinTx(el);
    if(el.id==='payoutSource'||el.id==='bankCardSelect'){
      crmDraftLayout(active);active.core.calculateProfit();
      if(el.id==='payoutSource'&&el.value==='binance')active.core.loadOutgoingTxForBinance();
      if(el.id==='payoutSource'&&el.value==='founder_personal'){
        active.core.loadOutgoingTxForSelect(false);
        active.core.loadFounderWallets();
      }
    }
    if(el.id==='payoutNoConversion'){
      active.core.toggleNoConversion();
    }
    if(el.id==='payoutSettledByPayin'){
      el.dataset.touched='1';active.core.togglePayoutSettled();
    }
    if(el.id==='noConvWallet')el.dataset.want=el.value;
  });
  document.getElementById('crmDraftInvoiceCurrency')?.addEventListener('change',()=>crmDraftLayout(active));
  root.addEventListener('input',e=>{
    const el=e.target;
    if(el.dataset.crmEvent==='input')crmDraftAction(active,el.dataset.crmAction,el);
    if(el.id==='mfPayoutSearch')active.core.renderMfPayoutPicker();
    if(['customPayinAmount','customPayoutAmount'].includes(el.id))active.core.calcCustomProfit();
    if(el.id==='customPayinRate')active.core.onCustomRateInput('payin');
    if(el.id==='customPayoutRate')active.core.onCustomRateInput('payout');
    if(el.id==='customPayinUsdt')active.core.onCustomUsdtInput('payin');
    if(el.id==='customPayoutUsdt')active.core.onCustomUsdtInput('payout');
    if(el.id==='binanceUsdt')active.core.calcBinanceRate();
    if(el.id==='payoutAmountThb'){
      active.core.calcBinanceRate();active.core.calcNoConvRate();
    }
    if(el.id==='noConvUsdt')active.core.calcNoConvRate();
    if(el.id==='payoutFounderHash')active.core.lookupPayoutFounderTx();
    if(el.name==='payin_rate_rub_usdt'){active.core.setPayinMode('rate');active.core.autoCalcUsdt();}
    if(el.name==='payin_amount_usdt'){active.core.setPayinMode('usdt');active.core.autoCalcUsdt();}
    if(['mfInvoiceThb','mfBuyRate','mfSellRate','mfSpread','mfPercent','mfSentThb'].includes(el.id)){
      if(el.id==='mfSpread')active.core.mfSpreadChanged();
      else active.core.mfRecalc({mfInvoiceThb:'invoice',mfPercent:'percent',mfSentThb:'sent'}[el.id]);
    }
    if(['fhInvoiceUsd','fhSentUsd','fhFeePercent','fhFeeFixed'].includes(el.id)){
      active.core.fhRecalc();
    }
    if(el.id==='clientSearchInput'){
      crmDraftValue(root,'clientIdHidden','');
      crmDraftClientSearch(active,el.value);
    }
  });
  root.addEventListener('click',e=>{
    const call=e.target.closest('[data-crm-call]')?.dataset.crmCall;
    if(call){
      e.preventDefault();
      const core=active.core;
      const actions={
    'sberLoadIncomes()':()=>core.sberLoadIncomes(),
        'sberAddManual()':()=>core.sberAddManual(),
        'toggleMfPayoutPicker()':()=>core.toggleMfPayoutPicker(),
        'mfPayoutCheckAll(true)':()=>core.mfPayoutCheckAll(true),
        'mfPayoutCheckAll(false)':()=>core.mfPayoutCheckAll(false),
        'addMfPayoutChecked()':()=>core.addMfPayoutChecked(),
        'addMfPayoutManual()':()=>core.addMfPayoutManual(),
        "stdAgentsPreset('cascade')":()=>core.stdAgentsPreset('cascade'),
        "stdAgentsPreset('flat')":()=>core.stdAgentsPreset('flat'),
        'stdAgentsAdd()':()=>core.stdAgentsAdd(),
        'payinExtraAdd()':()=>core.payinExtraAdd(),
        "customAgentsPreset('cascade')":()=>core.customAgentsPreset('cascade'),
        "customAgentsPreset('flat')":()=>core.customAgentsPreset('flat'),
        'customAgentsAdd()':()=>core.customAgentsAdd(),
        'createCustomDeal()':()=>editSave(active.id),
        'loadOutgoingTxForSelect(true)':()=>core.loadOutgoingTxForSelect(true),
        'loadOutgoingTxForBinance(true)':()=>core.loadOutgoingTxForBinance(true),
        'mfSuggestPercent()':()=>core.mfSuggestPercent(),
      };
      actions[call]?.();
    }
    const target=e.target.closest('[data-crm-action][data-crm-event="click"]');
    if(target)crmDraftAction(active,target.dataset.crmAction,target);
  });
  root.getElementById('clientSearchInput')?.addEventListener('focus',async e=>{
    try{
      const response=await crmDraftSafeFetch('/api/clients');
      const data=await response.json();
      if(crmDraftActive===active)active.clients=data.clients||data.data||[];
    }catch(error){/* Keep the already loaded local list. */}
    if(crmDraftActive===active)crmDraftClientSearch(active,e.target.value);
  });
  root.getElementById('payinManualHash')?.addEventListener('change',()=>crmDraftLookupPayin(active));
  document.getElementById('crmDraftTariff')?.addEventListener('change',e=>{
    const t=IPPS_TARIFFS[e.target.value];
    crmDraftValue(root,'fhFeePercent',t?.percent);
    crmDraftValue(root,'fhFeeFixed',t?.fixed);
    crmDraftPreview(active);
  });
}
async function crmDraftLookupPayin(active) {
  const {root}=active,hash=crmDraftRead(root,'payinManualHash').trim();
  active.manualTx=null;
  if(!hash)return;
  const network=crmDraftRead(root,'payinManualNetwork')||'trc20';
  try{
    const response=await crmDraftSafeFetch('/api/tx/lookup?network='+encodeURIComponent(network)+'&hash='+encodeURIComponent(hash));
    const data=await response.json();
    if(!response.ok||!data.success||!(Number(data.amount_usdt)>0))throw new Error(data.error||'Сумма не подтверждена сетью');
    active.manualTx={hash,network,amount:Number(data.amount_usdt)};
    crmDraftValue(root,'payin_amount_usdt',active.manualTx.amount.toFixed(2));
    const hint=root.getElementById('payinTxWarn');
    if(hint){hint.textContent='Сумма '+active.manualTx.amount.toFixed(2)+' USDT подтверждена сетью';hint.style.display='block';}
  }catch(error){toast('Хэш не принят: '+error.message);}
}
function crmDraftClientSearch(active,query) {
  const box=active.root.getElementById('clientDropdown');if(!box)return;
  const q=query.trim().toLowerCase();
  const matched=(active.clients||[]).filter(c=>!q||
    [c.name,c.telegram,c.phone].some(v=>String(v||'').toLowerCase().includes(q)));
  const list=matched.slice(0,30);
  box.innerHTML=list.map(c=>`<div class="client-dropdown-item" data-client="${crmDraftEsc(c.id)}"><div>
    <div class="client-name">${crmDraftEsc(c.name||'Без имени')}</div>
    ${c.telegram||c.phone?`<div class="client-meta">${crmDraftEsc(c.telegram||c.phone)}</div>`:''}
    </div></div>`).join('')+
    (q&&!matched.some(c=>String(c.name||'').toLowerCase()===q)
      ?`<div class="client-dropdown-create" data-client-new="1"><span>+</span> Создать «${crmDraftEsc(query.trim())}»</div>`:'') ||
    '<div style="padding:12px;color:var(--text-sec);">Ничего не найдено</div>';
  box.style.display='block';
  box.querySelectorAll('[data-client]').forEach(el=>el.addEventListener('click',()=>{
    const c=active.clients.find(x=>String(x.id)===el.dataset.client);
    crmDraftValue(active.root,'clientIdHidden',c.id);
    crmDraftValue(active.root,'clientSearchInput',c.name);box.style.display='none';
    const local=clients().find(x=>x.name===c.name);
    if(local?.refId&&!active.core.stdAgents.length){
      active.core.stdAgentsLoad(agentsDefault(local.refId).map(a=>({
        referrer_id:a.refId||null,name:a.name||'',tier:a.tier||1,
        comp_model:a.comp||'revshare',percent:a.percent??0,fixed_usdt:a.fixed??0,
      })));
    }
  }));
  box.querySelector('[data-client-new]')?.addEventListener('click',()=>{
    crmDraftValue(active.root,'clientIdHidden','');box.style.display='none';
  });
}
function crmDraftAction(active,action,target) {
  if(!action)return;
  const core=active.core,i=Number(target.dataset.index),k=Number(target.dataset.subindex);
  if(action==='sber-add')core.sberAddIncome(target.dataset.uuid);
  else if(action==='sber-remove')core.sberRemovePart(i);
  else if(action==='mf-check')core.mfPayoutCheck(target.dataset.hash,target.checked);
  else if(action==='mf-remove')core.removeMfPayoutTx(i);
  else if(action==='payin-remove')core.removePayinTx(i);
  else if(action==='payin-share')core.payinTxShareChanged(i,target.value);
  else if(action==='extra-remove')core.payinExtraRemove(i);
  else if(action==='extra-method')core.payinExtraSetMethod(i,target.value);
  else if(action==='extra-pick')core.payinExtraPickTx(i,target);
  else if(action==='extra-sber-add')core.payinExtraSberAdd(i,target.dataset.uuid);
  else if(action==='extra-sber-remove')core.payinExtraSberRemove(i,k);
  else if(action==='extra-hash-remove')core.payinExtraHashRemove(i,k);
  else if(action==='extra-hash-manual')core.payinExtraHashManual(i);
  else if(action==='extra-hash-share')core.payinExtraHashShare(i,k,target.value);
  else if(action==='extra-set')core.payinExtraSet(i,target.dataset.key,target.value);
  else if(action==='agent-remove')core.stdAgentsRemove(i);
  else if(action==='agent-tier')core.stdAgentsTier(i,Number(target.dataset.delta));
  else if(action==='agent-field')core.stdAgentsField(i,target.dataset.key,target.value);
  else if(action==='custom-agent-remove')core.customAgentsRemove(i);
  else if(action==='custom-agent-tier')core.customAgentsTier(i,Number(target.dataset.delta));
  else if(action==='custom-agent-field')core.customAgentsField(i,target.dataset.key,target.value);
  else if(action==='payout-share')core.payoutTxShareChanged(i,target.value);
  else if(action==='payout-remove')core.removePayoutTx(i);
  crmDraftCapture();
}
function crmDraftCommitCustom(a,d,before) {
  const r=a.root,num=key=>crmDraftNum(crmDraftRead(r,key));
  const payinAmount=num('customPayinAmount'),payoutAmount=num('customPayoutAmount');
  const payinCurrency=crmDraftRead(r,'customPayinCurrency');
  const payoutCurrency=crmDraftRead(r,'customPayoutCurrency');
  const payinRate=num('customPayinRate'),payoutRate=num('customPayoutRate');
  if(!(payinAmount>0&&payoutAmount>0)){
    toast('Укажите суммы Pay-In и Pay-Out');return false;
  }
  if((payinCurrency!=='USDT'&&!(payinRate>0))||
     (payoutCurrency!=='USDT'&&!(payoutRate>0))){
    toast('Укажите курс Pay-In и Pay-Out к USDT');return false;
  }
  a.core.calcCustomProfit();
  const payinUsdt=payinCurrency==='USDT'?payinAmount:num('customPayinUsdt');
  const payoutUsdt=payoutCurrency==='USDT'?payoutAmount:num('customPayoutUsdt');
  if(!(payinUsdt>0&&payoutUsdt>0)){
    toast('Расчёт USDT не завершён');return false;
  }
  const name=crmDraftRead(r,'clientSearchInput').trim();
  d.source=document.getElementById('crmDraftSource')?.value||d.source;
  d.sourceRef=document.getElementById('crmDraftSourceRef')?.value||'';
  d.custom=true;d.type='Обмен валюты';d.kind='';
  d.manager=crmDraftRead(r,'managerSelect')||d.manager;
  if(name){
    d.client=name;d.crmClientId=crmDraftNum(crmDraftRead(r,'clientIdHidden'));
    let local=clients().find(c=>c.name===name);
    if(!local){local={id:Math.max(0,...clients().map(c=>Number(c.id)||0))+1,
      name,tg:d.sourceRef||'',docs:false,refId:null};clients().push(local);}
    d.clientId=local.id;
  }
  const c={payinCurrency,payinAmount,payinRate:payinCurrency==='USDT'?null:payinRate,
    payinUsdt,payoutCurrency,payoutAmount,
    payoutRate:payoutCurrency==='USDT'?null:payoutRate,payoutUsdt,
    profit:payinUsdt-payoutUsdt,netProfit:a.core.customAgentsRecalc(),
    usdtMode:a.core.customUsdtMode,
    payinMethod:crmDraftRead(r,'customPayinMethod'),
    payoutMethod:crmDraftRead(r,'customPayoutMethod'),
    payinTxHash:crmDraftRead(r,'customPayinTxHash').trim(),
    date:crmDraftRead(r,'customDealDate'),notes:crmDraftRead(r,'customNotes')};
  d.customData=c;
  const methods={sber_reqs:'По реквизитам',sber_wl:'СБП',crypto_direct:'Крипта',partners_cash:'Наличные'};
  d.payType=methods[c.payinMethod]||d.payType;
  d.amountRub=payinCurrency==='RUB'?payinAmount:null;
  d.amountUsdt=payinUsdt;
  d.amountThb=payoutCurrency==='THB'?payoutAmount:null;
  d.payout={...(d.payout||{}),method:c.payoutMethod,source:'Binance',
    thb:d.amountThb,usdt:payoutUsdt};
  d.paySrc='coins';
  d.rates=d.rates||{};
  d.rates.broker=payinCurrency==='RUB'?payinRate:null;
  const prior=new Set((d.payinParts||[]).map(p=>p.incId).filter(Boolean));
  d.payinParts=a.core.sberParts.map(p=>({uuid:p.uuid||null,
    incId:p.uuid?'sber:'+p.uuid:null,amountRub:crmDraftNum(p.amount_rub),
    payer:p.payer||'',date:p.date||'',note:p.note||'',
    kind:p.kind==='acquiring'?'acquiring':'bank',fee:crmDraftNum(p.fee_rub)||0,
    net:crmDraftNum(p.net_rub)}));
  const selected=new Set(d.payinParts.map(p=>p.incId).filter(Boolean));
  incomes().forEach(x=>{if(prior.has(x.id)&&!selected.has(x.id)&&x.dealId===d.id)x.dealId=null;
    if(selected.has(x.id)&&!x.dealId)x.dealId=d.id;});
  d.incomeAmount=d.payinParts.length?
    Math.round(d.payinParts.reduce((sum,p)=>sum+(p.amountRub||0),0)*100)/100:null;
  d.payinExtra=a.core.payinExtraSerialize();
  d.payinHashes=c.payinTxHash?[{hash:c.payinTxHash,network:'trc20',amount:payinUsdt}]:[];
  d.notes=c.notes;
  d.agents=a.core.customAgentsSerialize().map(x=>({refId:x.referrer_id,
    name:x.name,tier:x.tier,comp:x.comp_model,percent:x.percent,fixed:x.fixed_usdt}));
  crmDraftCapture();
  return JSON.stringify(d)===before?[]:['форма CRM'];
}
function crmDraftCommit(id) {
  const a=crmDraftActive;if(!a||a.id!==id)return;
  const d=deal(id),r=a.root;
  if(a.core.reportInvalidField(a.form))return false;
  const before=JSON.stringify(d);
  const kind=crmDraftRead(r,'dealKindSelect');
  if(kind==='custom')return crmDraftCommitCustom(a,d,before);
  const manualHash=crmDraftRead(r,'payinManualHash').trim();
  if(manualHash&&a.manualTx?.hash!==manualHash){toast('Сначала подтвердите сумму ручного хэша в сети');return false;}
  let tariff=null;
  if(kind==='mf_freehold'){
    tariff=document.getElementById('crmDraftTariff')?.value;
    const locked=crmDraftFreeholdLocked(d);
    // A historical document can predate invoiceCurrency/THB or the tariff
    // selector. An identity/note edit must preserve its exact stored schema.
    if(!IPPS_TARIFFS[tariff] && !(locked && !tariff && !d.ippsTariff)){
      toast('Выберите тариф IPPS из сделки');return false;
    }
    const pct=crmDraftNum(crmDraftRead(r,'fhFeePercent'));
    const fixed=crmDraftNum(crmDraftRead(r,'fhFeeFixed'));
    if(IPPS_TARIFFS[tariff] &&
        (fixed!==IPPS_TARIFFS[tariff].fixed || pct!==IPPS_TARIFFS[tariff].percent)){
      toast('Комиссия формы не совпадает с выбранным тарифом сделки');return false;
    }
    if(locked && (
      crmDraftNum(crmDraftRead(r,'fhInvoiceUsd'))!==(d.invoiceUsd??null) || tariff!==(d.ippsTariff||'') ||
      (document.getElementById('crmDraftInvoiceCurrency')?.value||'usd')!==(d.invoiceCurrency||'usd') ||
      crmDraftNum(document.getElementById('crmDraftInvoiceThb')?.value)!==(d.invoiceThb??null))){
      toast('Инвойс и тариф IPPS закрыты после начала подготовки договора');return false;
    }
  }
  // Source and rental workflow data belong to stand_state and are not CRM kind.
  d.source=document.getElementById('crmDraftSource')?.value||d.source;
  d.sourceRef=document.getElementById('crmDraftSourceRef')?.value||'';
  d.custom=kind==='custom';
  d.type=(kind==='mf_realty'||kind==='mf_freehold')?'Оплата недвижимости':'Обмен валюты';
  d.kind=kind==='mf_freehold'?'Фрихолд':kind==='mf_realty'
    ?(document.getElementById('crmDraftRealtySubtype')?.value|| (d.kind==='Аренда'?'Аренда':'Лизхолд')):'';
  d.manager=crmDraftRead(r,'managerSelect')||d.manager;
  const name=crmDraftRead(r,'clientSearchInput').trim();
  if(name){
    d.client=name;d.crmClientId=crmDraftNum(crmDraftRead(r,'clientIdHidden'));
    let local=clients().find(c=>c.name===name);
    if(!local){
      const cid=Math.max(0,...clients().map(c=>Number(c.id)||0))+1;
      local={id:cid,name,tg:d.sourceRef||'',docs:false,refId:null};
      clients().push(local);
    }
    d.clientId=local.id;
  }
  const methods={sber_reqs:'По реквизитам',sber_wl:'СБП',crypto_direct:'Крипта',partners_cash:'Наличные'};
  d.payType=methods[crmDraftRead(r,'payinMethod')]||d.payType;
  d.amountRub=crmDraftNum(crmDraftRead(r,'payin_amount_rub'));
  d.amountUsdt=crmDraftNum(crmDraftRead(r,'payin_amount_usdt'));
  d.rates=d.rates||{};
  d.rates.broker=crmDraftNum(crmDraftRead(r,'payin_rate_rub_usdt'));
  d.payinPartner=crmDraftRead(r,'payin_partner_name');
  d.payinHashes=a.core.payinTxPool.map(x=>({hash:x.hash,network:x.network||'trc20',amount:crmDraftNum(x.amount_usdt)}));
  d.payinExtra=a.core.payinExtraSerialize();
  if(a.manualTx&&!d.payinHashes.some(x=>x.hash===a.manualTx.hash))d.payinHashes.push(a.manualTx);
  const old=new Set((d.payinParts||[]).map(p=>p.incId).filter(Boolean));
  d.payinParts=a.core.sberParts.map(p=>({uuid:p.uuid||null,
    incId:p.uuid?'sber:'+p.uuid:null,amountRub:crmDraftNum(p.amount_rub),
    payer:p.payer||'',date:p.date||'',note:p.note||'',
    kind:p.kind==='acquiring'?'acquiring':'bank',fee:crmDraftNum(p.fee_rub)||0,
    net:crmDraftNum(p.net_rub)}));
  const next=new Set(d.payinParts.map(p=>p.incId).filter(Boolean));
  incomes().forEach(x=>{if(old.has(x.id)&&!next.has(x.id)&&x.dealId===id)x.dealId=null;
    if(next.has(x.id)&&!x.dealId)x.dealId=id;});
  d.incomeAmount=d.payinParts.length?Math.round(d.payinParts.reduce((s,p)=>s+(p.amountRub||0),0)*100)/100:null;
  d.mfPayout=a.core.mfPayoutTxPool.map(p=>({hash:p.hash,net:p.network||'trc20',
    amount:crmDraftNum(p.amount_usdt),to_address:p.to_address||'',date:p.date||''}));
  d.realtyPurpose=kind==='mf_freehold'?crmDraftRead(r,'fhPurpose'):crmDraftRead(r,'mfPurpose');
  if(d.realtyPurpose){d.payTo=d.payTo||{};d.payTo.purpose=d.realtyPurpose;}
  if(kind==='mf_realty'||kind==='mf_freehold'){
    d.docLinks=d.docLinks||{};
    const prefix=kind==='mf_freehold'?'fh':'mf';
    for(const [field,key] of [['DocInvoice','invoice'],['DocContract','contract'],['DocPayment','payment']])
      d.docLinks[key]=crmDraftRead(r,prefix+field);
  }
  if(kind==='mf_realty'){
    d.amountThb=crmDraftNum(crmDraftRead(r,'mfInvoiceThb'));
    d.rates.usdtThb=crmDraftNum(crmDraftRead(r,'mfBuyRate'));
    d.rates.client=crmDraftNum(crmDraftRead(r,'mfSellRate'));
    d.spread=crmDraftNum(crmDraftRead(r,'mfSpread'));
    d.companyPct=crmDraftNum(crmDraftRead(r,'mfPercent'));
    d.sentThb=crmDraftNum(crmDraftRead(r,'mfSentThb'));
  }
  if(kind==='mf_freehold'){
    d.sentUsd=crmDraftNum(crmDraftRead(r,'fhSentUsd'));
    // The server is authoritative after document preparation. Keep missing
    // historical keys missing: writing an implicit USD/null default here would
    // turn a harmless note edit into a guarded money mutation.
    if(!crmDraftFreeholdLocked(d)){
      d.invoiceUsd=crmDraftNum(crmDraftRead(r,'fhInvoiceUsd'));
      d.ippsTariff=tariff;
      d.invoiceCurrency=document.getElementById('crmDraftInvoiceCurrency')?.value||'usd';
      d.invoiceThb=d.invoiceCurrency==='thb'?crmDraftNum(document.getElementById('crmDraftInvoiceThb')?.value):null;
    }
  }
  if(kind==='exchange'){
    d.amountThb=crmDraftNum(crmDraftRead(r,'payout_amount_thb'));
    d.payout=d.payout||{};
    d.payout.thb=d.amountThb;
    const outgoing=a.core.payoutTxPool.map(x=>({hash:x.hash,
      amount:crmDraftNum(x.amount_usdt),network:x.network||'trc20',
      from_address:x.from_address||'',to_address:x.to_address||'',
      wallet_label:x.wallet_label||'',wallet_id:x.wallet_id||null}));
    const source=crmDraftRead(r,'payoutSource');
    const singleHash=crmDraftRead(r,'binanceTxInput').trim();
    const founderHash=crmDraftRead(r,'payoutFounderHash').trim();
    d.payout.hashes=source==='founder_personal'?outgoing:
      source==='binance'&&singleHash?[{hash:singleHash,
        amount:crmDraftNum(crmDraftRead(r,'binanceUsdt')),network:'trc20'}]:[];
    if(source==='founder_personal'&&founderHash&&!d.payout.hashes.some(x=>x.hash===founderHash))
      d.payout.hashes.push({hash:founderHash,amount:null,network:'trc20'});
    d.payout.usdt=source==='founder_personal'?
      (r.getElementById('payoutNoConversion')?.checked?
        crmDraftNum(crmDraftRead(r,'noConvUsdt')):a.core.payoutTxPoolTotal()):
      source==='binance'?crmDraftNum(crmDraftRead(r,'binanceUsdt')):
      crmDraftCalculatedCost(r);
    const method={office:'наличные в офисе',courier:'курьер',atm:'банкомат',transfer:'перевод на тайский счёт'};
    d.payout.method=method[crmDraftRead(r,'payout_method')]||'';
    const src={cash_batch:'cash',bank_card:'scb',binance:'coins',founder_personal:'founder'};
    d.paySrc=src[crmDraftRead(r,'payoutSource')]||null;
    d.payout.founder=crmDraftRead(r,'payout_founder_name');
    d.payout.bankCardId=crmDraftNum(crmDraftRead(r,'bankCardSelect'));
    d.payout.walletId=source==='founder_personal'?
      crmDraftNum(outgoing.find(x=>x.wallet_id)?.wallet_id):
      crmDraftNum(crmDraftRead(r,'payoutWalletSelect'));
    d.payout.ownBaht=!!r.getElementById('payoutNoConversion')?.checked;
    d.payout.settledByPayin=!!r.getElementById('payoutSettledByPayin')?.checked;
    if(d.payout.ownBaht){
      d.payout.usdt=crmDraftNum(crmDraftRead(r,'noConvUsdt'));
      d.payout.walletId=crmDraftNum(crmDraftRead(r,'noConvWallet'));
    }
  }
  d.notes=crmDraftRead(r,'notes');
  d.agents=a.core.stdAgentsSerialize().map(x=>({refId:x.referrer_id,name:x.name,
    tier:x.tier,comp:x.comp_model,percent:x.percent,fixed:x.fixed_usdt}));
  crmDraftCapture();
  return JSON.stringify(d)===before?[]:['форма CRM'];
}
function sberAddIncome(uuid){crmDraftActive?.core.sberAddIncome(uuid);crmDraftCapture();}
function sberRemovePart(i){crmDraftActive?.core.sberRemovePart(i);crmDraftCapture();}
function mfPayoutCheck(hash,on){crmDraftActive?.core.mfPayoutCheck(hash,on);}
function removeMfPayoutTx(i){crmDraftActive?.core.removeMfPayoutTx(i);crmDraftCapture();}
function payinTxShareChanged(i,v){crmDraftActive?.core.payinTxShareChanged(i,v);crmDraftCapture();}
function removePayinTx(i){crmDraftActive?.core.removePayinTx(i);crmDraftCapture();}
function stdAgentsTier(i,d){crmDraftActive?.core.stdAgentsTier(i,d);crmDraftCapture();}
function stdAgentsRemove(i){crmDraftActive?.core.stdAgentsRemove(i);crmDraftCapture();}
function stdAgentsField(i,k,v){crmDraftActive?.core.stdAgentsField(i,k,v);crmDraftCapture();}
function payinExtraRemove(i){crmDraftActive?.core.payinExtraRemove(i);crmDraftCapture();}
function payinExtraSet(i,k,v){crmDraftActive?.core.payinExtraSet(i,k,v);crmDraftCapture();}
function payinExtraSetMethod(i,v){crmDraftActive?.core.payinExtraSetMethod(i,v);crmDraftCapture();}
function payinExtraPickTx(i,el){crmDraftActive?.core.payinExtraPickTx(i,el);crmDraftCapture();}
function payinExtraHashManual(i){crmDraftActive?.core.payinExtraHashManual(i);crmDraftCapture();}
function payinExtraHashRemove(i,k){crmDraftActive?.core.payinExtraHashRemove(i,k);crmDraftCapture();}
function payinExtraHashShare(i,k,v){crmDraftActive?.core.payinExtraHashShare(i,k,v);crmDraftCapture();}
function payinExtraSberAdd(i,uuid){crmDraftActive?.core.payinExtraSberAdd(i,uuid);crmDraftCapture();}
function payinExtraSberRemove(i,k){crmDraftActive?.core.payinExtraSberRemove(i,k);crmDraftCapture();}
