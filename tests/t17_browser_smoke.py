"""Local synthetic UI probe. Run only inside T17 OS sandbox with clean env."""
import runpy
import socket
import threading
import time
import json
from urllib.parse import urlparse, parse_qs

appmod = runpy.run_path('tests/t17_fenced_smoke.py')['app']
db=appmod.get_session()
try:
    if not db.query(appmod.Manager).filter_by(name='Марина').first():
        db.add(appmod.Manager(name='Марина',active=True))
    db.add(appmod.Referrer(name='T17 Agent',code='T17AGENT',token='t17-synthetic-agent',
                           default_percent=10,comp_model='revshare',active=True,is_test=True))
    db.add(appmod.Client(name='T17 Existing',telegram='@t17fixture',phone='70000000000'))
    db.add(appmod.SberIncome(uuid='t17-transfer-1',operation_date='2026-09-27T12:00:00',
        amount_rub=266000,payer='T17 Transfer',purpose='Оплата недвижимости. НДС не облагается'))
    db.add(appmod.SberIncome(uuid='t17-acquiring-1',operation_date='2026-09-28T11:00:00',
        amount_rub=99300,payer='T17 Acquiring',purpose=
        'Зачисление средств по операциям эквайринга. Мерчант №781003872118. Комиссия 700.00. НДС не облагается.'))
    db.commit()
finally:
    db.close()
thread = threading.Thread(target=lambda: appmod.app.run(host='127.0.0.1', port=18917,
                                    debug=False, use_reloader=False), daemon=True)
thread.start()
for _ in range(50):
    sock = socket.socket()
    result = sock.connect_ex(('127.0.0.1', 18917))
    sock.close()
    if result == 0:
        break
    time.sleep(.1)
else:
    raise RuntimeError('own localhost port unavailable')
print('own localhost: success')

from playwright.sync_api import sync_playwright

def pick(scope, field, value):
    """Use CRM's actual upgraded dropdown when it is present."""
    select=scope.locator('#'+field)
    if select.get_attribute('data-upgraded')=='true':
        wrap=select.locator('xpath=..')
        wrap.locator('.custom-select-btn').click()
        option=wrap.locator(f'.custom-select-opt[data-value="{value}"]')
        if not option.is_visible():
            print('hidden custom option:',field,value,wrap.evaluate('e=>e.outerHTML.slice(0,450)'))
        try:
            option.click(timeout=5000)
        except Exception:
            print('custom option hit test:',field,value,option.evaluate('''e=>{
              const r=e.getBoundingClientRect(),x=r.left+r.width/2,y=r.top+r.height/2;
              const hit=e.getRootNode().elementFromPoint(x,y);
              return {rect:[r.left,r.top,r.width,r.height],hit:hit?.outerHTML.slice(0,220),
                wrap:e.closest('.custom-select-wrap')?.className};}'''))
            raise
    else:
        select.select_option(value)

def start_manual(page):
    page.evaluate('startManual()')
    # newDeal() and startManual() each queue a board save. Wait through the
    # queued second PUT and its rerender before touching a ShadowRoot control.
    page.wait_for_timeout(180)
    page.wait_for_function('!standBusy && !standPush',timeout=20000)
    page.locator('#crmDraftHost #managerSelect[data-upgraded="true"]').wait_for(
        state='attached',timeout=20000)

def open_edit(page, deal_id):
    page.wait_for_timeout(180)
    page.wait_for_function('!standBusy && !standPush',timeout=20000)
    page.evaluate('(id)=>editOpen(id)',deal_id)
    page.wait_for_timeout(180)
    page.wait_for_function('!standBusy && !standPush',timeout=20000)
    page.locator('#crmDraftHost #managerSelect[data-upgraded="true"]').wait_for(
        state='attached',timeout=20000)

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True,
        executable_path='/Users/karimamirov/Library/Caches/ms-playwright/chromium_headless_shell-1234/chrome-headless-shell-mac-arm64/chrome-headless-shell')
    context = browser.new_context(ignore_https_errors=True)
    blocked=[]
    outgoing=[{'tx_hash':format(i,'064x'),'amount_usdt':round(100+i/100,2),
               'to_address':f'T17-outgoing-address-{i%4}',
               'timestamp':'2026-09-28T10:00:00Z'} for i in range(1,251)]
    outgoing_count=[250]
    founder_hash='f'*64
    founder_tx={'tx_hash':founder_hash,'amount_usdt':3205.13,
                'from_address':'T17-founder-wallet','to_address':'T17-recipient',
                'timestamp':'2026-09-28T10:00:00Z'}
    outgoing_mode=['mf']
    incoming_hash='e'*64
    manual_out_hash='d'*64
    mocked=[]
    def route_local(route):
        parsed=urlparse(route.request.url)
        if parsed.hostname=='127.0.0.1' and parsed.port==18917 and parsed.path=='/api/cash/batches':
            route.fulfill(status=200,content_type='application/json',body=json.dumps({
                'success':True,'batches':[{'id':1,'status':'active','remaining_thb':200000,
                                          'purchase_rate':32}],
                'summary':{'total_remaining_thb':200000}}))
            return
        if parsed.hostname=='127.0.0.1' and parsed.port==18917 and parsed.path=='/api/cards/balance':
            route.fulfill(status=200,content_type='application/json',body=json.dumps({
                'success':True,'cards':[{'id':7,'bank_name':'T17 Bank',
                  'holder_name':'Synthetic','balance_thb':200000,'avg_rate':31.25}]}))
            return
        if parsed.hostname=='127.0.0.1' and parsed.port==18917 and parsed.path=='/api/transactions/outgoing':
            mocked.append(('outgoing',parse_qs(parsed.query)))
            limit=int(parse_qs(parsed.query).get('limit',['1000'])[0])
            available=[founder_tx] if outgoing_mode[0]=='founder' else outgoing[:outgoing_count[0]]
            route.fulfill(status=200,content_type='application/json',
                          body=json.dumps({'success':True,'available':available[:limit],
                                           'wallets_errors':[]}))
            return
        if parsed.hostname=='127.0.0.1' and parsed.port==18917 and parsed.path=='/api/tron/payout-tx':
            mocked.append(('founder-lookup',parse_qs(parsed.query)))
            route.fulfill(status=200,content_type='application/json',
                          body=json.dumps({'success':True,'amount_usdt':3205.13,
                            'from_address':'T17-founder-wallet','to_address':'T17-recipient'}))
            return
        if parsed.hostname=='127.0.0.1' and parsed.port==18917 and parsed.path=='/api/transactions/incoming':
            mocked.append(('custom-incoming',parse_qs(parsed.query)))
            route.fulfill(status=200,content_type='application/json',
                          body=json.dumps({'success':True,'available':[]}))
            return
        if parsed.hostname=='127.0.0.1' and parsed.port==18917 and parsed.path=='/api/wl-transactions':
            mocked.append(('custom-wl',parse_qs(parsed.query)))
            route.fulfill(status=200,content_type='application/json',body='[]')
            return
        if parsed.hostname=='127.0.0.1' and parsed.port==18917 and parsed.path=='/api/tx/lookup':
            h=parse_qs(parsed.query).get('hash',[''])[0]
            if h==incoming_hash:
                mocked.append(('incoming-lookup',h))
                route.fulfill(status=200,content_type='application/json',body=json.dumps({
                    'success':True,'amount_usdt':1234.56,'source':'mock'}))
                return
            if h==manual_out_hash:
                mocked.append(('manual-out-lookup',h))
                route.fulfill(status=200,content_type='application/json',body=json.dumps({
                    'success':True,'amount_usdt':250,'total_out_usdt':250.01,
                    'to_address':'T17-manual-out','source':'mock'}))
                return
            tx=next((x for x in outgoing if x['tx_hash']==h),None)
            if tx:
                mocked.append(('lookup',h))
                route.fulfill(status=200,content_type='application/json',body=json.dumps({
                    'success':True,'amount_usdt':tx['amount_usdt'],
                    'total_out_usdt':round(tx['amount_usdt']+0.01,2),
                    'to_address':tx['to_address'],'source':'mock'}))
                return
        if route.request.url.startswith('http://127.0.0.1:18917/'):
            route.continue_()
        else:
            blocked.append(route.request.url.split('?')[0])
            route.abort()
    context.route('**/*', route_local)
    page = context.new_page()
    crm_posts=[]
    stand_puts=[]
    page.on('request', lambda req: crm_posts.append(req.url)
            if req.method=='POST' and req.url.endswith('/api/deals') else None)
    page.on('request', lambda req: stand_puts.append(req.post_data_json)
            if req.method=='PUT' and req.url.endswith('/api/stand/state') else None)
    result = page.request.post('http://127.0.0.1:18917/api/auth/login',
                               data={'username':'karim','password':'synthetic-t17'})
    print('login:', result.status, result.json().get('success'))
    page.goto('http://127.0.0.1:18917/tasks', wait_until='domcontentloaded', timeout=20000)
    page.wait_for_function('standVer !== null && !standBusy',timeout=20000)
    routes=page.evaluate('''async()=>Object.fromEntries(await Promise.all(
      ['/tasks','/tasks/','/tasks/screens-data.js','/tasks/crm-draft-core.js?v=1',
       '/tasks/crm-draft-adapter.js?cache=2'].map(async path=>
         [path,(await fetch(path,{credentials:'same-origin'})).status])))''')
    print('same-origin routes:',routes)
    start_manual(page)
    first_manual_put=next((b for b in stand_puts if any(
        d.get('manualNew') for d in b.get('data',{}).get('deals',[]))),None)
    assert first_manual_put is not None
    first_d=next(d for d in first_manual_put['data']['deals'] if d.get('manualNew'))
    assert first_d['manual'] is True and first_d['step']=='manual'
    print('first actual manual PUT:',first_d['manual'],first_d['manualNew'],first_d['step'])
    host = page.locator('#crmDraftHost')
    host.locator('#createDealForm').wait_for(timeout=20000)
    host.locator('#managerSelect[data-upgraded="true"]').wait_for(state='attached',timeout=20000)
    print('form:', host.locator('#createDealForm').count())
    print('kind:', host.locator('#dealKindSelect').input_value())
    print('payin:', host.locator('#payinMethod option').count())
    print('source:', page.locator('#crmDraftSource').input_value())
    invalid=page.evaluate('''()=>{const id=S.edit,before=JSON.stringify(deal(id));
      crmDraftActive.root.getElementById('payinMethod').value='';
      editSave(id);return {same:JSON.stringify(deal(id))===before,edit:S.edit===id};}''')
    print('invalid required field atomic draft:',invalid)
    assert invalid=={'same':True,'edit':True}
    pick(host,'payinMethod','sber_reqs')
    crm=context.new_page()
    crm.goto('http://127.0.0.1:18917/crm',wait_until='domcontentloaded',timeout=20000)
    crm.evaluate('showSection("create")')
    crm.wait_for_function('document.querySelectorAll("#managerSelect option").length > 0',timeout=20000)
    crm.wait_for_function('document.querySelector("#managerSelect")?.dataset.upgraded === "true"',timeout=20000)
    pick(crm,'payinMethod','sber_reqs')
    snapshot='''el => [...el.querySelectorAll('label,button,select,input,textarea')]
      .filter(x => x.getClientRects().length > 0)
      .map(x => [x.tagName,x.id||x.name||'',(x.innerText||'').replace(/\\s+/g,' ').trim(),
        x.tagName==='SELECT'?[...x.options].map(o=>[o.value,o.textContent.trim()]):null,
        x.getAttribute('placeholder')||'',x.required])'''
    task_fields=host.locator('#createDealForm').evaluate(snapshot)
    crm_fields=crm.locator('#createDealForm').evaluate(snapshot)
    print('source form fields:',len(crm_fields),'task shadow fields:',len(task_fields),
          'exact same:',crm_fields==task_fields)
    if crm_fields!=task_fields:
        from itertools import zip_longest
        diffs=[(i,c,t) for i,(c,t) in enumerate(zip_longest(crm_fields,task_fields)) if c!=t]
        print('first form differences:',json.dumps(diffs[:5],ensure_ascii=False)[:1000])
    pick(crm,'sberKindSelect','')
    pick(host,'sberKindSelect','')
    crm.wait_for_function('document.querySelector("#sberIncomesAvail")?.textContent.includes("T17 Transfer")',timeout=10000)
    page.wait_for_function('document.querySelector("#crmDraftHost")?.shadowRoot?.getElementById("sberIncomesAvail")?.textContent.includes("T17 Transfer")',timeout=10000)
    sber_rows='''el=>[...el.querySelectorAll('div[style*="border-bottom"]')]
      .map(x=>x.innerText.replace(/\\s+/g,' ').trim())'''
    crm_sber=crm.locator('#sberIncomesAvail').evaluate(sber_rows)
    task_sber=host.locator('#sberIncomesAvail').evaluate(sber_rows)
    print('Sber all rows CRM/tasks:',crm_sber,task_sber,'same:',crm_sber==task_sber)
    assert crm_sber==task_sber and len(task_sber)==2
    assert host.locator('[onclick],[onchange],[oninput]').count()==0
    for query in ('70000000000','@t17fixture'):
        crm.locator('#clientSearchInput').fill(query)
        host.locator('#clientSearchInput').fill(query)
        crm.locator('#clientDropdown .client-name').first.wait_for(timeout=10000)
        host.locator('#clientDropdown .client-name').first.wait_for(timeout=10000)
        found=[crm.locator('#clientDropdown .client-name').first.inner_text(),
               host.locator('#clientDropdown .client-name').first.inner_text()]
        print('client search:',query,found)
        assert found==['T17 Existing','T17 Existing']
    crm.locator('#clientDropdown .client-dropdown-item').first.click()
    host.locator('#clientDropdown .client-dropdown-item').first.click()
    ids=[crm.locator('#clientIdHidden').input_value(),host.locator('#clientIdHidden').input_value()]
    print('client selected IDs:',ids)
    assert ids[0]==ids[1] and ids[0]
    for filter_value,expected_count in [('acquiring',1),('transfer',1),('',2)]:
        pick(crm,'sberKindSelect',filter_value)
        pick(host,'sberKindSelect',filter_value)
        crm.wait_for_function('(n)=>document.querySelectorAll("#sberIncomesAvail button").length===n',arg=expected_count)
        page.wait_for_function('(n)=>document.querySelector("#crmDraftHost")?.shadowRoot?.querySelectorAll("#sberIncomesAvail button").length===n',arg=expected_count)
        filtered_crm=crm.locator('#sberIncomesAvail').evaluate(sber_rows)
        filtered_task=host.locator('#sberIncomesAvail').evaluate(sber_rows)
        print('Sber filter:',filter_value or 'all',len(filtered_crm),filtered_crm==filtered_task)
        assert len(filtered_crm)==expected_count and filtered_crm==filtered_task
    crm.locator('#sberReqsGroup button[onclick="sberLoadIncomes()"]') .click()
    host.locator('#sberReqsGroup button[data-crm-call="sberLoadIncomes()"]') .click()
    crm.wait_for_function('document.querySelectorAll("#sberIncomesAvail button").length===2')
    page.wait_for_function('document.querySelector("#crmDraftHost")?.shadowRoot?.querySelectorAll("#sberIncomesAvail button").length===2')
    assert crm.locator('#sberIncomesAvail').evaluate(sber_rows)==host.locator('#sberIncomesAvail').evaluate(sber_rows)
    print('Sber refresh: same two rows')
    for _ in range(2):
        crm.locator('#sberIncomesAvail button').first.click()
        host.locator('#sberIncomesAvail button').first.click()
    parts_text=lambda scope: scope.locator('#sberPartsList').inner_text().replace('\n',' ').strip()
    crm_parts=parts_text(crm)
    task_parts=parts_text(host)
    amounts=[crm.locator('[name="payin_amount_rub"]').input_value(),
             host.locator('[name="payin_amount_rub"]').input_value()]
    print('Sber two chosen:',amounts,crm_parts==task_parts,task_parts[:300])
    assert amounts==['366000.00','366000.00'] and crm_parts==task_parts
    crm.locator('#sberPartsList span[onclick]').first.click()
    host.locator('#sberPartsList span[data-crm-action="sber-remove"]').first.click()
    removed=[crm.locator('[name="payin_amount_rub"]').input_value(),
             host.locator('[name="payin_amount_rub"]').input_value()]
    print('Sber × after first:',removed,parts_text(crm)==parts_text(host))
    assert removed==['266000.00','266000.00'] and parts_text(crm)==parts_text(host)
    crm.locator('#sberPartsList span[onclick]').first.click()
    host.locator('#sberPartsList span[data-crm-action="sber-remove"]').first.click()
    crm.close()
    form=host.locator('#createDealForm')
    pick(form,'payinMethod','crypto_direct')
    form.locator('#payinManualHash').fill(incoming_hash)
    form.locator('#payinManualHash').press('Tab')
    page.wait_for_function('document.querySelector("#crmDraftHost")?.shadowRoot?.querySelector("[name=payin_amount_usdt]")?.value==="1234.56"',timeout=10000)
    assert form.locator('#payinManualAmount').count()==0
    print('TRC20 incoming hash amount from mock network: 1234.56, no manual amount')
    form.locator('#payinManualHash').fill('')
    form.locator('#payinManualHash').press('Tab')
    form.locator('#clientSearchInput').fill('T17 synthetic freehold')
    pick(form,'dealKindSelect','mf_freehold')
    page.locator('#crmDraftTariff').select_option('bank')
    pick(form,'payinMethod','crypto_direct')
    form.locator('[name="payin_amount_usdt"]').fill('46000')
    form.locator('#fhInvoiceUsd').fill('45000')
    form.locator('#fhPurpose').fill('synthetic unit')
    page.locator('.card.edit-page > .row > button').first.click()
    result=page.evaluate('''() => {const d=S.deals.find(x=>x.client==='T17 synthetic freehold');
      return d&&{id:d.id,kind:d.kind,invoiceUsd:d.invoiceUsd,ippsTariff:d.ippsTariff,
        edit:S.edit,payload:crmPayload(d)};}''')
    print('freehold:',json.dumps(result,ensure_ascii=False,default=str)[:550])
    assert result and result['kind']=='Фрихолд' and result['invoiceUsd']==45000
    assert result['ippsTariff']=='bank' and result['edit'] is None
    assert result['payload']['transfer_fee_percent']==0.8
    assert not crm_posts,crm_posts
    open_edit(page,result['id'])
    host=page.locator('#crmDraftHost')
    crm_fh=context.new_page()
    crm_fh.goto('http://127.0.0.1:18917/crm',wait_until='domcontentloaded',timeout=20000)
    crm_fh.evaluate('showSection("create")')
    crm_fh.wait_for_function('document.querySelector("#dealKindSelect")?.dataset.upgraded === "true"')
    pick(crm_fh,'dealKindSelect','mf_freehold')
    pick(crm_fh,'payinMethod','crypto_direct')
    crm_fh.locator('[name="payin_amount_usdt"]').fill('46000')
    crm_fh.locator('#fhInvoiceUsd').fill('45000')
    crm_fh.locator('#fhFeePercent').fill('0.8')
    crm_fh.locator('#fhFeeFixed').fill('50')
    crm_fh.evaluate('fhRecalcNow()')
    page.evaluate('crmDraftActive.core.fhRecalcNow()')
    crm_fh.wait_for_function('document.querySelector("#fhSummary")?.textContent.includes("45")')
    page.wait_for_function('document.querySelector("#crmDraftHost")?.shadowRoot?.getElementById("fhSummary")?.textContent.includes("45")')
    fh_summaries=[crm_fh.locator('#fhSummary').inner_text(),host.locator('#fhSummary').inner_text()]
    print('freehold bank preview CRM/tasks:',fh_summaries[0]==fh_summaries[1])
    assert fh_summaries[0]==fh_summaries[1]
    crm_fh.close()
    page.locator('#crmDraftInvoiceCurrency').select_option('thb')
    page.locator('#crmDraftInvoiceThb').fill('1500000')
    with page.expect_response(lambda resp: resp.url.endswith('/api/stand/state')
                              and resp.request.method=='PUT' and resp.status==200):
        page.locator('.card.edit-page > .row > button').first.click()
    page.reload(wait_until='domcontentloaded')
    page.wait_for_function('standVer !== null && !standBusy',timeout=20000)
    bank_thb=page.evaluate('''id=>{const d=deal(id),p=crmPayload(d);return [
      d.invoiceUsd,d.invoiceThb,d.invoiceCurrency,d.ippsTariff,
      p.invoice_amount_usd,p.transfer_fee_percent,p.transfer_fee_fixed_usd]}''',result['id'])
    print('freehold bank THB invoice reload:',bank_thb)
    assert bank_thb==[45000,1500000,'thb','bank',45000,0.8,50]
    open_edit(page,result['id'])
    host=page.locator('#crmDraftHost')
    host.locator('#createDealForm').wait_for(timeout=20000)
    assert host.locator('#fhInvoiceUsd').input_value()=='45000'
    assert page.locator('#crmDraftTariff').input_value()=='bank'
    page.locator('#crmDraftTariff').select_option('soft')
    page.locator('.card.edit-page > .row > button').first.click()
    saved=page.evaluate('(id) => {const d=deal(id);return [d.kind,d.ippsTariff,crmPayload(d).transfer_fee_percent,S.edit]}',result['id'])
    print('freehold edit:',saved)
    assert saved==['Фрихолд','soft',1.5,None]
    assert not crm_posts,crm_posts
    open_edit(page,result['id'])
    host=page.locator('#crmDraftHost')
    host.locator('#createDealForm').wait_for(timeout=20000)
    page.locator('#crmDraftInvoiceCurrency').select_option('thb')
    page.locator('#crmDraftInvoiceThb').fill('1500000')
    with page.expect_response(lambda resp: resp.url.endswith('/api/stand/state')
                              and resp.request.method=='PUT' and resp.status==200):
        page.locator('.card.edit-page > .row > button').first.click()
    page.reload(wait_until='domcontentloaded')
    page.wait_for_function('standVer !== null && !standBusy',timeout=20000)
    thb=page.evaluate('''id=>{const d=deal(id),p=crmPayload(d);return {
      x:d.invoiceUsd,thb:d.invoiceThb,currency:d.invoiceCurrency,tariff:d.ippsTariff,
      payloadX:p.invoice_amount_usd,payloadPct:p.transfer_fee_percent,
      payloadFixed:p.transfer_fee_fixed_usd}}''',result['id'])
    print('freehold THB invoice reload:',thb)
    assert thb=={'x':45000,'thb':1500000,'currency':'thb','tariff':'soft',
                 'payloadX':45000,'payloadPct':1.5,'payloadFixed':50},thb
    assert not crm_posts,crm_posts
    with page.expect_response(lambda resp: resp.url.endswith('/api/stand/state')
                              and resp.request.method=='PUT'):
        page.evaluate('(id) => {deal(id).step="s11";save();}',result['id'])
    open_edit(page,result['id'])
    host=page.locator('#crmDraftHost')
    host.locator('#createDealForm').wait_for(timeout=20000)
    assert page.locator('#crmDraftTariff').is_disabled()
    assert host.locator('#fhInvoiceUsd').is_disabled()
    assert page.locator('#crmDraftInvoiceCurrency').is_disabled()
    print('freehold s11 UI basis disabled')
    page.evaluate('editClose()')
    # Historical locked fixture must be inserted directly into the synthetic
    # database: stand_state correctly rejects removing these keys over HTTP.
    db=appmod.get_session()
    try:
        row=appmod._stand_row(db,lock=True)
        state_data=json.loads(row.data)
        historical=next(d for d in state_data['deals'] if d['id']==result['id'])
        historical.pop('invoiceCurrency',None)
        historical.pop('invoiceThb',None)
        row.data=json.dumps(state_data,ensure_ascii=False)
        row.version+=1
        db.commit()
    finally:
        db.close()
    page.reload(wait_until='domcontentloaded')
    page.wait_for_function('standVer !== null && !standBusy',timeout=20000)
    open_edit(page,result['id'])
    host=page.locator('#crmDraftHost')
    host.locator('#createDealForm').wait_for(timeout=20000)
    host.locator('[name="notes"]').fill('legacy issued document note')
    with page.expect_response(lambda resp: resp.url.endswith('/api/stand/state')
                              and resp.request.method=='PUT' and resp.status==200):
        page.locator('.card.edit-page > .row > button').first.click()
    legacy=page.evaluate('''id=>{const d=deal(id);return {notes:d.notes,
      currency:Object.hasOwn(d,'invoiceCurrency'),thb:Object.hasOwn(d,'invoiceThb'),edit:S.edit}}''',result['id'])
    assert legacy=={'notes':'legacy issued document note','currency':False,'thb':False,'edit':None},legacy
    print('legacy issued document note save:',legacy)
    assert not crm_posts,crm_posts
    page.wait_for_function('!standBusy && !standPush',timeout=20000)
    start_manual(page)
    host=page.locator('#crmDraftHost')
    host.locator('#createDealForm').wait_for(timeout=20000)
    host.locator('#clientSearchInput').fill('T17 synthetic rental')
    pick(host,'dealKindSelect','mf_realty')
    page.locator('#crmDraftRealtySubtype').select_option('Аренда')
    pick(host,'payinMethod','crypto_direct')
    host.locator('[name="payin_amount_usdt"]').fill('1200')
    host.locator('#mfInvoiceThb').fill('35000')
    host.locator('#mfBuyRate').fill('33')
    host.locator('#mfSellRate').fill('32.5')
    host.locator('#mfPurpose').fill('rental fixture')
    host.locator('[name="notes"]').fill('rental note')
    page.locator('.card.edit-page > .row > button').first.click()
    rental=page.evaluate('''() => {const d=S.deals.find(x=>x.client==='T17 synthetic rental');
      return [d.id,d.kind,d.notes,crmPayload(d).deal_kind,crmPayload(d).sell_rate_thb_usdt];}''')
    print('rental:',rental)
    assert rental[1:]==['Аренда','rental note','mf_realty',32.5]
    open_edit(page,rental[0])
    host=page.locator('#crmDraftHost')
    host.locator('#createDealForm').wait_for(timeout=20000)
    assert page.locator('#crmDraftRealtySubtype').input_value()=='Аренда'
    pick(host,'dealKindSelect','exchange')
    pick(host,'dealKindSelect','mf_realty')
    assert page.locator('#crmDraftRealtySubtype').input_value()=='Аренда'
    page.locator('.card.edit-page > .row > button').first.click()
    retained=page.evaluate('(id) => [deal(id).kind,deal(id).notes,crmPayload(deal(id)).deal_kind]',rental[0])
    print('rental no-op edit:',retained)
    assert retained==['Аренда','rental note','mf_realty']
    assert not crm_posts,crm_posts
    page.wait_for_function('!standBusy && !standPush',timeout=20000)
    start_manual(page)
    host=page.locator('#crmDraftHost')
    host.locator('#createDealForm').wait_for(timeout=20000)
    host.locator('#clientSearchInput').fill('T17 synthetic leasehold')
    pick(host,'dealKindSelect','mf_realty')
    print('lease subtype initial:',page.locator('#crmDraftRealtySubtype').input_value(),
          page.evaluate('({id:S.edit,kind:deal(S.edit).kind,live:[...crmDraftLive.keys()]})'),
          page.locator('#crmDraftRealtySubtype').evaluate('e=>e.outerHTML'))
    assert page.locator('#crmDraftRealtySubtype').input_value()=='Лизхолд'
    assert host.locator('#mfSpread').input_value()==''
    assert host.locator('#mfSpread').get_attribute('placeholder')=='1.5'
    pick(host,'dealKindSelect','exchange')
    pick(host,'dealKindSelect','mf_realty')
    assert host.locator('#mfSpread').input_value()==''
    pick(host,'payinMethod','crypto_direct')
    host.locator('[name="payin_amount_usdt"]').fill('12000')
    host.locator('#mfInvoiceThb').fill('350000')
    host.locator('#mfBuyRate').fill('32')
    host.locator('#mfSellRate').fill('31.5')
    host.locator('#mfPurpose').fill('leasehold fixture')
    page.locator('.card.edit-page > .row > button').first.click()
    lease=page.evaluate('''()=>{const d=S.deals.find(x=>x.client==='T17 synthetic leasehold');
      return {id:d.id,kind:d.kind,spread:d.spread,sell:crmPayload(d).sell_rate_thb_usdt}}''')
    print('leasehold blank spread:',lease)
    assert lease['kind']=='Лизхолд' and lease['spread'] is None and lease['sell']==31.5
    open_edit(page,lease['id'])
    host=page.locator('#crmDraftHost')
    host.locator('#createDealForm').wait_for(timeout=20000)
    assert host.locator('#mfSpread').input_value()==''
    crm_mf=context.new_page()
    crm_mf.goto('http://127.0.0.1:18917/crm',wait_until='domcontentloaded',timeout=20000)
    crm_mf.evaluate('showSection("create")')
    crm_mf.wait_for_function('document.querySelector("#dealKindSelect")?.dataset.upgraded === "true"',timeout=20000)
    pick(crm_mf,'dealKindSelect','mf_realty')
    pick(crm_mf,'payinMethod','crypto_direct')
    crm_mf.locator('[name="payin_amount_usdt"]').fill('12000')
    crm_mf.locator('#mfInvoiceThb').fill('350000')
    crm_mf.locator('#mfBuyRate').fill('32')
    crm_mf.locator('#mfSellRate').fill('31.5')
    crm_mf.locator('#mfPurpose').fill('leasehold fixture')
    crm_mf.wait_for_function('document.querySelector("#mfPayoutPickerBtn")?.textContent.includes("200 исходящих")',timeout=20000)
    page.wait_for_function('document.querySelector("#crmDraftHost")?.shadowRoot?.getElementById("mfPayoutPickerBtn")?.textContent.includes("200 исходящих")',timeout=20000)
    # The same endpoint limit applies to both 250 cached rows and a 126-row
    # counterexample. Compare exact IDs and order, not only button counts.
    outgoing_count[0]=126
    crm_mf.evaluate('loadMfPayoutTx()')
    page.evaluate('crmDraftActive.core.loadMfPayoutTx()')
    crm_mf.wait_for_function('document.querySelector("#mfPayoutPickerBtn")?.textContent.includes("126 исходящих")')
    page.wait_for_function('document.querySelector("#crmDraftHost")?.shadowRoot?.getElementById("mfPayoutPickerBtn")?.textContent.includes("126 исходящих")')
    ids126=[crm_mf.evaluate('mfPayoutTxOptions.map(x=>x.tx_hash)'),
            page.evaluate('crmDraftActive.core.mfPayoutTxOptions.map(x=>x.tx_hash)')]
    assert ids126[0]==ids126[1] and len(ids126[0])==126
    outgoing_count[0]=250
    crm_mf.evaluate('loadMfPayoutTx()')
    page.evaluate('crmDraftActive.core.loadMfPayoutTx()')
    crm_mf.wait_for_function('document.querySelector("#mfPayoutPickerBtn")?.textContent.includes("200 исходящих")')
    page.wait_for_function('document.querySelector("#crmDraftHost")?.shadowRoot?.getElementById("mfPayoutPickerBtn")?.textContent.includes("200 исходящих")')
    ids200=[crm_mf.evaluate('mfPayoutTxOptions.map(x=>x.tx_hash)'),
            page.evaluate('crmDraftActive.core.mfPayoutTxOptions.map(x=>x.tx_hash)')]
    assert ids200[0]==ids200[1] and len(ids200[0])==200
    print('MF same snapshot IDs/order: cache 126/126, >limit 200/200 from 250')
    crm_mf.locator('#mfPayoutPickerBtn').click()
    host.locator('#mfPayoutPickerBtn').click()
    crm_count=crm_mf.locator('#mfPayoutPickerList label').count()
    task_count=host.locator('#mfPayoutPickerList label').count()
    print('MF outgoing rows CRM/tasks:',crm_count,task_count)
    assert (crm_count,task_count)==(200,200)
    assert host.locator('[onclick],[onchange],[oninput]').count()==0
    crm_mf.locator('#mfPayoutSearch').fill('address-1')
    host.locator('#mfPayoutSearch').fill('address-1')
    crm_filtered=crm_mf.locator('#mfPayoutPickerList label').all_inner_texts()
    task_filtered=host.locator('#mfPayoutPickerList label').all_inner_texts()
    print('MF address filter CRM/tasks:',len(crm_filtered),len(task_filtered),crm_filtered==task_filtered)
    if crm_filtered!=task_filtered:
        print('MF first row difference:',repr(crm_filtered[:2]),repr(task_filtered[:2]))
    assert len(crm_filtered)==50 and crm_filtered==task_filtered
    for query in ('100.05',format(5,'064x')):
        crm_mf.locator('#mfPayoutSearch').fill(query)
        host.locator('#mfPayoutSearch').fill(query)
        pairs=[crm_mf.locator('#mfPayoutPickerList label').all_inner_texts(),
               host.locator('#mfPayoutPickerList label').all_inner_texts()]
        print('MF filter query:',query,len(pairs[0]),pairs[0]==pairs[1])
        assert len(pairs[0])==1 and pairs[0]==pairs[1]
    crm_mf.locator('#mfPayoutSearch').fill('address-1')
    host.locator('#mfPayoutSearch').fill('address-1')
    for action in ('true','false'):
        crm_mf.locator(f'#mfPayoutPicker button[onclick="mfPayoutCheckAll({action})"]').click()
        host.locator(f'#mfPayoutPicker button[data-crm-call="mfPayoutCheckAll({action})"]').click()
        selected=[crm_mf.locator('#mfPayoutPickerSum').inner_text(),
                  host.locator('#mfPayoutPickerSum').inner_text()]
        print('MF', 'all' if action=='true' else 'clear',selected[0]==selected[1],selected[0])
        assert selected[0]==selected[1]
    for scope in (crm_mf,host):
        scope.locator('#mfPayoutPickerList input[type="checkbox"]').nth(0).check()
        scope.locator('#mfPayoutPickerList input[type="checkbox"]').nth(1).check()
    marked=[crm_mf.locator('#mfPayoutPickerSum').inner_text(),
            host.locator('#mfPayoutPickerSum').inner_text()]
    print('MF two marked:',marked)
    assert marked==['Отмечено: 2 · $200,06','Отмечено: 2 · $200,06']
    crm_mf.locator('#mfPayoutPicker button[onclick="addMfPayoutChecked()"]') .click()
    host.locator('#mfPayoutPicker button[data-crm-call="addMfPayoutChecked()"]') .click()
    crm_mf.wait_for_function('document.querySelector("#mfPayoutTxPoolBox")?.textContent.includes("Переводов: 2")')
    page.wait_for_function('document.querySelector("#crmDraftHost")?.shadowRoot?.getElementById("mfPayoutTxPoolBox")?.textContent.includes("Переводов: 2")')
    crm_out=crm_mf.locator('#mfPayoutTxPoolBox').inner_text()
    task_out=host.locator('#mfPayoutTxPoolBox').inner_text()
    print('MF two added text equal:',crm_out==task_out,task_out[-160:])
    assert crm_out==task_out and '$200,08' in task_out
    crm_mf.evaluate('mfRecalcNow()')
    crm_mf.wait_for_function('document.querySelector("#mfSummary")?.textContent.includes("350")',timeout=10000)
    page.wait_for_function('document.querySelector("#crmDraftHost")?.shadowRoot?.getElementById("mfSummary")?.textContent.includes("350")',timeout=10000)
    crm_money=crm_mf.locator('#mfSummary').inner_text().replace('\n',' ').strip()
    task_money=host.locator('#mfSummary').inner_text().replace('\n',' ').strip()
    print('MF same-fixture summary:',crm_money==task_money,task_money[:420])
    assert crm_money==task_money
    for spread,sale in [('0','32.0000'),('1.5','31.5200')]:
        crm_mf.locator('#mfSpread').fill(spread)
        host.locator('#mfSpread').fill(spread)
        crm_mf.wait_for_function('(sale)=>document.querySelector("#mfSellRate")?.value===sale',arg=sale)
        page.wait_for_function('(sale)=>document.querySelector("#crmDraftHost")?.shadowRoot?.getElementById("mfSellRate")?.value===sale',arg=sale)
        crm_mf.evaluate('mfRecalcNow()')
        page.wait_for_timeout(300)
        crm_money=crm_mf.locator('#mfSummary').inner_text().replace('\n',' ').strip()
        task_money=host.locator('#mfSummary').inner_text().replace('\n',' ').strip()
        print('MF spread summary:',spread,sale,crm_money==task_money)
        assert crm_money==task_money
        page.locator('.card.edit-page > .row > button').first.click()
        page.wait_for_function('!standBusy && !standPush',timeout=20000)
        saved_spread=page.evaluate('(id)=>[deal(id).spread,crmPayload(deal(id)).sell_rate_thb_usdt]',lease['id'])
        assert saved_spread==[float(spread),float(sale)],saved_spread
        open_edit(page,lease['id'])
        host=page.locator('#crmDraftHost')
        host.locator('#createDealForm').wait_for(timeout=20000)
        assert host.locator('#mfSpread').input_value()==spread
    for scope in (crm_mf,host):
        scope.locator('#mfSentThb').fill('360000')
        scope.locator('#mfPercent').fill('0.8')
    cleared=[(crm_mf.locator('#mfSentThb').input_value(),crm_mf.locator('#mfPercent').input_value()),
             (host.locator('#mfSentThb').input_value(),host.locator('#mfPercent').input_value())]
    print('MF percent clears sent CRM/tasks:',cleared)
    assert cleared==[('', '0.8'),('', '0.8')]
    crm_mf.locator('button[onclick="mfSuggestPercent()"]') .click()
    host.locator('button[data-crm-call="mfSuggestPercent()"]') .click()
    crm_mf.wait_for_function('document.querySelector("#mfPercent")?.value && document.querySelector("#mfPercent")?.value!=="0.8"')
    page.wait_for_function('document.querySelector("#crmDraftHost")?.shadowRoot?.getElementById("mfPercent")?.value && document.querySelector("#crmDraftHost")?.shadowRoot?.getElementById("mfPercent")?.value!=="0.8"')
    suggested=[crm_mf.locator('#mfPercent').input_value(),host.locator('#mfPercent').input_value()]
    print('MF suggested percent CRM/tasks:',suggested)
    assert suggested[0]==suggested[1]
    for scope in (crm_mf,host):
        scope.locator('#mfPayoutManual summary').click()
        scope.locator('#mfPayoutManualHash').fill(manual_out_hash)
        scope.locator('#mfPayoutManualAmount').fill('100')
    crm_mf.locator('#mfPayoutManual button[onclick="addMfPayoutManual()"]') .click()
    host.locator('#mfPayoutManual button[data-crm-call="addMfPayoutManual()"]') .click()
    crm_mf.wait_for_function('document.querySelector("#mfPayoutTxPoolBox")?.textContent.includes("Переводов: 3")')
    page.wait_for_function('document.querySelector("#crmDraftHost")?.shadowRoot?.getElementById("mfPayoutTxPoolBox")?.textContent.includes("Переводов: 3")')
    manual_text=[crm_mf.locator('#mfPayoutTxPoolBox').inner_text(),
                 host.locator('#mfPayoutTxPoolBox').inner_text()]
    print('MF manual partial amount:',manual_text[0]==manual_text[1],manual_text[1][-110:])
    assert manual_text[0]==manual_text[1] and '$300,08' in manual_text[1]
    page.locator('.card.edit-page > .row > button').first.click()
    page.wait_for_function('!standBusy && !standPush',timeout=20000)
    saved_out=page.evaluate('(id)=>deal(id).mfPayout.map(x=>[x.hash,x.amount])',lease['id'])
    print('MF saved outgoing:',saved_out)
    assert [x[1] for x in saved_out]==[100.02,100.06,100]
    assert not crm_posts,crm_posts
    crm_mf.close()
    start_manual(page)
    host=page.locator('#crmDraftHost')
    host.locator('#createDealForm').wait_for(timeout=20000)
    host.locator('#clientSearchInput').fill('T17 synthetic exchange')
    pick(host,'payinMethod','crypto_direct')
    host.locator('[name="payin_amount_usdt"]').fill('3300')
    pick(host,'payoutSource','binance')
    host.locator('#payoutAmountThb').fill('100000')
    host.locator('#binanceUsdt').fill('3205.13')
    profit=host.locator('#profitUsdt').input_value()
    print('exchange gross:',profit)
    assert profit=='94.87'
    host.locator('#agentsBlockStd').locator('xpath=following-sibling::button[1]').click()
    agents=host.locator('#agentsBlockStd > div').count()
    print('exchange agents:',agents)
    assert agents==1
    assert host.locator('[onclick],[onchange],[oninput]').count()==0
    crm_ex=context.new_page()
    crm_ex.goto('http://127.0.0.1:18917/crm',wait_until='domcontentloaded',timeout=20000)
    crm_ex.evaluate('showSection("create")')
    crm_ex.wait_for_function('document.querySelector("#payoutSource")?.dataset.upgraded === "true"',timeout=20000)
    pick(crm_ex,'payinMethod','crypto_direct')
    crm_ex.locator('[name="payin_amount_usdt"]').fill('3300')
    pick(crm_ex,'payoutSource','binance')
    crm_ex.locator('#payoutAmountThb').fill('100000')
    crm_ex.locator('#binanceUsdt').fill('3205.13')
    crm_ex.evaluate('stdAgentsAdd();calculateProfit()')
    money_fields='''el=>Object.fromEntries(['profitUsdt','referrerPayout','netProfit',
      'profitPercent','cashBatchCostUsdt'].map(id=>[id,el.querySelector('#'+id)?.value]))'''
    crm_exchange_money=crm_ex.locator('#createDealForm').evaluate(money_fields)
    task_exchange_money=host.locator('#createDealForm').evaluate(money_fields)
    print('exchange money CRM/tasks:',crm_exchange_money,task_exchange_money)
    assert crm_exchange_money==task_exchange_money
    for source,expected in [('cash_batch','$3125.00'),('bank_card','$3200.00')]:
        pick(crm_ex,'payoutSource',source)
        pick(host,'payoutSource',source)
        crm_ex.evaluate('calculateProfit()')
        page.evaluate('crmDraftActive.core.calculateProfit()')
        values=(crm_ex.locator('#cashBatchCostUsdt').input_value(),
                host.locator('#cashBatchCostUsdt').input_value())
        if source=='bank_card':
            print('card select CRM/tasks:',
                  crm_ex.locator('#bankCardSelect').evaluate('e=>[e.value,e.innerHTML,e.selectedIndex]'),
                  host.locator('#bankCardSelect').evaluate('e=>[e.value,e.innerHTML,e.selectedIndex]'))
        print('exchange source cost CRM/tasks:',source,values)
        assert values==(expected,expected)
    pick(crm_ex,'payoutSource','binance')
    pick(host,'payoutSource','binance')
    first_out=format(1,'064x')
    crm_ex.wait_for_function('(h)=>document.querySelector("#binanceTxSelect")?.innerHTML.includes(h)',arg=first_out)
    page.wait_for_function('(h)=>document.querySelector("#crmDraftHost")?.shadowRoot?.getElementById("binanceTxSelect")?.innerHTML.includes(h)',arg=first_out)
    pick(crm_ex,'binanceTxSelect',first_out)
    pick(host,'binanceTxSelect',first_out)
    binance_pick=[(crm_ex.locator('#binanceTxInput').input_value(),crm_ex.locator('#binanceUsdt').input_value()),
                  (host.locator('#binanceTxInput').input_value(),host.locator('#binanceUsdt').input_value())]
    print('exchange Binance picker CRM/tasks:',binance_pick)
    assert binance_pick==[(first_out,'100.01'),(first_out,'100.01')]
    crm_ex.locator('#binanceTxInput').fill('')
    host.locator('#binanceTxInput').fill('')
    crm_ex.locator('#binanceUsdt').fill('3205.13')
    host.locator('#binanceUsdt').fill('3205.13')
    crm_ex.close()
    page.locator('.card.edit-page > .row > button').first.click()
    exchange=page.evaluate('''() => {const d=S.deals.find(x=>x.client==='T17 synthetic exchange');
      return [d.id,d.paySrc,d.payout.thb,d.payout.usdt,crmPayload(d).deal_kind,
        crmPayload(d).payout_source,crmPayload(d).payout_amount_usdt];}''')
    print('exchange:',exchange)
    assert exchange[1:6]==['coins',100000,3205.13,'exchange','binance']
    for source,expected,cost in [('bank_card','bank_card',3200),
                                 ('cash_batch','cash_batch',3125)]:
        open_edit(page,exchange[0])
        host=page.locator('#crmDraftHost')
        pick(host,'payoutSource',source)
        page.locator('.card.edit-page > .row > button').first.click()
        page.wait_for_function('!standBusy && !standPush',timeout=20000)
        persisted=page.evaluate('''id=>{const d=deal(id),p=crmPayload(d);return {
          source:p.payout_source,cost:p.payout_amount_usdt,
          card:p.bank_card_id,profit:p.profit_usdt}}''',exchange[0])
        print('exchange source saved:',source,persisted)
        assert persisted['source']==expected and persisted['cost']==cost
        if source=='bank_card':assert persisted['card']==7
    assert not crm_posts,crm_posts
    start_manual(page)
    host=page.locator('#crmDraftHost')
    host.locator('#createDealForm').wait_for(timeout=20000)
    host.locator('#clientSearchInput').fill('T17 synthetic Sber deal')
    pick(host,'payinMethod','sber_reqs')
    pick(host,'sberKindSelect','')
    page.wait_for_function('document.querySelector("#crmDraftHost")?.shadowRoot?.querySelectorAll("#sberIncomesAvail button").length===2')
    host.locator('#sberIncomesAvail button').first.click()
    host.locator('#sberIncomesAvail button').first.click()
    host.locator('[name="payin_rate_rub_usdt"]').fill('90')
    page.locator('.card.edit-page > .row > button').first.click()
    page.wait_for_function('!standBusy && !standPush',timeout=20000)
    sber_id=page.evaluate('S.deals.find(x=>x.client==="T17 synthetic Sber deal")?.id')
    page.reload(wait_until='domcontentloaded')
    page.wait_for_function('standVer !== null && !standBusy',timeout=20000)
    sber_saved=page.evaluate('''id=>{const d=deal(id),p=crmPayload(d);return {
      parts:d.payinParts.map(x=>[x.uuid,x.amountRub,x.fee,x.net]),
      rub:d.amountRub,usdt:d.amountUsdt,payloadParts:p.payin_parts,
      payloadRub:p.payin_amount_rub}}''',sber_id)
    print('Sber save/reload CRM payload:',sber_saved)
    assert len(sber_saved['parts'])==2 and sber_saved['rub']==366000
    assert sber_saved['payloadRub']==366000 and len(sber_saved['payloadParts'])==2
    assert not crm_posts,crm_posts
    open_edit(page,sber_id)
    host=page.locator('#crmDraftHost')
    host.locator('#createDealForm').wait_for(timeout=20000)
    assert host.locator('#sberPartsList').inner_text().count('₽')>=2
    page.evaluate('editClose()')
    start_manual(page)
    host=page.locator('#crmDraftHost')
    host.locator('#createDealForm').wait_for(timeout=20000)
    draft_id=page.evaluate('S.edit')
    before_custom=page.evaluate('(id)=>JSON.stringify(deal(id))',draft_id)
    pick(host,'dealKindSelect','custom')
    assert page.evaluate('(id)=>JSON.stringify(deal(id))',draft_id)==before_custom
    host.locator('#clientSearchInput').fill('T17 synthetic custom')
    pick(host,'customPayinCurrency','RUB')
    host.locator('#customPayinAmount').fill('92000')
    host.locator('#customPayinRate').fill('92')
    pick(host,'customPayoutCurrency','THB')
    host.locator('#customPayoutAmount').fill('30000')
    host.locator('#customPayoutRate').fill('31.5')
    pick(host,'customPayinMethod','sber_reqs')
    pick(host,'customPayoutMethod','transfer')
    host.locator('#customNotes').fill('custom fixture')
    host.locator('#agentsBlockCustom').locator('xpath=following-sibling::button[1]').click()
    host.locator('#agentsBlockCustom select').first.select_option(label='T17 Agent')
    task_custom_money=[host.locator('#customProfitUsdt').input_value(),
                       host.locator('#customNetProfit').input_value()]
    crm_c=context.new_page()
    captured=[]
    def capture_custom(route):
        captured.append(route.request.post_data_json)
        route.fulfill(status=400,content_type='application/json',body='{"success":false,"error":"synthetic capture"}')
    crm_c.route('http://127.0.0.1:18917/api/deals',capture_custom)
    crm_c.goto('http://127.0.0.1:18917/crm',wait_until='domcontentloaded',timeout=20000)
    crm_c.evaluate('showSection("create")')
    crm_c.wait_for_function('document.querySelector("#dealKindSelect")?.dataset.upgraded === "true"',timeout=20000)
    pick(crm_c,'dealKindSelect','custom')
    pick(crm_c,'customPayinCurrency','RUB')
    crm_c.locator('#customPayinAmount').fill('92000')
    crm_c.locator('#customPayinRate').fill('92')
    pick(crm_c,'customPayoutCurrency','THB')
    crm_c.locator('#customPayoutAmount').fill('30000')
    crm_c.locator('#customPayoutRate').fill('31.5')
    pick(crm_c,'customPayinMethod','sber_reqs')
    crm_c.wait_for_function('document.querySelector("#sberIncomesAvailC")?.textContent.includes("T17 Transfer")')
    page.wait_for_function('document.querySelector("#crmDraftHost")?.shadowRoot?.getElementById("sberIncomesAvailC")?.textContent.includes("T17 Transfer")')
    custom_sber_crm=crm_c.locator('#sberIncomesAvailC').inner_text().strip()
    custom_sber_task=host.locator('#sberIncomesAvailC').inner_text().strip()
    print('custom Sber CRM/tasks:',custom_sber_crm==custom_sber_task,custom_sber_task[:160])
    assert custom_sber_crm==custom_sber_task
    pick(crm_c,'customPayoutMethod','transfer')
    crm_c.locator('#customNotes').fill('custom fixture')
    crm_c.evaluate('customAgentsAdd()')
    crm_c.locator('#agentsBlockCustom select').first.select_option(label='T17 Agent')
    crm_custom_money=[crm_c.locator('#customProfitUsdt').input_value(),
                      crm_c.locator('#customNetProfit').input_value()]
    print('custom CRM/tasks money:',crm_custom_money,task_custom_money)
    assert task_custom_money==crm_custom_money and task_custom_money[0]!='$0.00'
    crm_c.evaluate('createCustomDeal()')
    for _ in range(30):
        if captured:break
        crm_c.wait_for_timeout(100)
    assert captured
    host.locator('#customDealSubmit').click()
    page.wait_for_function('!standBusy && !standPush',timeout=20000)
    custom_id=page.evaluate('S.deals.find(x=>x.client==="T17 synthetic custom")?.id')
    page.reload(wait_until='domcontentloaded')
    page.wait_for_function('standVer !== null && !standBusy',timeout=20000)
    custom_saved=page.evaluate('''id=>{const d=deal(id),p=crmPayload(d);
      return {marker:d.custom,fields:d.customData,payload:p}}''',custom_id)
    fields=['is_custom','custom_payin_currency','custom_payin_amount','custom_payin_rate',
      'payin_amount_usdt','custom_payout_currency','custom_payout_amount',
      'custom_payout_rate','payout_amount_usdt','profit_usdt','net_profit_usdt',
      'payin_method','payout_method','payout_source','notes']
    fields.append('agents')
    compared={k:[captured[0].get(k),custom_saved['payload'].get(k)] for k in fields}
    print('custom save/reload source payload:',custom_saved['marker'],compared)
    assert custom_saved['marker'] is True and all(a==b for a,b in compared.values())
    assert not crm_posts,crm_posts
    page.evaluate('(id)=>openDeal(id)',custom_id)
    final_button=page.locator('button:has-text("Сохранить в CRM")')
    assert final_button.count()==1
    has_origin=page.evaluate('(id)=>deal(id).originMode==="manual"',custom_id)
    assert final_button.is_disabled() != has_origin
    open_edit(page,custom_id)
    host=page.locator('#crmDraftHost')
    assert host.locator('#customPayinAmount').input_value()=='92000'
    assert host.locator('#customPayoutAmount').input_value()=='30000'
    host.locator('#customPayoutAmount').fill('32000')
    page.evaluate('editClose()')
    assert page.evaluate('(id)=>deal(id).customData.payoutAmount',custom_id)==30000
    open_edit(page,sber_id)
    assert page.locator('#crmDraftHost #sberPartsList').inner_text().count('₽')>=2
    page.evaluate('editClose()')
    open_edit(page,custom_id)
    host=page.locator('#crmDraftHost')
    assert host.locator('#sberPartsList').inner_text().count('₽')==0
    assert host.locator('#agentsBlockCustom > div').count()==1
    authoritative=page.evaluate('''async()=>{const r=await fetch('/api/stand/state',
      {credentials:'same-origin'});return {status:r.status,...await r.json()}}''')
    assert authoritative.get('version') is not None,authoritative
    old_note=page.evaluate('(id)=>deal(id).notes',custom_id)
    blocked_put=[]
    def reject_once(route):
        if route.request.method=='PUT' and not blocked_put:
            blocked_put.append(True)
            route.fulfill(status=409,content_type='application/json',body=json.dumps({
                'success':False,'error':'synthetic_locked','version':authoritative['version'],
                'data':authoritative['data']}))
        else:
            route.continue_()
    page.route('http://127.0.0.1:18917/api/stand/state',reject_once)
    host.locator('#customNotes').fill('must not persist')
    page.locator('.card.edit-page > .row > button').first.click()
    page.wait_for_function('!standBusy && !standPush',timeout=20000)
    page.unroute('http://127.0.0.1:18917/api/stand/state',reject_once)
    after_reject=page.evaluate('''async()=>{const r=await fetch('/api/stand/state',
      {credentials:'same-origin'});return {status:r.status,...await r.json()}}''')
    assert blocked_put and after_reject['version']==authoritative['version']
    assert page.evaluate('(id)=>deal(id).notes',custom_id)==old_note
    print('custom cancel/next-mount/409: no field leak, server version and board unchanged')
    crm_c.close()
    outgoing_mode[0]='founder'
    start_manual(page)
    host=page.locator('#crmDraftHost')
    host.locator('#clientSearchInput').fill('T17 synthetic founder')
    pick(host,'payinMethod','crypto_direct')
    host.locator('[name="payin_amount_usdt"]').fill('3300')
    pick(host,'payoutSource','founder_personal')
    host.locator('#payoutAmountThb').fill('100000')
    page.wait_for_function('(h)=>document.querySelector("#crmDraftHost")?.shadowRoot?.getElementById("payoutTxSelect")?.innerHTML.includes(h)',arg=founder_hash)
    crm_f=context.new_page()
    crm_f.goto('http://127.0.0.1:18917/crm',wait_until='domcontentloaded',timeout=20000)
    crm_f.evaluate('showSection("create")')
    crm_f.wait_for_function('document.querySelector("#payoutSource")?.dataset.upgraded === "true"',timeout=20000)
    pick(crm_f,'payinMethod','crypto_direct')
    crm_f.locator('[name="payin_amount_usdt"]').fill('3300')
    pick(crm_f,'payoutSource','founder_personal')
    crm_f.locator('#payoutAmountThb').fill('100000')
    crm_f.wait_for_function('(h)=>document.querySelector("#payoutTxSelect")?.innerHTML.includes(h)',arg=founder_hash)
    pick(crm_f,'payoutTxSelect',founder_hash)
    pick(host,'payoutTxSelect',founder_hash)
    founder_text=[crm_f.locator('#payoutTxPoolBox').inner_text().strip(),
                  host.locator('#payoutTxPoolBox').inner_text().strip()]
    founder_money=[crm_f.locator('#profitUsdt').input_value(),
                   host.locator('#profitUsdt').input_value()]
    print('founder payout CRM/tasks:',founder_text[0]==founder_text[1],founder_money)
    assert founder_text[0]==founder_text[1] and founder_money==['94.87','94.87']
    crm_f.locator('#payoutNoConversion').check()
    host.locator('#payoutNoConversion').check()
    assert crm_f.locator('#payoutTxPoolBox').inner_text()==host.locator('#payoutTxPoolBox').inner_text()==''
    crm_f.locator('#noConvUsdt').fill('3205.13')
    host.locator('#noConvUsdt').fill('3205.13')
    assert crm_f.locator('#noConvRateInfo').inner_text()==host.locator('#noConvRateInfo').inner_text()
    assert crm_f.locator('#profitUsdt').input_value()==host.locator('#profitUsdt').input_value()=='94.87'
    print('founder own-THB no-conversion CRM/tasks: same cost/rate/gross; tx pool cleared')
    crm_f.locator('#payoutNoConversion').uncheck()
    host.locator('#payoutNoConversion').uncheck()
    pick(crm_f,'payoutTxSelect',founder_hash)
    pick(host,'payoutTxSelect',founder_hash)
    crm_f.locator('#payoutSettledByPayin').check()
    host.locator('#payoutSettledByPayin').check()
    settled_hints=[crm_f.locator('#payoutSettledHint').inner_text(),
                   host.locator('#payoutSettledHint').inner_text()]
    print('founder settled hints:',settled_hints,host.locator('#payoutSettledHint').evaluate(
      'e=>({text:e.textContent,display:getComputedStyle(e).display,parent:getComputedStyle(e.parentElement).display,checked:e.getRootNode().getElementById("payoutSettledByPayin").checked,touched:e.getRootNode().getElementById("payoutSettledByPayin").dataset.touched})'))
    assert settled_hints[0]==settled_hints[1]
    page.locator('.card.edit-page > .row > button').first.click()
    page.wait_for_function('!standBusy && !standPush',timeout=20000)
    founder_saved=page.evaluate('''()=>{const d=S.deals.find(x=>x.client==='T17 synthetic founder');
      const p=crmPayload(d);return {hash:d.payout.hashes[0],source:p.payout_source,
        cost:p.payout_amount_usdt,links:p.payout_tx_hashes,needs:p.needs_reimbursement};}''')
    print('founder saved:',founder_saved)
    assert founder_saved['hash']['hash']==founder_hash and founder_saved['cost']==3205.13
    assert founder_saved['source']=='founder_personal' and founder_saved['links'][0]['from_address']=='T17-founder-wallet'
    assert founder_saved['needs'] is False
    assert not crm_posts,crm_posts
    crm_f.close()
    print('blocked external attempts:',blocked)
    browser.close()
