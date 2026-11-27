"""Independent synthetic acceptance probes; no external transport."""
import json
import pytest
import docparse
import stand_egress
import app as appmod
from tests.test_stand_docs import stand, _auto_deal, _auto_fields, _text

@pytest.mark.parametrize('reverse',[False,True])
def test_conflicting_seller_visible_independent_of_upload_order(reverse):
    a={'_kind':'vehicle_contract','_file':'contract','seller_name':'QA Seller A Ltd'}
    b={'_kind':'auto_invoice','_file':'invoice','seller_name':'QA Seller B Ltd'}
    result=docparse.merge([b,a] if reverse else [a,b])
    assert 'seller_name' in result['conflicts'],result

@pytest.mark.parametrize('kind',['vehicle_contract','auto_invoice'])
def test_auto_prompt_does_not_ask_thai_property(monkeypatch,kind):
    seen=[]
    monkeypatch.setattr(stand_egress,'docparse_request_authorized',lambda:True)
    def fake(payload,**kwargs):
        seen.append(payload)
        return 200,{'choices':[{'message':{'content':'{}'}}]},None
    monkeypatch.setattr(stand_egress,'docparse_post',fake)
    docparse._call('synthetic',[], 'synthetic',kind=kind,stand=True)
    assert 'недвижимости в Таиланде' not in seen[0]['messages'][0]['content'][0]['text']

@pytest.mark.parametrize('bad',[{}, {'file':'fake.pdf','mime':'application/pdf'}, {'storageId':999999,'file':'fake.pdf','mime':'application/pdf'}, {'data':'data:application/pdf;base64,eA==','mime':'application/pdf','file':'fake.pdf'}])
def test_missing_real_vehicle_file_refused(stand,bad):
    d=_auto_deal(980)
    d['files']['vehicle_contract']=[bad]
    stand.put_board([d])
    r=stand.post('/api/stand/docs/issue',json={'dealId':980,'docFields':_auto_fields()})
    assert r.status_code==400,r.json
    assert r.json['error']=='missing_vehicle_contract'


def test_invoice_date_required(stand):
    stand.put_board([_auto_deal(981)])
    r=stand.post('/api/stand/docs/issue',json={'dealId':981,'docFields':_auto_fields(invDate='')})
    assert r.status_code==400,r.json
    assert 'invDate' in r.json['fields']


def test_seller_address_confirmed_is_not_dropped(stand):
    d=_auto_deal(982)
    d['docParse']['fields']['seller_address']='123 Synthetic Seller Address'
    stand.put_board([d])
    r=stand.post('/api/stand/docs/issue',json={'dealId':982,'docFields':_auto_fields(sellerAddress='123 Synthetic Seller Address')})
    assert r.status_code==200,r.json
    text='\n'.join(_text(stand,e['docId']) for e in r.json['issued'])
    assert '123 Synthetic Seller Address' in text

@pytest.mark.parametrize('stage',['Остаток после аванса','Не аванс, полная оплата'])
def test_pending_vin_not_allowed_for_final_payment(stand,stage):
    stand.put_board([_auto_deal(983)])
    f=_auto_fields(vinState='pending',vehicleVin='',vinEvidence='VIN будет выдан позднее по п.2 ДКП',paymentStage=stage)
    r=stand.post('/api/stand/docs/issue',json={'dealId':983,'docFields':f})
    assert r.status_code==400,r.json


def test_ordinary_repeated_payment_retains_nonauto_contract_basis(stand):
    from tests.test_stand_docs import _deal,_fields
    d=_deal(984)
    d['docParse']['fields']['contract_ref']='QA Lease Contract Basis 984'
    stand.put_board([d])
    r=stand.post('/api/stand/docs/issue',json={'dealId':984,'docFields':_fields()})
    assert r.status_code==200,r.json
    db=appmod.get_session()
    try:
        a=db.get(appmod.Agreement,r.json['pack']['agreementId'])
        assert json.loads(a.fields_json)['contract_ref']=='QA Lease Contract Basis 984'
        payload,code=appmod._docs_payment(db,a,{},json.loads(a.money_json),commit=False)
        assert code==200,payload
        assert json.loads(a.fields_json).get('contract_ref')=='QA Lease Contract Basis 984'
    finally:
        db.rollback();db.close()


def test_unsupported_parent_schema_controlled_refusal(stand):
    stand.put_board([_auto_deal(985),_auto_deal(986,isOld=True)])
    first=stand.post('/api/stand/docs/issue',json={'dealId':985,'docFields':_auto_fields()})
    assert first.status_code==200,first.json
    db=appmod.get_session()
    try:
        a=db.get(appmod.Agreement,first.json['pack']['agreementId'])
        money=json.loads(a.money_json);money['auto_document_schema']='unsupported-v99'
        a.money_json=json.dumps(money);db.commit()
    finally:db.close()
    second=stand.post('/api/stand/docs/issue',json={'dealId':986,'docFields':_auto_fields()})
    assert second.status_code in (400,409),second.json


@pytest.mark.parametrize('role', ['manager', 'findir', 'teodor'])
def test_auto_issue_requires_current_step_role(stand, monkeypatch, role):
    stand.put_board([_auto_deal(987)])
    monkeypatch.setattr(appmod, 'current_role', lambda: role)
    response = stand.post('/api/stand/docs/issue',
                          json={'dealId': 987, 'docFields': _auto_fields()})
    assert response.status_code == 403, response.json
    assert response.json['error'] == 'forbidden_role'
    db = appmod.get_session()
    try:
        assert db.query(appmod.Agreement).count() == 0
    finally:
        db.close()


def test_one_contract_vin_and_pending_basis_requires_bound_review(stand):
    deal = _auto_deal(990)
    deal['docParse'] = {'fields': {
        'vehicle_vin': 'QA-VIN-1',
        'vehicle_vin_pending_basis': 'Appendix says VIN to be issued',
    }, 'provenance': {
        'vehicle_vin': 'vehicle_contract',
        'vehicle_vin_pending_basis': 'vehicle_contract',
    }, 'conflicts': {}}
    stand.put_board([deal])
    fields = _auto_fields(vinEvidence='Appendix says VIN to be issued')
    missing = stand.post('/api/stand/docs/issue',
                         json={'dealId': 990, 'docFields': fields})
    assert missing.status_code == 400, missing.json
    assert 'reviewNote' in missing.json['fields']

    fields['reviewNote'] = 'Текущий платёж: использовать VIN из основной части ДКП'
    values = [item.get('sha256') or '' for kind in ('vehicle_contract', 'inv')
              for item in deal['files'][kind]]
    values += [fields.get(k) for k in (
        'sellerName', 'sellerId', 'sellerAddress', 'dev', 'vehicleVin',
        'vinEvidence', 'vinState', 'contractNo', 'contractDate',
        'paymentStage', 'reviewNote')]
    values += ['QA-VIN-1', 'Appendix says VIN to be issued']
    fields['reviewToken'] = '|'.join(str(value or '').strip() for value in values)
    accepted = stand.post('/api/stand/docs/issue',
                          json={'dealId': 990, 'docFields': fields})
    assert accepted.status_code == 200, accepted.json

    fields['vinEvidence'] = 'Changed appendix basis'
    stale = stand.post('/api/stand/docs/issue',
                       json={'dealId': 990, 'docFields': fields})
    assert stale.status_code == 400, stale.json
    assert 'reviewNote' in stale.json['fields']
