"""RUB basis is immutable per deal; bank conversion works in credited RUB."""
import json
import uuid

import pytest

import app as appmod
from app import (Conversion, ConversionSource, Deal, DealStatus, DealType,
                 PayInMethod, SberIncome, app, get_session)


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
