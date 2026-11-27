"""Документы: один договор на клиента и тип сделки, ключ — паспорт.

Что ловим:
- регрессию «БУРОВА НАДЕЖДА» и «Бурова Надежда» — два разных клиента.
  Распознавание отдаёт имя то капсом, то в нормальном регистре, и у одного
  человека появлялось два лизхолд-договора (поймано Каримом на проде);
- обратную ошибку: однофамильцы с разными паспортами должны заводиться
  независимо;
- что другой тип сделки у того же клиента разрешён — шаблоны разные;
- что старым записям без ключа он проставляется при старте.

Запуск: cd Dev/CalcCRM && python -m pytest tests/test_docs_api.py -v
"""
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from uuid import uuid4

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('SECRET_KEY', 'test-secret-key-for-pytest')
os.environ['REESTR_SYNC_ENABLED'] = '0'

import app as crm
from app import (app, get_session, Agreement, AgreementDoc,  # noqa: E402
                 _docs_client_key, _backfill_agreement_keys)

FIELDS = {
    'client_passport_no': '77 2817242',
    'client_citizenship': 'Российская Федерация',
    'client_passport_issue_date': '14.03.2024',
    'invoice_no': 'X-1', 'invoice_date': '01.09.2026',
    'unit_no': 'B2-711', 'project_name': 'HEART BY BOTANICA',
    'recipient_name': 'Botanica Co., Ltd.', 'recipient_bank': 'Bangkok Bank',
}
MONEY = {'pair': 'RUB_THB', 'payin_currency': 'RUB', 'total_payin': '2800000',
         'transfer_amount': '1007194.24', 'rate': '2.78', 'payin_method': 'bank',
         'payin_recipient': 'MF Corporation Company Limited', 'payin_recipient_role': 'Агент',
         'payin_details': 'Test bank, account 12345', 'rate_valid_until': '10.09.2026, 23:59 (GMT+7)'}


@pytest.fixture(autouse=True)
def clean_agreements():
    def _clean():
        s = get_session()
        try:
            s.query(AgreementDoc).delete()
            s.query(Agreement).delete()
            s.commit()
        finally:
            s.close()
    _clean()
    yield
    _clean()


@pytest.fixture
def client(monkeypatch):
    # обход логина как в остальных API-тестах: работает только на sqlite
    monkeypatch.setenv('LOCAL_NO_AUTH', '1')
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c


def create(client, name, deal_type='leasehold', passport=None, money=None):
    fields = dict(FIELDS, client_name_ru=name, client_name_en='Burova Nadezhda')
    if passport:
        fields['client_passport_no'] = passport
    return client.post('/api/docs/agreements', json={
        'deal_type': deal_type, 'fields': fields, 'money': dict(MONEY, **(money or {}))})


class TestКлючКлиента:
    def test_ключ_это_только_цифры_паспорта(self):
        assert _docs_client_key({'client_passport_no': '77 2817242'}) == '772817242'

    def test_регистр_имени_на_ключ_не_влияет(self):
        a = _docs_client_key({'client_passport_no': '77 2817242',
                              'client_name_ru': 'БУРОВА НАДЕЖДА ВАСИЛЬЕВНА'})
        b = _docs_client_key({'client_passport_no': '77 2817242',
                              'client_name_ru': 'Бурова Надежда Васильевна'})
        assert a == b

    def test_разные_паспорта_дают_разные_ключи(self):
        assert (_docs_client_key({'client_passport_no': '77 2817242'})
                != _docs_client_key({'client_passport_no': '77 9999999'}))

    def test_без_паспорта_падаем_на_нормализованное_имя(self):
        a = _docs_client_key({'client_name_ru': '  БУРОВА   НАДЕЖДА '})
        b = _docs_client_key({'client_name_ru': 'Бурова Надежда'})
        assert a == b and a


class TestОдинДоговорНаТипСделки:
    def test_капс_и_нормальный_регистр_это_один_клиент(self, client):
        assert create(client, 'БУРОВА НАДЕЖДА ВАСИЛЬЕВНА').status_code == 200
        r = create(client, 'Бурова Надежда Васильевна')
        assert r.status_code == 409
        assert r.get_json()['error'] == 'already_exists'

    def test_другой_тип_сделки_разрешён(self, client):
        assert create(client, 'Бурова Надежда Васильевна').status_code == 200
        r = create(client, 'Бурова Надежда Васильевна', deal_type='rental',
                   money={'payment_type': 'депозит'})
        assert r.status_code == 200

    def test_однофамилец_с_другим_паспортом_заводится(self, client):
        assert create(client, 'Бурова Надежда Васильевна').status_code == 200
        r = create(client, 'Бурова Надежда Васильевна', passport='77 9999999')
        assert r.status_code == 200

    def test_в_ответе_есть_ссылка_на_существующий_договор(self, client):
        first = create(client, 'БУРОВА НАДЕЖДА').get_json()['agreement']
        dup = create(client, 'Бурова Надежда').get_json()
        assert dup['agreement_id'] == first['id']
        assert dup['number'] == first['number']

    def test_ключ_сохраняется_в_записи(self, client):
        a = create(client, 'Бурова Надежда Васильевна').get_json()['agreement']
        assert a['client_key'] == '772817242'


class TestБэкфилл:
    def test_старым_записям_ключ_проставляется(self, client):
        create(client, 'Бурова Надежда Васильевна')
        s = get_session()
        try:
            row = s.query(Agreement).first()
            row.client_key = None          # запись «из прошлого», до появления колонки
            s.commit()
            agreement_id = row.id
        finally:
            s.close()

        _backfill_agreement_keys()

        s = get_session()
        try:
            assert s.query(Agreement).get(agreement_id).client_key == '772817242'
        finally:
            s.close()

    def test_бэкфилл_идемпотентен(self, client):
        create(client, 'Бурова Надежда Васильевна')
        _backfill_agreement_keys()
        _backfill_agreement_keys()
        s = get_session()
        try:
            keys = [a.client_key for a in s.query(Agreement).all()]
        finally:
            s.close()
        assert keys == ['772817242']


class TestМаршрутыДокументов:
    @pytest.fixture(autouse=True)
    def skip_pdf(self, monkeypatch):
        # API-тестирует сохранение и валидацию; PDF проверяется отдельно реальным рендером.
        import docgen
        monkeypatch.setattr(docgen, 'to_pdf', lambda data: None)

    @pytest.mark.parametrize('first_direct,next_direct', [(False,True),(True,False),(True,True)])
    def test_rate_direction_survives_create_and_new_payment(self, client, first_direct, next_direct):
        from tests.test_doc_routes import route
        import doc_routes
        initial=route()
        if first_direct:
            initial.update(rate='32.260870',rate_basis=doc_routes.DIRECT_RATE)
        created=create(client,'Test direct quote',money=initial)
        assert created.status_code==200,created.json
        agreement=created.json['agreement']
        assert agreement['money']['rate_basis']==(doc_routes.DIRECT_RATE if first_direct else doc_routes.INVERSE_RATE)
        before=client.get(f"/api/docs/agreements/{agreement['id']}").json['agreement']
        old_files={d['id']:client.get(f"/api/docs/file/{d['id']}").data for d in before['docs']}
        payment=route()
        if next_direct:
            payment.update(rate='32.260870',rate_basis=doc_routes.DIRECT_RATE)
        result=client.post(f"/api/docs/agreements/{agreement['id']}/payment",json={'money':payment})
        assert result.status_code==200,result.json
        saved=result.json['agreement']['money']
        assert saved['rate_basis']==(doc_routes.DIRECT_RATE if next_direct else doc_routes.INVERSE_RATE)
        assert saved['total_payin']=='575' and saved['transfer_amount']=='18550'
        for doc_id,data in old_files.items():
            assert client.get(f'/api/docs/file/{doc_id}').data==data

    def test_basis_without_rate_is_rejected_atomically(self, client):
        from tests.test_doc_routes import route
        initial=route()
        created=create(client,'Test direct quote',money=initial).json['agreement']
        initial.pop('rate')
        initial['rate_basis']='transfer_per_payin'
        result=client.post(f"/api/docs/agreements/{created['id']}/payment",json={'money':initial})
        assert result.status_code==400 and 'укажите курс' in result.json['detail']
        assert client.get(f"/api/docs/agreements/{created['id']}").json['agreement']['payments_count']==1

    def test_freehold_without_optional_rate_accepts_unchanged_basis(self, client):
        money=dict(MONEY,pair='RUB_USD',transfer_currency='USD',rate='',
                   rate_basis='payin_per_transfer',transfer_amount='100',usd_equivalent='100',
                   rate_source='Test source',developer_confirmation='Test confirmation',
                   thb_credit_status='Test confirmed')
        created=create(client,'Test no quote',deal_type='freehold',money=money)
        assert created.status_code==200,created.json
        money.pop('rate')
        result=client.post(f"/api/docs/agreements/{created.json['agreement']['id']}/payment",json={'money':money})
        assert result.status_code==200,result.json

    def test_разные_пары_у_одного_клиента(self, client):
        first = create(client, 'Тест Клиент')
        second = create(client, 'Тест Клиент', money={
            'pair':'USDT_THB','payin_currency':'USDT','payin_method':'usdt',
            'total_payin':'575','transfer_amount':'18550','rate':'0.030997',
            'payin_network':'TRON (TRC-20)','payin_wallet':'T'+'A'*33})
        assert first.status_code == second.status_code == 200
        assert first.json['agreement']['number'] != second.json['agreement']['number']

    def test_разные_способы_оплаты_разные_договоры(self, client):
        assert create(client, 'Тест Клиент').status_code == 200
        assert create(client, 'Тест Клиент', money={'payin_method':'sbp'}).status_code == 200

    def test_старый_шаблон_не_блокирует_исправленный_договор(self, client):
        old=create(client, 'Тест Клиент').json['agreement']
        s=get_session()
        try:
            s.get(Agreement,old['id']).route_key='legacy'
            s.commit()
        finally:
            s.close()
        r=client.post(f"/api/docs/agreements/{old['id']}/payment",json={'money':MONEY})
        assert r.status_code == 400 and 'старого шаблона' in r.json['detail']
        fresh=create(client, 'Тест Клиент')
        assert fresh.status_code == 200
        assert fresh.json['agreement']['id'] != old['id']
        assert len(client.get(f"/api/docs/agreements/{old['id']}").json['agreement']['docs']) == 3

    def test_новый_платёж_не_наследует_кошелёк_и_срок(self, client):
        first = create(client, 'Тест Клиент').json['agreement']
        r = client.post(f"/api/docs/agreements/{first['id']}/payment", json={
            'money': {'total_payin':'300', 'transfer_amount':'100', 'rate':'3'}})
        assert r.status_code == 400
        assert 'payin_details' in r.json['fields']
        assert 'rate_valid_until' in r.json['fields']
        assert client.get(f"/api/docs/agreements/{first['id']}").json['agreement']['payments_count'] == 1

    def test_новый_платёж_не_меняет_рамочный_маршрут(self, client):
        first = create(client, 'Тест Клиент').json['agreement']
        r=client.post(f"/api/docs/agreements/{first['id']}/payment", json={'money':dict(MONEY,payin_method='sbp')})
        assert r.status_code == 400
        assert 'новый договор' in r.json['detail']

    def test_неверная_пара_не_создаёт_файлы(self, client):
        r=create(client,'Тест Клиент',money={'pair':'USDT_THB','payin_currency':'USDT'})
        assert r.status_code == 400
        s=get_session()
        try:
            assert s.query(AgreementDoc).count() == 0
        finally:
            s.close()

    def test_пустая_сеть_не_выпускает_usdt(self, client):
        r=create(client,'Тест Клиент',money={'pair':'USDT_THB','payin_currency':'USDT','payin_method':'usdt'})
        assert r.status_code == 400
        assert 'payin_network' in r.json['fields']


@pytest.mark.parametrize('payload', [
    [], [1], None, 42,
    {'fields': []}, {'fields': None}, {'money': [1]},
    {'fields': {'client_name_ru': 1}},
    {'fields': {'client_passport_no': 123456}},
    {'money': {'total_payin': {'amount': 100}}},
    {'money': {'total_payin': float('nan')}},
    {'money': {'rate': float('inf')}},
    {'client_id': 'wrong'}, {'client_id': True}, {'client_id': 1.5},
])
@pytest.mark.parametrize('payment', [False, True])
def test_invalid_document_payload_is_atomic_400(client, monkeypatch, payload, payment):
    """Неверный ввод не запускает генерацию и не меняет договор/счётчик платежей."""
    import docgen
    db = get_session()
    try:
        a = Agreement(client_name='Тест', client_key='990001234',
                      deal_type='leasehold', number='QA-1', payments_count=1,
                      fields_json=json.dumps(dict(FIELDS, client_name_ru='Тест')),
                      money_json=json.dumps(MONEY))
        db.add(a)
        db.commit()
        agreement_id = a.id
    finally:
        db.close()

    def unexpected_generation(*args, **kwargs):
        pytest.fail('Валидация должна завершиться до генерации документа')

    monkeypatch.setattr(docgen, 'build_agreement', unexpected_generation)
    monkeypatch.setattr(docgen, 'build_addendum', unexpected_generation)
    path = (f'/api/docs/agreements/{agreement_id}/payment' if payment
            else '/api/docs/agreements')
    response = client.post(path, data=json.dumps(payload), content_type='application/json')
    assert response.status_code == 400
    assert response.get_json()['error'] == 'invalid_payload'
    db = get_session()
    try:
        assert db.query(Agreement).count() == 1
        assert db.get(Agreement, agreement_id).payments_count == 1
        assert db.query(AgreementDoc).count() == 0
    finally:
        db.close()


@pytest.mark.parametrize('fields', ['{broken', '[]', 'null'])
def test_invalid_multipart_fields_are_json_400(client, fields):
    """Ошибки JSON в multipart обрабатываются так же, как в JSON-запросе."""
    response = client.post('/api/docs/agreements', data={
        'deal_type': 'leasehold', 'fields': fields, 'money': json.dumps(MONEY)},
        content_type='multipart/form-data')
    assert response.status_code == 400
    assert response.get_json()['error'] == 'invalid_payload'


def test_document_payload_keeps_valid_multipart_and_numeric_money():
    """Валидация сохраняет контракт существующей формы и числовых сумм API."""
    from app import _docs_request_payload
    with app.test_request_context('/api/docs/agreements', method='POST', data={
            'fields': json.dumps(FIELDS), 'money': json.dumps(MONEY), 'client_id': '7'},
            content_type='multipart/form-data'):
        parsed = _docs_request_payload()
        assert parsed['fields'] == FIELDS
        assert parsed['money'] == MONEY
        assert parsed['client_id'] == 7
    with app.test_request_context('/api/docs/agreements', json={
            'fields': FIELDS, 'money': {'total_payin': 100.25, 'rate': 2}}):
        assert _docs_request_payload()['money'] == {'total_payin': 100.25, 'rate': 2}

    def test_запись_без_паспорта_в_полях_получает_ключ_из_имени(self, client):
        create(client, 'Бурова Надежда Васильевна')
        s = get_session()
        try:
            row = s.query(Agreement).first()
            row.client_key = None
            row.fields_json = json.dumps({}, ensure_ascii=False)
            s.commit()
            agreement_id = row.id
        finally:
            s.close()

        _backfill_agreement_keys()

        s = get_session()
        try:
            assert s.query(Agreement).get(agreement_id).client_key
        finally:
            s.close()


@pytest.fixture
def docs_admin(client):
    with get_session() as db:
        user = crm.AdminUser(username=f'docs-admin-{uuid4().hex}', role='admin', password_hash='unused')
        db.add(user)
        db.commit()
        user_id = user.id
    with client.session_transaction() as session:
        session['user_id'] = user_id
    try:
        yield client
    finally:
        with get_session() as db:
            db.delete(db.get(crm.AdminUser, user_id))
            db.commit()


@pytest.fixture
def docs_board_schema():
    crm.Base.metadata.create_all(crm.engine, tables=[crm.StandState.__table__])
    # SQLite может повторно выдать ID договора после clean_agreements.
    # Ссылки из предыдущих тестов задачника не относятся к новому договору.
    with get_session() as db:
        board = db.get(crm.StandState, 1)
        original_data = board.data if board is not None else None
        had_board = board is not None
        if had_board:
            board.data = '{}'
            db.commit()
    try:
        yield
    finally:
        with get_session() as db:
            board = db.get(crm.StandState, 1)
            if board is not None:
                if had_board:
                    board.data = original_data
                else:
                    db.delete(board)
                db.commit()


@pytest.fixture
def legacy_stand_docs(docs_admin, monkeypatch, docs_board_schema):
    monkeypatch.setattr(crm, 'STAND_MODE', True)
    return docs_admin


class TestУдаление:
    """Удаление обычного договора и защита файлов, связанных с задачником."""

    @pytest.mark.parametrize('tasks_enabled', [False, True])
    def test_договор_удаляется_вместе_с_документами(self, docs_admin, docs_board_schema,
                                                        monkeypatch, tasks_enabled):
        monkeypatch.setattr(crm, 'TASKS_ENABLED', tasks_enabled)
        client = docs_admin
        a = create(client, 'Бурова Надежда Васильевна').get_json()['agreement']
        assert len(a['docs']) == 3

        assert client.delete(f"/api/docs/agreements/{a['id']}").status_code == 200

        s = get_session()
        try:
            assert s.query(Agreement).count() == 0
            # документы уходят каскадом, иначе в базе остаётся мусор с паспортами
            assert s.query(AgreementDoc).filter(
                AgreementDoc.agreement_id == a['id']).count() == 0
        finally:
            s.close()

    def test_после_удаления_тип_сделки_освобождается(self, docs_admin):
        client = docs_admin
        a = create(client, 'Бурова Надежда Васильевна').get_json()['agreement']
        assert client.delete(f"/api/docs/agreements/{a['id']}").status_code == 200
        # тот же клиент и тип снова заводится — ключ больше никем не занят
        assert create(client, 'Бурова Надежда Васильевна').status_code == 200

    def test_договор_с_документами_нельзя_удалить_физически(self, legacy_stand_docs):
        client = legacy_stand_docs
        a = create(client, 'Бурова Надежда Васильевна').get_json()['agreement']
        assert len(a['docs']) == 3

        removed = client.delete(f"/api/docs/agreements/{a['id']}")
        assert removed.status_code == 409
        assert 'Удаляйте файлы по одному' in removed.json['error']

        s = get_session()
        try:
            assert s.query(Agreement).count() == 1
            assert s.query(AgreementDoc).filter(
                AgreementDoc.agreement_id == a['id']).count() == 3
        finally:
            s.close()

    def test_удаление_несуществующего_даёт_404(self, client):
        assert client.delete('/api/docs/agreements/999999').status_code == 404

    def test_договор_с_файлами_остаётся_занятым(self, legacy_stand_docs):
        client = legacy_stand_docs
        a = create(client, 'Бурова Надежда Васильевна').get_json()['agreement']
        assert client.delete(f"/api/docs/agreements/{a['id']}").status_code == 409
        assert create(client, 'Бурова Надежда Васильевна').status_code == 409


    @pytest.mark.parametrize('linked_to', ['task_card', 'closed_crm_deal'])
    def test_даже_админ_не_удаляет_договор_со_связью(self, docs_admin, docs_board_schema,
                                                         monkeypatch, linked_to):
        created = create(docs_admin, 'Бурова Надежда Васильевна')
        assert created.status_code == 200, created.json
        agreement = created.json['agreement']
        agreement_id = agreement['id']
        monkeypatch.setattr(crm, 'TASKS_ENABLED', True)
        deal_id = client_id = None
        with get_session() as db:
            board = crm._stand_row(db)
            old_data = board.data
            if linked_to == 'task_card':
                state = json.loads(old_data)
                state.setdefault('deals', []).append({'id': 9901, 'docPack': {'agreementId': agreement_id}})
                board.data = json.dumps(state)
            else:
                person = crm.Client(name='QA linked agreement')
                db.add(person)
                db.flush()
                deal = crm.Deal(client_id=person.id, deal_type=crm.DealType.PAY_IN,
                                status=crm.DealStatus.COMPLETED)
                db.add(deal)
                db.flush()
                deal_id, client_id = deal.id, person.id
                db.get(Agreement, agreement_id).client_id = client_id
            db.commit()

        try:
            response = docs_admin.delete(f'/api/docs/agreements/{agreement_id}')
            assert response.status_code == 409, response.json
            assert 'связан со сделкой' in response.json['error']
            with get_session() as db:
                saved = db.get(Agreement, agreement_id)
                assert saved and {doc.id for doc in saved.docs} == {doc['id'] for doc in agreement['docs']}
        finally:
            with get_session() as db:
                crm._stand_row(db).data = old_data
                if deal_id is not None:
                    db.get(Agreement, agreement_id).client_id = None
                    db.delete(db.get(crm.Deal, deal_id))
                    db.flush()
                    db.delete(db.get(crm.Client, client_id))
                db.commit()


    def test_импортированные_документы_доступны_только_для_чтения(self, docs_admin, monkeypatch):
        monkeypatch.setattr(crm, 'TASKS_ENABLED', True)
        tables = crm.Base.metadata.tables
        imports = tables['stand_task_imports']
        records = tables['stand_task_history_records']
        crm.Base.metadata.create_all(crm.engine, tables=[imports, records, tables['stand_task_history']])
        content = b'%PDF-1.4 synthetic archived attachment'
        agreement_id, doc_id = 99003, 99004
        with get_session() as db:
            db.execute(imports.insert().values(id=1, bundle_sha256='a' * 64,
                       generation='b' * 32, source_version=1,
                       applied_at=datetime.now(timezone.utc), reconciliation={}))
            db.execute(records.insert(), [
                {'source_table':'agreements', 'source_key':str(agreement_id), 'import_id':1,
                 'payload':{'id':agreement_id, 'client_name':'Synthetic archive', 'number':'QA-ARCHIVE'},
                 'content':None, 'content_sha256':None},
                {'source_table':'agreement_docs', 'source_key':str(doc_id), 'import_id':1,
                 'payload':{'id':doc_id, 'agreement_id':agreement_id,
                            'filename':'archive.pdf', 'mime':'application/pdf', 'deleted_at':None},
                 'content':content, 'content_sha256':hashlib.sha256(content).hexdigest()},
            ])
            db.commit()
        try:
            catalog = docs_admin.get('/api/stand/task-history/agreements')
            assert catalog.status_code == 200, catalog.json
            agreement, = [row for row in catalog.json['agreements'] if row['id'] == agreement_id]
            document, = agreement['documents']
            link = document['url']
            initial = docs_admin.get(link)
            assert initial.status_code == 200 and initial.data == content
            assert initial.headers['Cache-Control'] == 'private, no-store'
            assert docs_admin.delete(link).status_code == 405
            assert docs_admin.patch(link, json={'action': 'delete'}).status_code == 405
            assert docs_admin.delete(f'/api/docs/agreements/{agreement_id}').status_code == 404
            assert docs_admin.get(link).data == content
        finally:
            with get_session() as db:
                db.execute(records.delete().where(records.c.import_id == 1))
                db.execute(imports.delete().where(imports.c.id == 1))
                db.commit()


class TestДубльНеТупик:
    """При «уже есть» менеджеру нужен путь дальше, а не сообщение в никуда."""

    def test_ответ_несёт_id_и_номер_существующего(self, client):
        first = create(client, 'Бурова Надежда Васильевна').get_json()['agreement']
        dup = create(client, 'БУРОВА НАДЕЖДА ВАСИЛЬЕВНА').get_json()
        assert dup['agreement_id'] == first['id']
        assert dup['number'] == first['number']
        assert 'допник' in dup['detail'].lower() or 'платёж' in dup['detail'].lower()

    def test_платёж_по_существующему_договору_проходит(self, client):
        first = create(client, 'Бурова Надежда Васильевна').get_json()['agreement']
        r = client.post(f"/api/docs/agreements/{first['id']}/payment",
                        json={'money': dict(MONEY, total_payin='3000000', rate='3.0',
                                            transfer_amount='1000000')})
        assert r.status_code == 200
        a = r.get_json()['agreement']
        assert a['payments_count'] == 2
        assert len([d for d in a['docs'] if d['seq'] == 2]) == 2   # допник + инвойс
