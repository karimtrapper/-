"""Регрессия MF-268: валютная пара обязана проходить через весь комплект."""
import io
import shutil
import subprocess
from pathlib import Path
from datetime import datetime

import pytest
from docx import Document
import doc_routes
import docgen

FIELDS = {'client_name_ru': 'Тестовый Клиент', 'client_name_en': 'Test Client',
          'client_passport_no': '000000268', 'invoice_no': 'TEST-1',
          'invoice_date': '10.09.2026', 'invoice_amount': '18550', 'invoice_currency': 'THB',
          'project_name': 'Test property', 'unit_no': '1', 'recipient_name': 'Test Recipient',
          'recipient_bank': 'Test Bank', 'recipient_account': '123456',
          'contract_ref': 'Test instruction'}
WHEN = datetime(2026, 9, 10)


def test_real_javascript_document_rate_forms_and_payloads():
    """Исполняем настоящий JS обеих форм, а не проверяем наличие формулы в тексте."""
    node=shutil.which('node')
    if not node:
        pytest.skip('Для JS-регрессии требуется Node.js')
    html=(Path(__file__).resolve().parents[1]/'static/crm/crm.html').read_text()
    code=html[html.index('const DOCS_TYPE_LABEL'):].split('</script>')[0]
    checks=r'''
    const assert=require('node:assert/strict');
    const elements={};
    const document={getElementById:id=>elements[id]??={value:'',style:{},classList:{remove(){},add(){}},disabled:false}};
    let sent;
    const fetch=async(url,options)=>{sent=JSON.parse(options.body);return {json:async()=>({success:false,error:'test stop'})};};
    '''+code+r'''
    (async()=>{
        for(const pair of DOCS_PAIRS){
            docsState.pair=pair.k;
            docsState.current={money:{pair:pair.k}};
            const direct=pair.k==='USDT_THB';
            for(const prefix of ['docm_','docp_']){
                const recalc=prefix==='docm_'?docsRecalc:docsRecalcPay;
                const put=(key,value)=>document.getElementById(prefix+key).value=value;
                const get=key=>document.getElementById(prefix+key).value;
                put('total_payin','575');put('transfer_amount','18550');put('rate','');
                recalc('payout');
                assert.equal(get('rate'),direct?'32.260870':'0.030997');
                put('rate',direct?'32,26':'2,78');recalc('rate');
                assert.equal(get('transfer_amount'),direct?'18549.50':(575/2.78).toFixed(pair.out==='USDT'?6:2));
                put('transfer_amount','');recalc('payin');
                assert.equal(get('transfer_amount'),direct?'18549.50':(575/2.78).toFixed(pair.out==='USDT'?6:2));
            }
            assert.equal(docsCollect().money.rate_basis,direct?'transfer_per_payin':'payin_per_transfer');
            await docsSubmitPayment(1);
            assert.equal(sent.money.rate_basis,direct?'transfer_per_payin':'payin_per_transfer');
        }
        const old={rate:'0.030997',total_payin:'575',transfer_amount:'18550'};
        assert.equal(docsDisplayRate(old,'USDT_THB').toFixed(6),'32.260870');
        assert.equal(old.rate,'0.030997');
        assert.equal(docsDisplayRate({rate:'0.030998',total_payin:'61.997',transfer_amount:'2000'},'USDT_THB').toFixed(6),'32.259625');
        assert.equal(docsDisplayRate({rate:'0.03099910102607024396292507517',total_payin:'1',transfer_amount:'32.26'},'USDT_THB').toFixed(6),'32.259000');
        assert.equal(docsDisplayRate({rate:'32.259',rate_basis:'transfer_per_payin'},'USDT_THB'),32.259);
        assert.equal(docsRateUnit('USDT_THB'),'THB за 1 USDT');
        assert.equal(docsRateUnit('RUB_THB'),'RUB / THB');
        console.log('both forms, six pairs, payloads and historical display PASS');
    })().catch(e=>{console.error(e);process.exit(1)});
    '''
    result=subprocess.run([node,'-e',checks],capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stdout+result.stderr


def route(pair='USDT_THB', method='usdt'):
    incoming, outgoing = doc_routes.PAIRS[pair]
    return dict(pair=pair, payin_currency=incoming, transfer_currency=outgoing,
                payin_method=method, total_payin='575', transfer_amount='18550', rate='0.030997',
                payin_recipient='MF Corporation Company Limited', payin_recipient_role='Agent',
                payin_network='TRON (TRC-20)', payin_wallet='T'+'A'*33,
                payin_details='Test bank or SBP details',
                cash_network='Test cash network', cash_location='Test address',
                cash_contact='Test cashier', cash_datetime='10.09.2026 15:00 GMT+7',
                payout_network='Ethereum (ERC-20)', payout_wallet='0x'+'1'*40,
                rate_valid_until='10.09.2026 23:59 GMT+7')


def text(data):
    d = Document(io.BytesIO(data))
    return '\n'.join([p.text for p in d.paragraphs] + [c.text for c in docgen._unique_cells(d)])


@pytest.mark.parametrize('pair,method,kind', [
    ('USDT_THB','usdt','leasehold'), ('RUB_THB','bank','leasehold'),
    ('RUB_THB','sbp','rental'), ('RUB_THB','cash','leasehold'),
    ('RUB_USDT','bank','payment'), ('RUB_USDT','sbp','payment'),
    ('RUB_USDT','cash','payment'), ('USD_THB','bank','payment'),
    ('USD_THB','cash','payment'), ('USDT_USD','usdt','payment'),
    ('RUB_USD','bank','payment'),
])
def test_route_in_every_document(pair, method, kind):
    m = route(pair, method)
    agreement, _ = docgen.build_agreement(kind, FIELDS, m, when=WHEN)
    addendum = docgen.build_addendum(kind, FIELDS, m, 'MF-1', 'MF-0', 1, when=WHEN)
    invoice = docgen.build_commercial_invoice(FIELDS, m, 'MF-1', kind, when=WHEN)
    assert len(Document(io.BytesIO(invoice)).inline_shapes) >= 2  # подпись и печать Агента
    for data in (agreement, addendum, invoice):
        assert docgen.check(data) == []
        assert '40807' not in text(data) and '9909726886' not in text(data)
        if m['payin_currency'] != 'RUB':
            assert 'RUB' not in text(data)
        if kind == 'payment':
            assert 'leasehold' not in text(data).lower()
    assert ('THB за 1 USDT' if pair == 'USDT_THB' else pair.replace('_', '/')) in text(agreement)
    assert doc_routes.amount('575', m['payin_currency']) in text(addendum)
    assert doc_routes.amount('18550', m['transfer_currency']) in text(addendum)
    if method == 'usdt':
        assert m['payin_wallet'] in text(invoice)
        assert m['payin_network'] in text(invoice)
        assert 'TXID' in text(invoice)
    if method == 'cash':
        assert m['cash_network'] in text(invoice)
    if m['transfer_currency'] == 'USDT':
        assert m['payout_wallet'] in text(addendum)
        assert m['payout_network'] in text(addendum)
        assert 'TXID' in text(agreement)
        assert 'Agent to the Bank' not in text(agreement)


@pytest.mark.parametrize('pair,method', [('USDT_THB','bank'), ('RUB_THB','usdt'), ('USD_THB','sbp')])
def test_rejects_incompatible_currency_and_method(pair, method):
    with pytest.raises(ValueError):
        doc_routes.normalize(route(pair, method))


def test_missing_network_prevents_issuing_invoice():
    m = route()
    m['payin_network'] = ''
    assert 'payin_network' in doc_routes.validate(m, 'leasehold')


def test_rounding_and_amount_validation():
    m=route()
    assert doc_routes.validate(m, 'leasehold') == []
    m['rate']='32.26'
    with pytest.raises(ValueError, match='Курс не соответствует'):
        doc_routes.validate(m, 'leasehold')


@pytest.mark.parametrize('incoming,outgoing,rate', [
    ('575', '18550', '32.260870'),
    ('575', '18548.92', '32.259'),
    ('0.123456', '3.98', '32.26'),
    ('1000000', '32260000', '32.26'),
])
def test_direct_rate_accepts_amounts_or_rounded_quote(incoming, outgoing, rate):
    m=route()
    m.update(total_payin=incoming, transfer_amount=outgoing, rate=rate,
             rate_basis=doc_routes.DIRECT_RATE)
    assert doc_routes.validate(m, 'leasehold') == []
    assert doc_routes.rate_text(m) == f'1 USDT = {rate} THB'
    m['transfer_amount']='100'
    with pytest.raises(ValueError, match='Курс не соответствует'):
        doc_routes.validate(m, 'leasehold')


def test_unmarked_old_rate_is_not_reinterpreted_or_mutated():
    old=route()
    original=dict(old)
    normalized=doc_routes.normalize(old)
    assert normalized['rate_basis']==doc_routes.INVERSE_RATE
    assert doc_routes.normalize(normalized)==normalized
    assert doc_routes.rate_text(old)=='1 USDT = 32.260870 THB'
    assert old==original


def test_precise_historical_quote_not_replaced_by_rounded_payout_ratio():
    old=route()
    old.update(total_payin='1',transfer_amount='32.26',rate='0.03099910102607024396292507517')
    assert doc_routes.validate(old,'leasehold')==[]
    assert doc_routes.rate_text(old)=='1 USDT = 32.259000 THB'


def test_historical_js_halfway_rounding_matches_display():
    old=route()
    old.update(total_payin='61.997',transfer_amount='2000',rate='0.030998')
    assert doc_routes.validate(old,'leasehold')==[]
    assert doc_routes.rate_text(old)=='1 USDT = 32.259625 THB'


@pytest.mark.parametrize('rate', ['0.030997', '32.260870'])
def test_direct_rate_is_consistent_through_documents(rate):
    m=route()
    if rate != '0.030997':
        m.update(rate=rate, rate_basis=doc_routes.DIRECT_RATE)
    a=text(docgen.build_agreement('leasehold',FIELDS,m,when=WHEN)[0])
    b=text(docgen.build_addendum('leasehold',FIELDS,m,'MF-1','MF-0',1,when=WHEN))
    assert 'курс THB за 1 USDT' in a
    assert 'exchange rate in THB per 1 USDT' in a
    assert b.count('1 USDT = 32.260870 THB')==3
    assert 'USDT/THB' not in a+b and '0.030997' not in a+b


@pytest.mark.parametrize('basis', ['wrong', '', None])
def test_unknown_rate_basis_rejected(basis):
    with pytest.raises(ValueError, match='направление курса'):
        doc_routes.normalize(dict(route(),rate_basis=basis))


def test_direct_rate_cannot_change_other_pair_semantics():
    with pytest.raises(ValueError, match='только для USDT'):
        doc_routes.normalize(dict(route('RUB_THB','bank'), rate_basis=doc_routes.DIRECT_RATE))


@pytest.mark.parametrize('pair,payout,quoted_rate', [
    ('RUB_THB','359.71','2.78'),
    ('RUB_USDT','11.716187','85.352'),
])
def test_quoted_rate_allows_normal_payout_rounding(pair,payout,quoted_rate):
    m=route(pair,'bank')
    m.update(total_payin='1000',transfer_amount=payout,rate=quoted_rate)
    assert doc_routes.validate(m,'payment') == []
    m['transfer_amount']='500'
    with pytest.raises(ValueError, match='Курс не соответствует'):
        doc_routes.validate(m,'payment')


@pytest.mark.parametrize('invalid', ['NaN','Infinity','-1','0','575USD','575junk'])
def test_bad_amounts_rejected(invalid):
    with pytest.raises(ValueError):
        doc_routes.amount(invalid, 'USDT')


def test_usdt_precision_not_silently_rounded():
    assert doc_routes.amount('575.123456','USDT') == 'USDT 575.123456'
    with pytest.raises(ValueError):
        doc_routes.amount('575.1234567','USDT')
    m=route()
    m['total_payin']='575.1234567'
    with pytest.raises(ValueError, match='знаков'):
        doc_routes.validate(m,'leasehold')


def test_freehold_usdt_to_usd():
    m=route('USDT_USD','usdt')
    m.update(usd_equivalent='USD 18550',rate_source='Test source',
             thb_credit_status='Test credit',developer_confirmation='Test confirmation')
    assert doc_routes.validate(m,'freehold') == []
    a=docgen.build_agreement('freehold',FIELDS,m,when=WHEN)[0]
    b=docgen.build_addendum('freehold',FIELDS,m,'MF-1','MF-0',1,when=WHEN)
    assert docgen.check(a) == docgen.check(b) == []
    assert 'RUB' not in text(a)+text(b)
    assert 'USD 18 550.00' in text(b)


def test_sqlite_migration_preserves_documents_and_foreign_keys(tmp_path, monkeypatch):
    import app as module
    from sqlalchemy import create_engine, text as sql
    from sqlalchemy.schema import CreateTable
    engine=create_engine('sqlite:///'+str(tmp_path/'old.db'))
    monkeypatch.setattr(module,'engine',engine)
    monkeypatch.setattr(module,'DATABASE_URL','sqlite:///test')
    ddl=str(CreateTable(module.Agreement.__table__).compile(engine))
    ddl=ddl.replace('CONSTRAINT uq_agreement_client_route UNIQUE (client_key, deal_type, route_key)',
                    'CONSTRAINT uq_agreement_client_key_type UNIQUE (client_key, deal_type)')
    with engine.begin() as c:
        c.execute(sql('CREATE TABLE clients (id INTEGER PRIMARY KEY)'))
        c.execute(sql(ddl))
        c.execute(sql("INSERT INTO agreements (id,client_name,client_key,deal_type,route_key,number) VALUES (1,'Test','268','leasehold','legacy','MF-1')"))
        c.execute(sql('CREATE TABLE agreement_docs (id INTEGER PRIMARY KEY, agreement_id INTEGER REFERENCES agreements(id), data BLOB)'))
        c.execute(sql("INSERT INTO agreement_docs VALUES (1,1,X'010203')"))
    module._rebuild_agreements_without_name_constraint()
    module._rebuild_agreements_without_name_constraint()
    with engine.connect() as c:
        assert c.execute(sql('SELECT data FROM agreement_docs')).scalar() == b'\x01\x02\x03'
        assert c.execute(sql('PRAGMA foreign_key_check')).all() == []
        c.execute(sql("INSERT INTO agreements (id,client_name,client_key,deal_type,route_key,number) VALUES (2,'Test','268','leasehold','USDT_THB:usdt','MF-2')"))
        assert c.execute(sql('SELECT count(*) FROM agreements')).scalar() == 2
