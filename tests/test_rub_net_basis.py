"""RUB basis is immutable per deal; bank conversion works in credited RUB."""
import json
import uuid

import pytest

import app as appmod
from app import (Conversion, ConversionSource, ConversionStatus, ConversionTx,
                 Deal, DealStatus, DealType, PayInMethod, PayOutSource, PayinTx,
                 SberIncome, app, get_session)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('LOCAL_NO_AUTH', '1')
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c


def test_create_basis_is_explicit_and_immutable(client):
    created = []
    try:
        for flag in (None, True):
            payload = {'client_name': 'RUB basis test', 'status': 'pending',
                       'payin_method': 'sber_reqs', 'payin_amount_rub': 100000,
                       'skip_sync': True}
            if flag is not None:
                payload['payin_rub_is_net'] = flag
            response = client.post('/api/deals', json=payload)
            assert response.status_code == 201, response.get_json()
            deal = response.get_json()['deal']
            created.append(deal['id'])
            assert deal['payin_rub_is_net'] is (flag is True)
            session = get_session()
            try:
                assert session.query(Deal).get(deal['id']).payin_rub_is_net is flag
            finally:
                session.close()

        legacy, net = created
        assert client.put(f'/api/deals/{legacy}', json={
            'payin_rub_is_net': True}).status_code == 409
        assert client.put(f'/api/deals/{net}', json={
            'payin_rub_is_net': False}).status_code == 409
        assert client.put(f'/api/deals/{legacy}', json={
            'payin_rub_is_net': 'false'}).status_code == 400
        assert client.post('/api/deals', json={
            'client_name': 'bad basis', 'payin_rub_is_net': 1}).status_code == 400

        changed = client.put(f'/api/deals/{legacy}', json={
            'payin_amount_rub': 110000, 'skip_sync': True})
        assert changed.status_code == 200, changed.get_json()
        assert changed.get_json()['deal']['payin_rub_is_net'] is False
        session = get_session()
        try:
            old = session.query(Deal).get(legacy)
            assert old.payin_rub_is_net is None
            assert old.payin_amount_rub == 110000
        finally:
            session.close()
    finally:
        session = get_session()
        try:
            session.query(Deal).filter(Deal.id.in_(created)).delete(synchronize_session=False)
            session.commit()
        finally:
            session.close()


def test_part_basis_inherits_without_materializing_legacy_false(client):
    old_part = {'uuid': 'historical', 'amount_rub': 100000, 'note': 'keep'}
    assert appmod._payin_parts_with_basis([old_part], False) == [old_part]
    assert 'rub_is_net' not in old_part
    assert appmod._payin_parts_with_basis([old_part], True)[0]['rub_is_net'] is True
    with pytest.raises(ValueError):
        appmod._payin_parts_with_basis([{'uuid': 'x', 'rub_is_net': False}], True)
    with pytest.raises(ValueError):
        appmod._normalize_payin_extra([{'method': 'sber_reqs', 'rub_is_net': False}],
                                      rub_is_net=True)


def test_partial_acquiring_share_and_unknown_fee():
    known = SberIncome(uuid=uuid.uuid4().hex, amount_rub=99300,
                       purpose='Зачисление средств по операциям эквайринга. Комиссия 700.00.')
    unknown = SberIncome(uuid=uuid.uuid4().hex, amount_rub=99300,
                         purpose='Зачисление средств по операциям эквайринга.')
    assert appmod._income_share_fraction(known, 50000, False, strict_fee=True) == 0.5
    assert appmod._income_share_fraction(known, 49650, True, strict_fee=True) == 0.5
    assert appmod._income_share_fraction(unknown, 50000, False, strict_fee=True) is None
    assert appmod._income_share_fraction(unknown, 49650, True, strict_fee=True) == 0.5
    assert unknown.to_dict()['fee_known'] is False
    assert unknown.to_dict()['fee_rub'] is None
    assert unknown.to_dict()['gross_rub'] is None

    gross = Deal(deal_type=DealType.PAY_IN, status=DealStatus.PENDING,
                 payin_method=PayInMethod.SBER_WL, payin_amount_rub=50000,
                 payin_parts=json.dumps([{'uuid': known.uuid, 'amount_rub': 50000}]))
    net = Deal(deal_type=DealType.PAY_IN, status=DealStatus.PENDING,
               payin_method=PayInMethod.SBER_WL, payin_amount_rub=49650,
               payin_rub_is_net=True,
               payin_parts=json.dumps([{'uuid': known.uuid, 'amount_rub': 49650,
                                        'rub_is_net': True}]))
    assert appmod._deal_bank_net_rub(gross, [known], strict_fee=True) == 49650
    assert appmod._deal_bank_net_rub(net, [known], strict_fee=True) == 49650
    gross.payin_parts = json.dumps([{'uuid': unknown.uuid, 'amount_rub': 50000}])
    assert appmod._deal_bank_net_rub(gross, [unknown], strict_fee=True) is None


def test_mixed_distribution_warns_for_unknown_gross_fee():
    session = get_session()
    deal_ids = []
    income_ids = []
    conv_id = None
    try:
        cases = [
            (None, 'Зачисление средств по операциям эквайринга. Комиссия 700.00.', 100000),
            (True, 'Зачисление средств по операциям эквайринга. Комиссия 700.00.', 99300),
            (None, 'Зачисление средств по операциям эквайринга.', 100000),
        ]
        for flag, purpose, amount in cases:
            income = SberIncome(uuid=uuid.uuid4().hex, operation_date='2026-09-11',
                                amount_rub=99300, payer='Эквайринг', purpose=purpose)
            deal = Deal(deal_type=DealType.PAY_IN, status=DealStatus.PENDING,
                        client_name='mixed basis', payin_method=PayInMethod.SBER_WL,
                        payin_amount_rub=amount, payin_rub_is_net=flag,
                        payin_parts=json.dumps([{'uuid': income.uuid,
                                                 'amount_rub': amount}]))
            session.add_all([income, deal]); session.flush()
            income.claimed_deal_id = deal.id
            deal_ids.append(deal.id)
            income_ids.append(income.id)
        conv = Conversion(broker='TRADEX', rate_rub_usdt=99.3)
        session.add(conv); session.flush()
        conv_id = conv.id
        for income_id in income_ids:
            session.add(ConversionSource(conversion_id=conv_id,
                                         sber_income_id=income_id, amount_rub=99300))
        session.commit()
        assert appmod._conversion_has_mixed_basis(session, {conv_id}) is True
        result = appmod.conversion_distribution(session, conv)
        reasons = {row['deal_id']: row['reason'] for row in result['blocked_deals']}
        assert deal_ids[0] not in reasons
        assert deal_ids[1] not in reasons
        assert 'Комиссия эквайринга неизвестна' in reasons[deal_ids[2]]
        assert result['needs_input'] is True
        assert result['margin_usdt'] is None
    finally:
        session.rollback()
        if conv_id is not None:
            session.query(ConversionSource).filter(
                ConversionSource.conversion_id == conv_id).delete()
            session.query(Conversion).filter(Conversion.id == conv_id).delete()
        if income_ids:
            session.query(SberIncome).filter(SberIncome.id.in_(income_ids)).delete(
                synchronize_session=False)
        if deal_ids:
            session.query(Deal).filter(Deal.id.in_(deal_ids)).delete(
                synchronize_session=False)
        session.commit()
        session.close()


def test_mixed_conversion_create_keeps_unknown_fee_as_warning(client):
    session = get_session()
    deal_ids, income_ids = [], []
    conv_id = None
    try:
        for flag, amount, credited, purpose in (
            (None, 100000, 99300, 'Зачисление средств по операциям эквайринга.'),
            (True, 40000, 40000, 'Перевод без комиссии'),
        ):
            income = SberIncome(uuid=uuid.uuid4().hex, operation_date='2026-09-11',
                                amount_rub=credited, payer='QA', purpose=purpose)
            deal = Deal(deal_type=DealType.PAY_IN, status=DealStatus.PENDING,
                        client_name='unknown fee API', payin_method=PayInMethod.SBER_WL,
                        payin_amount_rub=amount, payin_rub_is_net=flag,
                        payin_parts=json.dumps([{'uuid': income.uuid, 'amount_rub': amount}]))
            session.add_all([income, deal]); session.flush()
            income.claimed_deal_id = deal.id
            deal_ids.append(deal.id)
            income_ids.append(income.id)
        session.commit()

        response = client.post('/api/conversions', json={
            'broker': 'TRADEX', 'rate_rub_usdt': 99.3,
            'sources': [{'sber_income_id': sid} for sid in income_ids],
        })
        assert response.status_code == 200, response.get_json()
        conv_id = response.get_json()['conversion']['id']
        distribution = client.get(f'/api/conversions/{conv_id}/distribution').get_json()
        assert distribution['needs_input'] is True
        assert distribution['margin_usdt'] is None
        reasons = {row['deal_id']: row['reason'] for row in distribution['blocked_deals']}
        assert 'Комиссия эквайринга неизвестна' in reasons[deal_ids[0]]
        assert deal_ids[1] not in reasons

        conv_id = response.get_json()['conversion']['id']
    finally:
        session.rollback()
        if conv_id is not None:
            session.query(ConversionSource).filter(
                ConversionSource.conversion_id == conv_id).delete()
            session.query(Conversion).filter(Conversion.id == conv_id).delete()
        session.query(SberIncome).filter(SberIncome.id.in_(income_ids)).delete(
            synchronize_session=False)
        session.query(Deal).filter(Deal.id.in_(deal_ids)).delete(
            synchronize_session=False)
        session.commit()
        session.close()


def test_mixed_partial_multi_income_extra_needs_shares_without_blocking_create(client):
    session = get_session()
    deal_ids, income_ids = [], []
    conv_id = None
    try:
        gross_incomes = []
        for credited, fee in ((99300, 700), (98000, 2000)):
            income = SberIncome(uuid=uuid.uuid4().hex, operation_date='2026-09-11',
                                amount_rub=credited, payer='QA',
                                purpose=f'Зачисление средств по операциям эквайринга. Комиссия {fee}.')
            session.add(income)
            gross_incomes.append(income)
        session.flush()
        extra = {'method': 'sber_wl', 'amount_rub': 120000,
                 'amount_usdt': 1200,
                 'rub_is_net': False,
                 'sber_uuids': [inc.uuid for inc in gross_incomes]}
        gross_deal = Deal(deal_type=DealType.PAY_IN, status=DealStatus.PENDING,
                          client_name='partial extra API', payin_method=PayInMethod.SBER_WL,
                          payin_amount_rub=120000, payin_amount_usdt=1200,
                          payin_extra=json.dumps([extra]),
                          payin_parts=json.dumps([{'uuid': inc.uuid, 'amount_rub': None}
                                                  for inc in gross_incomes]),
                          payout_source=PayOutSource.FOUNDER_PERSONAL,
                          payout_amount_usdt=1000)
        session.add(gross_deal); session.flush()
        for inc in gross_incomes:
            inc.claimed_deal_id = gross_deal.id
            income_ids.append(inc.id)
        deal_ids.append(gross_deal.id)

        net_income = SberIncome(uuid=uuid.uuid4().hex, operation_date='2026-09-11',
                                amount_rub=50000, payer='QA', purpose='Перевод без комиссии')
        net_deal = Deal(deal_type=DealType.PAY_IN, status=DealStatus.PENDING,
                        client_name='net alongside extra', payin_method=PayInMethod.SBER_WL,
                        payin_amount_rub=50000, payin_rub_is_net=True,
                        payin_parts=json.dumps([{'uuid': net_income.uuid,
                                                 'amount_rub': 50000, 'rub_is_net': True}]))
        session.add_all([net_income, net_deal]); session.flush()
        net_income.claimed_deal_id = net_deal.id
        income_ids.append(net_income.id)
        deal_ids.append(net_deal.id)
        session.commit()

        issues = []
        assert appmod._deal_bank_net_rub(
            gross_deal, gross_incomes, strict_fee=True, issues=issues) is None
        assert 'shares_missing' in issues
        full_extra = Deal(deal_type=DealType.PAY_IN, status=DealStatus.PENDING,
                          payin_method=PayInMethod.SBER_WL, payin_amount_rub=200000,
                          payin_extra=json.dumps([dict(extra, amount_rub=200000)]))
        assert appmod._deal_bank_net_rub(full_extra, gross_incomes, strict_fee=True) == 197300
        one_income = Deal(deal_type=DealType.PAY_IN, status=DealStatus.PENDING,
                          payin_method=PayInMethod.SBER_WL, payin_amount_rub=50000,
                          payin_extra=json.dumps([dict(extra, amount_rub=50000,
                                                       sber_uuids=[gross_incomes[0].uuid])]))
        assert appmod._deal_bank_net_rub(one_income, gross_incomes[:1], strict_fee=True) == 49650

        partial_response = client.post('/api/conversions', json={
            'broker': 'TRADEX', 'rate_rub_usdt': 99.3,
            'sources': [{'sber_income_id': income_ids[0]},
                        {'sber_income_id': income_ids[2]}],
        })
        assert partial_response.status_code == 409
        assert partial_response.get_json()['error_code'] == 'bank_deal_conversion_lock'

        response = client.post('/api/conversions', json={
            'broker': 'TRADEX', 'rate_rub_usdt': 99.3,
            'sources': [{'sber_income_id': sid} for sid in income_ids],
        })
        assert response.status_code == 200, response.get_json()
        conv_id = response.get_json()['conversion']['id']
        distribution = client.get(f'/api/conversions/{conv_id}/distribution').get_json()
        assert distribution['needs_input'] is True
        assert distribution['margin_usdt'] is None
        reasons = {row['deal_id']: row['reason'] for row in distribution['blocked_deals']}
        assert reasons[deal_ids[0]] == 'не заданы доли по поступлениям'
        assert deal_ids[1] not in reasons
        deferred = [row for group in distribution['to_return']
                    for row in group['deferred_deals']]
        assert any(row['deal_id'] == deal_ids[0] for row in deferred)
        assert all(group['amount_usdt'] is None for group in distribution['to_return'])
    finally:
        session.rollback()
        if conv_id is not None:
            session.query(ConversionSource).filter(
                ConversionSource.conversion_id == conv_id).delete()
            session.query(Conversion).filter(Conversion.id == conv_id).delete()
        session.query(SberIncome).filter(SberIncome.id.in_(income_ids)).delete(
            synchronize_session=False)
        session.query(Deal).filter(Deal.id.in_(deal_ids)).delete(
            synchronize_session=False)
        session.commit()
        session.close()


def test_distribution_assigns_only_known_half_of_gross_and_net_incomes(client):
    session = get_session()
    deal_ids, income_ids = [], []
    conv_id = None
    tx_id = None
    try:
        for flag, amount in ((None, 30200), (True, 30000)):
            income = SberIncome(uuid=uuid.uuid4().hex, operation_date='2026-09-11',
                                amount_rub=60000, payer='QA',
                                purpose='Зачисление средств по операциям эквайринга. Комиссия 400.')
            deal = Deal(deal_type=DealType.PAY_IN, status=DealStatus.PENDING,
                        client_name='half income', payin_method=PayInMethod.SBER_WL,
                        payin_amount_rub=amount, payin_rub_is_net=flag,
                        payin_parts=json.dumps([{'uuid': income.uuid, 'amount_rub': amount,
                                                 **({'rub_is_net': True} if flag else {})}]))
            session.add_all([income, deal]); session.flush()
            income.claimed_deal_id = deal.id
            deal_ids.append(deal.id)
            income_ids.append(income.id)
        session.commit()

        response = client.post('/api/conversions', json={
            'broker': 'TRADEX', 'rate_rub_usdt': 98, 'held_percent': 0,
            'held_fixed_rub': 0,
            'sources': [{'sber_income_id': sid} for sid in income_ids],
        })
        assert response.status_code == 200, response.get_json()
        conv_id = response.get_json()['conversion']['id']
        tx = PayinTx(tx_hash=uuid.uuid4().hex, amount_usdt=1224.49, source='manual')
        session.add(tx); session.flush()
        tx_id = tx.id
        session.add(ConversionTx(conversion_id=conv_id, payin_tx_id=tx_id,
                                 amount_usdt=1224.49))
        session.query(Conversion).get(conv_id).status = ConversionStatus.RECEIVED
        session.commit()
        distribution = client.get(f'/api/conversions/{conv_id}/distribution').get_json()
        rows = {row['deal_id']: row for row in distribution['no_return_deals']}
        assert set(rows) == set(deal_ids)
        assert all(abs(row['share_usdt'] - 306.12) < 0.02 for row in rows.values())
        assert distribution['needs_input'] is True
        assert distribution['balanced'] is False
        assert distribution['margin_usdt'] is None
        assert len(distribution['unassigned_incomes']) == 2
        assert {row['partial_deal_id'] for row in distribution['unassigned_incomes']} == set(deal_ids)
        assert abs(distribution['received_usdt'] - distribution['no_return_usdt']
                   - distribution['unassigned_usdt']) < 0.02
    finally:
        session.rollback()
        if conv_id is not None:
            session.query(ConversionTx).filter(
                ConversionTx.conversion_id == conv_id).delete()
            session.query(ConversionSource).filter(
                ConversionSource.conversion_id == conv_id).delete()
            session.query(Conversion).filter(Conversion.id == conv_id).delete()
        if tx_id is not None:
            session.query(PayinTx).filter(PayinTx.id == tx_id).delete()
        session.query(SberIncome).filter(SberIncome.id.in_(income_ids)).delete(
            synchronize_session=False)
        session.query(Deal).filter(Deal.id.in_(deal_ids)).delete(
            synchronize_session=False)
        session.commit()
        session.close()
