/* Узкий адаптер черновика: DOM и обработчики пулов берутся из crm.html.
   Чужой bootstrap CRM не исполняется; сохранение остаётся в stand_state. */
const crmDraftSource = fetch('/crm', {credentials:'same-origin'}).then(async response => {
  if (!response.ok) throw new Error('CRM form unavailable');
  const html = await response.text();
  const source = new DOMParser().parseFromString(html, 'text/html');
  if (!source.querySelector('#createDealForm #sberReqsGroup') ||
      !source.querySelector('#createDealForm #realtyPayoutTxBlock')) {
    throw new Error('CRM form structure changed');
  }
  return source;
});
const crmDraftLive = new Map();
let crmDraftCore = null;
let crmDraftDealId = null;

function crmDraftEscape(value) {
  return String(value ?? '').replace(/[&<>"']/g, ch =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
}
function crmDraftParts(d) {
  return (d.payinParts || []).map(p => ({
    uuid:p.uuid || (String(p.incId || '').startsWith('sber:') ? String(p.incId).slice(5) : null),
    amount_rub:p.amountRub || 0, payer:p.payer || '', date:(p.date || '').slice(0,10),
    note:p.note || '', kind:p.kind === 'acquiring' ? 'acquiring' : 'transfer',
    fee_rub:p.fee || 0, net_rub:p.net ?? p.amountRub,
  }));
}
function crmDraftCapture() {
  if (crmDraftDealId == null || !crmDraftCore) return;
  crmDraftLive.set(crmDraftDealId, {
    sberParts:crmDraftCore.sberParts.map(p => ({...p})),
    mfPayoutTxPool:crmDraftCore.mfPayoutTxPool.map(p => ({...p})),
  });
}
function crmDraftClone(source, selector) {
  const node = source.querySelector('#createDealForm ' + selector).cloneNode(true);
  // Только явно перечисленные команды пула получают обработчики. Ссылки,
  // формы и любые другие inline события из CRM не переносятся в задачник.
  node.querySelectorAll('*').forEach(el => {
    const action = el.getAttribute('onclick');
    for (const attr of [...el.attributes]) {
      if (/^on/i.test(attr.name) || attr.name === 'href' || attr.name === 'target')
        el.removeAttribute(attr.name);
    }
    const allowed = {
      'sberLoadIncomes()':() => crmDraftCore.sberLoadIncomes(),
      'sberAddManual()':() => crmDraftCore.sberAddManual(),
      'toggleMfPayoutPicker()':() => crmDraftCore.toggleMfPayoutPicker(),
      'mfPayoutCheckAll(true)':() => crmDraftCore.mfPayoutCheckAll(true),
      'mfPayoutCheckAll(false)':() => crmDraftCore.mfPayoutCheckAll(false),
      'addMfPayoutChecked()':() => crmDraftCore.addMfPayoutChecked(),
      'addMfPayoutManual()':() => crmDraftCore.addMfPayoutManual(),
    };
    if (allowed[action]) el.addEventListener('click', allowed[action]);
    if (el.id === 'sberKindSelect')
      el.addEventListener('change', () => crmDraftCore.sberKindChanged(el.value));
    if (el.id === 'mfPayoutSearch')
      el.addEventListener('input', () => crmDraftCore.renderMfPayoutPicker());
  });
  return node;
}
async function crmDraftMount(id) {
  const sberSlot = document.getElementById('crmSberSlot');
  const mfSlot = document.getElementById('crmMfPayoutSlot');
  if (!sberSlot && !mfSlot) { crmDraftCore = null; crmDraftDealId = null; return; }
  crmDraftDealId = id;
  try {
    const source = await crmDraftSource;
    // Пока HTML грузился, пользователь мог уйти с карточки.
    if (S.edit !== id || document.getElementById('crmSberSlot') !== sberSlot &&
        document.getElementById('crmMfPayoutSlot') !== mfSlot) return;
    if (sberSlot) {
      const node = crmDraftClone(source, '#sberReqsGroup');
      node.style.display = 'block';
      sberSlot.replaceChildren(node);
    }
    if (mfSlot) {
      const node = crmDraftClone(source, '#realtyPayoutTxBlock');
      mfSlot.replaceChildren(node);
    }
    const d = deal(id), live = crmDraftLive.get(id);
    const safeFetch = (url, options) => {
      const parsed = new URL(url, location.origin);
      if (parsed.origin !== location.origin ||
          !['/api/sber-incomes','/api/transactions/outgoing','/api/tx/lookup'].includes(parsed.pathname) ||
          (options && options.method && options.method.toUpperCase() !== 'GET'))
        return Promise.reject(new Error('CRM draft request blocked'));
      // Исходящий пул читаем только из локального кэша. Холодный кэш не
      // запускает TronScan fetch при открытии формы задачника.
      if (parsed.pathname === '/api/transactions/outgoing')
        parsed.searchParams.set('stale_ok','true');
      return window.fetch(parsed.href, {credentials:'same-origin'});
    };
    crmDraftCore = createCrmDraftCore(document, {
      fetch:safeFetch, toast:(message)=>toast(message), escapeHtml:crmDraftEscape,
      formatDate:v=>new Date(v).toLocaleDateString('ru-RU'),
      form:{
        payin_amount_rub:document.querySelector('[name="payin_amount_rub"]'),
        payin_rate_rub_usdt:document.querySelector('[name="payin_rate_rub_usdt"]'),
        payin_amount_usdt:document.querySelector('[name="payin_amount_usdt"]'),
      },
      editingDealId:d.manualNew ? null : id,
      calculateProfit:()=>{}, realtyPayinRecalc:()=>{},
      realtyPayoutRecalc:()=>{},
      sberParts:live?.sberParts || crmDraftParts(d),
      mfPayoutTxPool:live?.mfPayoutTxPool || (d.mfPayout || []).map(p => ({
        hash:p.hash, network:String(p.net || 'trc20').toLowerCase().replace('-',''),
        amount_usdt:p.amount, to_address:p.to_address || '', date:p.date || '',
      })),
    });
    if (sberSlot) { crmDraftCore.sberRender(); await crmDraftCore.sberLoadIncomes(); }
    document.querySelector('[name="payin_rate_rub_usdt"]')?.addEventListener('input', () => {
      crmDraftCore.setPayinMode('rate'); crmDraftCore.autoCalcUsdt();
    });
    document.querySelector('[name="payin_amount_usdt"]')?.addEventListener('input', () => {
      crmDraftCore.setPayinMode('usdt'); crmDraftCore.autoCalcUsdt();
    });
    if (mfSlot) { crmDraftCore.renderMfPayoutTxPool(); await crmDraftCore.loadMfPayoutTx(); }
  } catch (error) {
    const slot = sberSlot || mfSlot;
    if (slot) slot.textContent = 'Форма CRM недоступна: ' + error.message;
  }
}

function crmDraftCommit(id) {
  if (crmDraftDealId !== id || !crmDraftCore) return;
  const d = deal(id);
  const parts = crmDraftCore.sberParts;
  if (document.getElementById('crmSberSlot')) {
    const old = new Set((d.payinParts || []).map(p => p.incId).filter(Boolean));
    d.payinParts = parts.map(p => ({
      uuid:p.uuid || null, incId:p.uuid ? 'sber:' + p.uuid : null,
      amountRub:Number(p.amount_rub) || 0, payer:p.payer || '',
      date:(p.date || '').slice(0,10), note:p.note || '',
      kind:p.kind === 'acquiring' ? 'acquiring' : 'bank',
      fee:Number(p.fee_rub) || 0, net:p.net_rub == null ? null : Number(p.net_rub),
    }));
    const next = new Set(d.payinParts.map(p => p.incId).filter(Boolean));
    incomes().forEach(x => {
      if (old.has(x.id) && !next.has(x.id) && x.dealId === id) x.dealId = null;
      if (next.has(x.id) && !x.dealId) x.dealId = id;
    });
    d.incomeAmount = parts.length ? Math.round(parts.reduce((sum,p)=>sum+(Number(p.amount_rub)||0),0)*100)/100 : null;
    const rub = document.getElementById('e_pay_amt');
    if (rub && rub.name === 'payin_amount_rub' && parts.length) rub.value = d.incomeAmount.toFixed(2);
  }
  if (document.getElementById('crmMfPayoutSlot')) {
    d.mfPayout = crmDraftCore.mfPayoutTxPool.map(p => ({
      hash:p.hash, net:p.network || 'trc20', amount:p.amount_usdt,
      to_address:p.to_address || '', date:p.date || '',
    }));
  }
  crmDraftCapture();
}

// HTML, созданный функциями CRM, ссылается только на эти команды.
function sberAddIncome(uuid) { crmDraftCore?.sberAddIncome(uuid); crmDraftCapture(); }
function sberRemovePart(index) { crmDraftCore?.sberRemovePart(index); crmDraftCapture(); }
function mfPayoutCheck(hash, on) { crmDraftCore?.mfPayoutCheck(hash,on); }
function removeMfPayoutTx(index) { crmDraftCore?.removeMfPayoutTx(index); crmDraftCapture(); }
