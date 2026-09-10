"""Регрессия MF-268: валютная пара обязана проходить через весь комплект."""
import io
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
    for data in (agreement, addendum, invoice):
        assert docgen.check(data) == []
        assert '40807' not in text(data) and '9909726886' not in text(data)
        if m['payin_currency'] != 'RUB':
            assert 'RUB' not in text(data)
        if kind == 'payment':
            assert 'leasehold' not in text(data).lower()
    assert pair.replace('_', '/') in text(agreement)
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
