"""Оплата авто на изолированных данных: отдельный продукт, документы и денежный маршрут."""
from io import BytesIO

import app as m
import docgen
import pytest
from docx import Document

pytestmark = pytest.mark.usefixtures('stand_demo_environment')


@pytest.fixture(autouse=True)
def clean_auto_close_artifacts(stand_demo_environment, monkeypatch):
    """Synthetic CRM close must not leave links or ledgers for adjacent tests."""
    import json
    monkeypatch.setattr(m, 'STAND_MODE', True)
    m._stand_migrate()
    db = m.get_session()
    try:
        prior = {(x.origin, x.crm_deal_id) for x in db.query(m.StandCrmLink).all()}
        prior_users = {x.id for x in db.query(m.AdminUser).all()}
        prior_evidence = {(x.generation, x.stand_deal_id, x.kind)
                          for x in db.query(m.StandCloseEvidence).all()}
    finally:
        db.close()
    yield
    db = m.get_session()
    try:
        for link in list(db.query(m.StandCrmLink).all()):
            if (link.origin, link.crm_deal_id) in prior:
                continue
            crm_id = link.crm_deal_id
            db.query(m.PayinTxUse).filter_by(deal_id=crm_id).delete()
            db.delete(link)
            db.query(m.Deal).filter_by(id=crm_id).delete()
        row = db.query(m.StandState).filter_by(id=1).first()
        if row:
            board = json.loads(row.data or '{}')
            hashes = [h.get('hash') for d in board.get('deals') or []
                      if d.get('autoPayment') is True for h in d.get('payinHashes') or []]
            if hashes:
                tx_ids = [i for (i,) in db.query(m.PayinTx.id).filter(m.PayinTx.tx_hash.in_(hashes)).all()]
                if tx_ids:
                    db.query(m.PayinTxUse).filter(m.PayinTxUse.tx_id.in_(tx_ids)).delete(synchronize_session=False)
                db.query(m.PayinTx).filter(m.PayinTx.tx_hash.in_(hashes)).delete(synchronize_session=False)
        for evidence in db.query(m.StandCloseEvidence).all():
            if (evidence.generation, evidence.stand_deal_id, evidence.kind) not in prior_evidence:
                db.delete(evidence)
        for user in db.query(m.AdminUser).all():
            if user.id not in prior_users:
                db.delete(user)
        db.commit()
    finally:
        db.close()


def _auto_deal(mode='sber'):
    return {
        'id': 1, 'type': 'Оплата недвижимости', 'kind': 'Фрихолд', 'autoPayment': True,
        'payType': 'По реквизитам', 'rubReceivingAccount': {'mode': mode},
        'invoiceUsd': 45000, 'ippsTariff': 'bank', 'object': 'Toyota Camry VIN QA123',
        'amountRub': 4000000, 'rates': {'client': 88.888889},
        'docParse': {'fields': {'project_name': 'Неверный проект', 'unit_no': 'A-123',
                                'property_address': 'Неверный адрес', 'invoice_no': 'AUTO-QA-1'}},
    }


def _fields():
    return {'fio': 'Тест Тестов', 'passNo': 'QA123456', 'dev': 'Synthetic seller',
            'invNo': 'AUTO-QA-1', 'invDate': '01.11.2026', 'object': 'Toyota Camry VIN QA123',
            'vehicleModel': 'Toyota Camry', 'vehicleVin': 'QA123', 'vinState': 'known',
            'vehicleDetails': '2026, серебристый', 'sellerName': 'Synthetic seller',
            'sellerId': 'TEST-REG-1', 'contractNo': 'TEST-DKP-1',
            'contractDate': '01.11.2026', 'paymentStage': 'full',
            'amountThb': '45000', 'amountPay': '4000000', 'rate': '88.888889',
            'payTo': 'Реквизиты получателя по агентскому договору',
            'purpose': 'Оплата по агентскому договору', 'validTill': '06.11.2026'}


@pytest.mark.parametrize('mode,agent', [('sber', 'mf_corp'), ('flowsole', 'flow_sole')])
def test_auto_uses_payment_docs_with_usd_output_and_correct_agent(mode, agent):
    result = m._stand_doc_request({'deals': []}, _auto_deal(mode), _fields())
    assert 'error' not in result, result
    assert result['deal_type'] == 'payment'
    assert result['money']['pair'] == 'RUB_USD'
    assert result['money']['agent'] == agent
    assert result['money']['transfer_amount'] == '45000'
    assert result['money']['object_label'] == 'Автомобиль / Vehicle'
    assert result['money']['invoice_description'].startswith('Оплата автомобиля')
    assert result['fields']['vehicle_model'] == 'Toyota Camry'
    assert 'project_name' not in result['fields']
    assert 'unit_no' not in result['fields']
    assert 'property_address' not in result['fields']
    content, _ = docgen.build_agreement('payment', result['fields'], result['money'],
                                        blank_annexes=False)
    doc = Document(BytesIO(content))
    text = '\n'.join(cell.text for table in doc.tables for row in table.rows for cell in row.cells)
    assert 'Автомобиль / Vehicle' in text
    assert 'Toyota Camry' in text and 'QA123' in text
    assert 'Неверный проект' not in text
    assert 'Объект / Property' not in text
    invoice = docgen.build_commercial_invoice(result['fields'], result['money'],
                                              'AUTO-QA-INV', 'payment', agent=agent)
    inv_doc = Document(BytesIO(invoice))
    inv_text = '\n'.join(p.text for p in inv_doc.paragraphs)
    inv_text += '\n' + '\n'.join(cell.text for table in inv_doc.tables
                                  for row in table.rows for cell in row.cells)
    assert 'апартаменты' not in inv_text.lower()
    assert 'Toyota Camry' in inv_text
    assert 'Текущий платёж продавцу / Current seller payment: USD 45 000.00' in inv_text


def test_auto_flow_is_separate_from_freehold_and_only_verified_for_requisites():
    assert m.canonical_deal_kind_from_stand('Оплата недвижимости', 'Фрихолд', True) == 'auto'
    assert m.canonical_deal_kind_from_legacy('mf_auto') == 'auto'
    assert m.is_verified_flow('auto', 'requisites')
    assert not m.is_verified_flow('auto', 'crypto')
    assert m.is_verified_flow('freehold', 'requisites')


def test_auto_rub_requisites_have_broker_basis_in_crm_fact_check():
    board = _auto_deal()
    board.update(incomeAmount=4000000, payinHashes=[], payinExtra=[], payinParts=[],
                 mfPayout=[], payTo={'purpose': 'AUTO-QA-1'},
                 rates={'broker': 82, 'client': 88.888889}, rubIsNet=True)
    basis = m._stand_broker_payin_basis(4000000, 82)
    assert basis and basis['usdt'] > 0
    crm = {'deal_kind': 'mf_auto', 'payin_method': 'sber_reqs',
           'payin_amount_rub': 4000000, 'payin_rate_rub_usdt': 82,
           'payin_amount_usdt': float(basis['usdt']), 'payin_tx_hashes': [],
           'payin_parts': [], 'payin_extra': [], 'payout_tx_hashes': [],
           'realty_purpose': 'AUTO-QA-1', 'invoice_amount_usd': 45000,
           'transfer_fee_percent': .8, 'transfer_fee_fixed_usd': 50,
           'transfer_sent_usd': 45410, 'payin_rub_is_net': True}
    assert m._stand_crm_fact_problem(board, crm, 'mf_auto') is None


@pytest.mark.parametrize('mode,source,rate,expected_margin', [
    ('usd', 45000, 82, 3), ('rub', 4000000, 82, 3),
    ('usd', 6000, 82, 5), ('usd', 6100, 82, 4),
    ('usd', 12190, 82, 4), ('usd', 12200, 82, 3),
])
def test_auto_quote_uses_calculator_ladder_and_preserves_request(mode, source, rate, expected_margin):
    from decimal import Decimal
    deal = {'autoPayment': True, 'step': 's6', 'autoRequestMode': mode,
            'requestedRub': source if mode == 'rub' else None,
            'requestedUsd': source if mode == 'usd' else None,
            'ippsTariff': 'bank', 'rates': {'rubUsdt': str(rate)}}
    m._stand_auto_quote_calculate(deal)
    assert deal['requestedRub' if mode == 'rub' else 'requestedUsd'] == source
    assert deal['invoiceUsd'] > 0 and deal['amountRub'] > 0
    if mode == 'rub':
        assert deal['amountRub'] == source
    else:
        assert deal['invoiceUsd'] == source
    rub = Decimal(str(deal['amountRub']))
    usd_amount = Decimal(str(deal['invoiceUsd']))
    if mode == 'usd':
        base = ((usd_amount+1)*rate*(1+Decimal(expected_margin)/100)).quantize(Decimal('.01'))
        expected_rub = (base*(usd_amount*Decimal('1.008')+50)/usd_amount).quantize(Decimal('.01'))
        assert rub == expected_rub
    else:
        before_fee = (rub/rate/(1+Decimal(expected_margin)/100)-1).quantize(Decimal('.01'))
        expected_usd = ((before_fee-50)/Decimal('1.008')).quantize(Decimal('.01'))
        assert usd_amount == expected_usd
    if mode == 'usd':
        assert (Decimal(source)*rate < 500000 and expected_margin == 5 or
                500000 <= Decimal(source)*rate < 1000000 and expected_margin == 4 or
                Decimal(source)*rate >= 1000000 and expected_margin == 3)


@pytest.mark.parametrize('mode', ['usd', 'rub'])
def test_auto_quote_rejects_amount_outside_matching_js_precision(mode):
    deal = {'autoPayment': True, 'step': 's6', 'autoRequestMode': mode,
            'requestedRub': 1000000000000 if mode == 'rub' else None,
            'requestedUsd': 542000000000 if mode == 'usd' else None,
            'ippsTariff': 'bank', 'rates': {'rubUsdt': '80'}}
    assert m._stand_auto_quote_calculate(deal) is False
    assert deal.get('amountRub') is None
    assert deal.get('invoiceUsd') is None


@pytest.mark.parametrize('mode', ['usd', 'rub'])
def test_manual_client_rub_survives_server_requote_and_checks_actual_margin(mode):
    from decimal import Decimal
    deal = {'autoPayment': True, 'step': 's6', 'autoRequestMode': mode,
            'requestedRub': 4000000 if mode == 'rub' else None,
            'requestedUsd': 45000 if mode == 'usd' else None,
            'ippsTariff': 'bank', 'rates': {'rubUsdt': '80'}}
    assert m._stand_auto_quote_calculate(deal)

    invoice = deal['invoiceUsd']
    requested = deal['requestedRub' if mode == 'rub' else 'requestedUsd']
    deal['amountRub'] = round(deal['amountRub'] + 1000, 2)
    manual_rub = deal['amountRub']
    deal['autoManualClientRub'] = True
    assert m._stand_auto_quote_calculate(deal)
    assert deal['amountRub'] == manual_rub
    assert deal['invoiceUsd'] == invoice
    assert deal['requestedRub' if mode == 'rub' else 'requestedUsd'] == requested
    assert Decimal(deal['rates']['client']) == (Decimal(str(manual_rub)) / Decimal(str(invoice))).quantize(Decimal('.000001'))
    deal['amountRub'] = round(manual_rub * 1.15, 2)
    assert m._stand_auto_quote_calculate(deal) is False
    deal['amountRub'] = manual_rub
    assert m._stand_auto_quote_calculate(deal)

def test_historical_auto_quote_allows_unchanged_state_but_checks_edits():
    import copy
    deal = {'id': 1, 'autoPayment': True, 'step': 's6', 'type': 'Оплата недвижимости',
            'kind': 'Фрихолд', 'payType': 'По реквизитам', 'invoiceCurrency': 'usd',
            'autoRequestMode': 'usd',
            'requestedUsd': 79800, 'requestedRub': None, 'invoiceUsd': 79800,
            'amountRub': 6991294.16, 'ippsTariff': 'soft', 'autoMarkupPct': 3,
            'rates': {'rubUsdt': '83.498', 'client': '87.610203'}}
    before = {'deals': [deal], 'convs': [], 'wallets': [], 'notes': []}
    after = copy.deepcopy(before)
    after['deals'][0]['comment'] = 'Согласовать реквизиты'
    assert m._stand_guard_transition(before, after, 'manager') is None
    agreed = copy.deepcopy(before)
    agreed['deals'][0]['step'] = 's8'
    assert m._stand_guard_transition(before, agreed, 'manager') is None
    edited = copy.deepcopy(before)
    edited['deals'][0]['amountRub'] += 100
    assert 'совпадать с расчётом' in m._stand_guard_transition(before, edited, 'manager')
    recalculated = copy.deepcopy(before)
    assert m._stand_auto_quote_calculate(recalculated['deals'][0])
    assert recalculated['deals'][0]['amountRub'] == 6970367.62
    assert m._stand_guard_transition(before, recalculated, 'manager') is None


@pytest.mark.parametrize('tariff,usd_amount', [('bank', 1005.11), ('soft', 1005.11),
                                               ('bank', 45000), ('soft', 45000)])
def test_old_quote_at_margin_floor_survives_manual_guard(tariff, usd_amount):
    deal = {'autoPayment': True, 'step': 's6', 'autoRequestMode': 'usd',
            'requestedUsd': usd_amount, 'ippsTariff': tariff, 'autoMarkupPct': 1.5,
            'rates': {'rubUsdt': '83.498'}}
    assert m._stand_auto_quote_calculate(deal)
    deal['autoManualClientRub'] = True
    assert m._stand_auto_quote_calculate(deal)


@pytest.mark.parametrize('mode', ['usd', 'rub'])
def test_manual_client_rub_guard_accepts_valid_and_rejects_invoice_change(mode):
    import copy
    deal = {'id': 1, 'autoPayment': True, 'step': 's6',
            'type': 'Оплата недвижимости', 'kind': 'Фрихолд',
            'payType': 'По реквизитам', 'invoiceCurrency': 'usd',
            'autoRequestMode': mode, 'requestedRub': 4000000 if mode == 'rub' else None,
            'requestedUsd': 45000 if mode == 'usd' else None,
            'ippsTariff': 'bank', 'rates': {'rubUsdt': '80'}}
    assert m._stand_auto_quote_calculate(deal)
    before = {'deals': [deal], 'convs': [], 'wallets': [], 'notes': []}
    after = copy.deepcopy(before)
    changed = after['deals'][0]
    changed['autoManualClientRub'] = True
    changed['amountRub'] = round(changed['amountRub'] + 1000, 2)
    assert m._stand_auto_quote_calculate(changed)
    assert m._stand_guard_transition(before, after, 'manager') is None
    bad = copy.deepcopy(after)
    bad['deals'][0]['invoiceUsd'] += 1
    assert 'выплату продавцу' in m._stand_guard_transition(before, bad, 'manager')
    accepted = copy.deepcopy(after)
    accepted['deals'][0]['step'] = 's8'
    changed_amount = copy.deepcopy(accepted)
    changed_amount['deals'][0]['amountRub'] += 100000
    assert 'сумму клиенту' in m._stand_guard_transition(accepted, changed_amount, 'manager')
    changed_rate = copy.deepcopy(accepted)
    changed_rate['deals'][0]['rates']['client'] = '99,999999'
    assert 'курс клиенту' in m._stand_guard_transition(accepted, changed_rate, 'manager')
    changed_markup = copy.deepcopy(after)
    changed_markup['deals'][0]['autoMarkupPct'] = 5
    assert 'При ручной сумме' in m._stand_guard_transition(after, changed_markup, 'manager')
    rerated = copy.deepcopy(accepted)
    rerated['deals'][0].update(step='s5', autoManualClientRub=False,
                               reRequest=1, rates={}, quotes=[], ratePick={})
    assert m._stand_guard_transition(accepted, rerated, 'manager') is None


@pytest.mark.parametrize('mode', ['sber', 'flowsole'])
def test_auto_atomic_crm_close_on_synthetic_conversion(monkeypatch, mode):
    import json
    import secrets
    from tests import test_stand_crm_close_atomic as h

    uid = h._setup(monkeypatch)
    db = m.get_session()
    try:
        row = db.query(m.StandState).filter_by(id=1).one()
        state = json.loads(row.data)
        deal = state['deals'][0]
        deal.update(type='Оплата недвижимости', kind='Фрихолд', autoPayment=True,
                        payType='По реквизитам', invoiceCurrency='usd',
                        autoRequestMode='usd', requestedUsd=45000,
                        rubReceivingAccount={'mode': mode},
                    postConv='ipps_swift', invoiceUsd=45000, ippsTariff='bank',
                    incomeAmount=4000000, amountRub=4000000, amountUsdt=47000,
                    rates={'broker': 82, 'client': 88.888889}, rubIsNet=True,
                    payTo={'purpose': 'AUTO-QA-1'},
                    mfPayout=[{'hash': 'demo:auto:1', 'net': 'TRC20', 'amount': 45410}],
                    payinParts=[{'incId': 'sber:auto-qa', 'amountRub': 4000000, 'rubIsNet': True}])
        deal['pay']['invoicePaid'] = True
        state['incomes'] = [{'id': 'sber:auto-qa', 'source': 'sber', 'rub': 4000000,
                             'dealId': deal['id'], 'uuid': secrets.token_hex(16)}]
        row.data = json.dumps(state)
        db.commit()
        h._seed_evidence(db, row, state, uid)
        state = json.loads(row.data)
        state['convs'][0]['sources'][0]['rub'] = 4000000
        row.data = json.dumps(state)
        db.commit()
        deal = state['deals'][0]
    finally:
        db.close()
    receipt = deal['payinHashes'][0]
    crm = {'deal_kind': 'mf_auto', 'client_name': deal['client'],
           'manager_name': 'Елизавета', 'payin_method': 'flow_sole_reqs' if mode == 'flowsole' else 'sber_reqs',
           'payin_amount_rub': 4000000, 'payin_rate_rub_usdt': 82,
           'payin_amount_usdt': 47000, 'payin_rub_is_net': True,
           'payin_tx_hashes': [{'hash': receipt['hash'], 'network': 'trc20',
                                'amount_usdt': 47000}],
           'payin_parts': [{'uuid': state['incomes'][0]['uuid'], 'amount_rub': 4000000,
                           'kind': 'transfer', 'net_rub': 4000000, 'payin_rub_is_net': True}],
           'payin_extra': [], 'realty_purpose': 'AUTO-QA-1',
           'invoice_amount_usd': 45000, 'transfer_fee_percent': .8,
           'transfer_fee_fixed_usd': 50, 'transfer_sent_usd': 45410,
           'payout_tx_hashes': [{'hash': 'demo:auto:1', 'network': 'trc20',
                                 'amount_usdt': 45410}]}
    if mode == 'flowsole':
        monkeypatch.setattr(m, '_flow_sole_payin_confirmation',
                            lambda *args, **kwargs: {'status': 'confirmed',
                                'declared_usdt': 47000, 'network_usdt': 47000,
                                'allocated_usdt': 47000})
    result = h._post(h._client(uid), crm=crm)
    assert result.status_code == 201, result.json
    assert result.json['deal']['deal_kind'] == 'mf_auto'
