"""Разделение приходов Сбера на СБП (эквайринг) и реквизиты.

В выписку счёта падают оба потока, и в пуле они были неразличимы: у СБП
плательщик всегда «Московский банк Сбербанка России», сумма — уже за вычетом
комиссии банка, а клиент заплатил больше. Из-за этого приход по СБП нельзя
было сопоставить ни с одной сделкой («деньги пришли, а чьи — непонятно»),
а если бы и забрали, объём сделки занизился бы на комиссию.

Назначения в тестах — дословно из выписки счёта …0286 (ООО ЭМ ЭФ Корпорейшн).

Запуск: cd Dev/CalcCRM && python -m pytest tests/test_sber_acquiring.py -v
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('SECRET_KEY', 'test-secret-key-for-pytest')
os.environ['REESTR_SYNC_ENABLED'] = '0'

import pytest

from app import (PAYIN_METHOD_LABELS, SberIncome, app as flask_app, get_session,
                 parse_sber_acquiring)

CRM_HTML = (Path(__file__).resolve().parent.parent / 'static' / 'crm' / 'crm.html').read_text(encoding='utf-8')
CALC_JS = (Path(__file__).resolve().parent.parent / 'static' / 'calculator' / 'calculator.js').read_text(encoding='utf-8')

ACQ_700 = ('Зачисление средств по операциям эквайринга. Мерчант №781003872118. '
           'Комиссия 700.00. НДС не облагается.')
ACQ_SPACED = ('Зачисление средств по операциям эквайринга. Мерчант №781003872118. '
              'Комиссия 7 000.00. НДС не облагается.')
ACQ_NDS = ('Зачисление средств по операциям эквайринга. Мерчант №781003794166. '
           'Комиссия 0.41 (в т.ч. НДС 0.07). Возврат покупки 0.00/0.00.')
TRANSFER = 'Оплата недвижимости. НДС не облагается'


@pytest.fixture(autouse=True)
def clean_db():
    def _wipe():
        s = get_session()
        try:
            s.query(SberIncome).delete()
            s.commit()
        finally:
            s.close()
    _wipe()
    yield
    _wipe()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('LOCAL_NO_AUTH', '1')
    flask_app.config['TESTING'] = True
    with flask_app.test_client() as c:
        yield c


def _mk_income(uuid, amount, purpose, payer='Московский банк Сбербанка России'):
    s = get_session()
    try:
        s.add(SberIncome(uuid=uuid, operation_date='2026-08-12', amount_rub=amount,
                         payer=payer, purpose=purpose, doc_number='1'))
        s.commit()
    finally:
        s.close()


# ==================== разбор назначения ====================

def test_acquiring_fee_parsed():
    acq = parse_sber_acquiring(ACQ_700)
    assert acq['kind'] == 'acquiring'
    assert acq['fee_rub'] == 700.0
    assert acq['merchant'] == '781003872118'


def test_fee_with_thousand_separator():
    """«Комиссия 7 000.00» — пробел-разделитель тысяч не должен обрезать число."""
    assert parse_sber_acquiring(ACQ_SPACED)['fee_rub'] == 7000.0


def test_fee_with_nds_in_brackets():
    """У другого мерчанта ставка иная (2.4%) и в скобках НДС — берём саму комиссию."""
    acq = parse_sber_acquiring(ACQ_NDS)
    assert acq['fee_rub'] == 0.41
    assert acq['merchant'] == '781003794166'


def test_transfer_is_not_acquiring():
    acq = parse_sber_acquiring(TRANSFER)
    assert acq['kind'] == 'transfer'
    assert acq['fee_rub'] == 0.0


def test_empty_purpose():
    assert parse_sber_acquiring(None)['kind'] == 'transfer'
    assert parse_sber_acquiring('')['fee_rub'] == 0.0


# ==================== gross в to_dict ====================

def test_gross_is_net_plus_fee():
    """Клиент заплатил 100 000 ₽, на счёт упало 99 300 — в сделку идут 100 000."""
    _mk_income('u1', 99300.0, ACQ_700)
    s = get_session()
    try:
        d = s.query(SberIncome).filter(SberIncome.uuid == 'u1').first().to_dict()
    finally:
        s.close()
    assert d['kind'] == 'acquiring'
    assert d['amount_rub'] == 99300.0     # зачислено
    assert d['gross_rub'] == 100000.0     # заплатил клиент
    assert d['fee_rub'] == 700.0


def test_gross_equals_net_for_transfer():
    """По реквизитам приходит вся сумма — gross и net совпадают."""
    _mk_income('u2', 3300000.0, TRANSFER, payer='НАФИКОВ РАДИМИР РАВИЛЬЕВИЧ')
    s = get_session()
    try:
        d = s.query(SberIncome).filter(SberIncome.uuid == 'u2').first().to_dict()
    finally:
        s.close()
    assert d['kind'] == 'transfer'
    assert d['gross_rub'] == d['amount_rub'] == 3300000.0


def test_real_wl_deal_matches_by_gross():
    """Сделка WL на 27 786,44 ₽ — в выписке это 27 591,93 + комиссия 194,51."""
    _mk_income('u3', 27591.93, ACQ_700.replace('700.00', '194.51'))
    s = get_session()
    try:
        d = s.query(SberIncome).filter(SberIncome.uuid == 'u3').first().to_dict()
    finally:
        s.close()
    assert d['gross_rub'] == 27786.44


# ==================== фильтр эндпоинта ====================

def test_endpoint_filters_by_kind(client):
    _mk_income('a1', 99300.0, ACQ_700)
    _mk_income('t1', 450000.0, TRANSFER, payer='ИМАЙКИНА ЕЛЕНА НИКОЛАЕВНА')

    acq = client.get('/api/sber-incomes?kind=acquiring').get_json()['incomes']
    assert [i['uuid'] for i in acq] == ['a1']

    tr = client.get('/api/sber-incomes?kind=transfer').get_json()['incomes']
    assert [i['uuid'] for i in tr] == ['t1']

    both = client.get('/api/sber-incomes').get_json()['incomes']
    assert {i['uuid'] for i in both} == {'a1', 't1'}


def test_unknown_kind_does_not_filter(client):
    _mk_income('a1', 99300.0, ACQ_700)
    rows = client.get('/api/sber-incomes?kind=нечто').get_json()['incomes']
    assert len(rows) == 1


# ==================== СБП вместо «Сбер (WL Bot)» ====================

def test_labels_call_sber_wl_sbp():
    assert PAYIN_METHOD_LABELS['sber_wl'] == 'СБП'
    assert PAYIN_METHOD_LABELS['spp_doverka'] == 'СБП (Доверка)'


def _option_line(select_id, value):
    """Строка <option> с данным value внутри селекта select_id."""
    start = CRM_HTML.index(f'id="{select_id}"')
    end = CRM_HTML.index('</select>', start)
    block = CRM_HTML[start:end]
    m = re.search(r'<option value="%s".*' % re.escape(value), block)
    return m.group(0) if m else None


@pytest.mark.parametrize('select_id', ['payinMethod', 'customPayinMethod'])
def test_doverka_hidden_from_selects(select_id):
    """Архивный метод не выбирается руками, но остаётся в DOM — иначе старая
    сделка откроется с пустым селектом и сохранение сменит ей метод."""
    line = _option_line(select_id, 'spp_doverka')
    assert line is not None, f'{select_id}: опция spp_doverka удалена из DOM'
    assert 'hidden' in line


@pytest.mark.parametrize('select_id', ['payinMethod', 'customPayinMethod'])
def test_sbp_option_points_to_sber_wl(select_id):
    line = _option_line(select_id, 'sber_wl')
    assert line is not None and '>СБП<' in line


def test_legacy_value_restores_option():
    """Хелпер раскрывает скрытую опцию, когда у сделки архивный метод."""
    assert 'function setPayinMethodValue' in CRM_HTML
    assert 'opt.hidden = false' in CRM_HTML
    assert "document.getElementById('payinMethod').value = deal.payin_method" not in CRM_HTML


def test_sber_pool_serves_both_methods():
    assert "function methodUsesSberPool" in CRM_HTML
    # Все три места отправки частей идут через общий предикат, иначе части
    # СБП-сделки молча теряются при сохранении
    assert CRM_HTML.count('methodUsesSberPool(') >= 6
    assert "payin_parts: payinMethod === 'sber_reqs'" not in CRM_HTML
    assert "data.payin_method === 'sber_reqs' ? sberParts" not in CRM_HTML


def test_calculator_creates_sbp_deal_as_sber_wl():
    assert "'doverka' ? 'sber_wl'" in CALC_JS
    assert "'doverka' ? 'spp_doverka'" not in CALC_JS
