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
