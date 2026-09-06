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
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('SECRET_KEY', 'test-secret-key-for-pytest')
os.environ['REESTR_SYNC_ENABLED'] = '0'

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
         'transfer_amount': '1007194.24', 'rate': '2.78', 'payin_method': 'bank'}


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


class TestУдаление:
    """Удалить договор было нечем — API есть, кнопки в интерфейсе не было."""

    def test_договор_удаляется_вместе_с_документами(self, client):
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

    def test_удаление_несуществующего_даёт_404(self, client):
        assert client.delete('/api/docs/agreements/999999').status_code == 404

    def test_после_удаления_тип_сделки_освобождается(self, client):
        a = create(client, 'Бурова Надежда Васильевна').get_json()['agreement']
        client.delete(f"/api/docs/agreements/{a['id']}")
        # тот же клиент и тип снова заводится — ключ больше никем не занят
        assert create(client, 'Бурова Надежда Васильевна').status_code == 200


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
