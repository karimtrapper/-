"""Real HTTP stand_state freehold basis guard against a synthetic SQLite DB.
Run only under T17 sandbox; database path comes from the clean test env.
"""
import copy
import json
import runpy

appmod = runpy.run_path('tests/t17_fenced_smoke.py')['app']
client = appmod.app.test_client()
login = client.post('/api/auth/login', json={'username':'karim','password':'synthetic-t17'},
                    base_url='https://localhost')
assert login.status_code == 200, login.json


def state():
    r=client.get('/api/stand/state',base_url='https://localhost')
    assert r.status_code==200,r.json
    return r.json


def put(version,data):
    return client.put('/api/stand/state',json={'version':version,'data':data},
                      base_url='https://localhost')

current=state()
original=copy.deepcopy(current['data'])
original['deals']=[
    {'id':91001,'kind':'Фрихолд','type':'Оплата недвижимости','step':'manual',
     'invoiceUsd':45000,'invoiceCurrency':'thb','invoiceThb':1500000,
     'ippsTariff':'bank','closed':False},
    {'id':91002,'kind':'Фрихолд','type':'Оплата недвижимости','step':'s11',
     'invoiceUsd':45000,'invoiceCurrency':'usd','invoiceThb':None,
     'ippsTariff':'bank','closed':False},
    {'id':91003,'kind':'Фрихолд','type':'Оплата недвижимости','step':'done',
     'invoiceUsd':45000,'invoiceCurrency':'usd','invoiceThb':None,
     'ippsTariff':'bank','closed':True},
    {'id':91004,'kind':'Фрихолд','type':'Оплата недвижимости','step':'s8',
     'invoiceUsd':45000,'invoiceCurrency':'usd','invoiceThb':None,
     'ippsTariff':'bank','closed':False,
     'transfer':{'sends':[{'hash':'synthetic-confirmed','status':'confirmed'}]}},
]
original['seq']=91004
seed=put(current['version'],original)
assert seed.status_code==200,seed.json
current=seed.json
# Before lock, an explicit manager choice remains writable.
allowed=copy.deepcopy(current['data'])
allowed['deals'][0]['ippsTariff']='soft'
r=put(current['version'],allowed)
assert r.status_code==200,r.json
current=r.json
assert current['data']['deals'][0]['ippsTariff']=='soft'
# A confirmed transfer is server-owned; put it into the isolated fixture DB,
# because ordinary stand_state PUT intentionally downgrades forged confirmation.
db=appmod.get_session()
try:
    row=appmod._stand_row(db,lock=True)
    server_state=json.loads(row.data)
    next(x for x in server_state['deals'] if x['id']==91004)['transfer']['sends'][0]['status']='confirmed'
    row.data=json.dumps(server_state,ensure_ascii=False)
    row.version+=1
    db.commit()
finally:
    db.close()
current=state()
def crm_rows():
    db=appmod.get_session()
    try:
        return [(d.id,d.deal_kind) for d in db.query(appmod.Deal).order_by(appmod.Deal.id)]
    finally:
        db.close()

crm_before=crm_rows()
mutations={
    'invoiceUsd':(46000,0,'46000',''),
    'ippsTariff':('soft','',0),
    'invoiceCurrency':('thb','',0),
    'invoiceThb':(1550000,0,'1550000',''),
}
# All four canonical fields are independently guarded, even when an unrelated
# note is bundled into the malicious request. A failed PUT cannot advance the
# version, change another deal, or create a CRM deal.
for deal_id, stage in ((91002,'s11'),(91003,'closed'),(91004,'confirmed')):
    for field, values in mutations.items():
        for value in values:
            attempted=copy.deepcopy(current['data'])
            row=next(x for x in attempted['deals'] if x['id']==deal_id)
            if row.get(field)==value:
                continue
            row[field]=value
            row['notes']='must not persist'
            response=put(current['version'],attempted)
            assert response.status_code==409,(stage,field,value,response.status_code,response.json)
            assert state()==current,(stage,field,value,'non-atomic state')
            assert crm_rows()==crm_before,(stage,field,value,'CRM changed')
        print(stage,field,'409 atomic')

# Identity and a note-only edit remain valid at each protected stage.
for deal_id,stage in ((91002,'s11'),(91003,'closed'),(91004,'confirmed')):
    identity=put(current['version'],copy.deepcopy(current['data']))
    assert identity.status_code==200,(stage,'identity',identity.json)
    current=identity.json
    note=copy.deepcopy(current['data'])
    next(x for x in note['deals'] if x['id']==deal_id)['notes']='allowed note '+stage
    saved=put(current['version'],note)
    assert saved.status_code==200,(stage,'note',saved.json)
    current=saved.json
    assert crm_rows()==crm_before
    print(stage,'identity and note 200')

# The existing stand_state schema uses these camel-case names; its serializer
# does not normalize monetary number strings or aliases. Check exact identity
# rather than treating a changed representation as an authorised money edit.
print('draft tariff changed; individual locked X/tariff/currency/THB guarded; identity/note 200: PASS')
