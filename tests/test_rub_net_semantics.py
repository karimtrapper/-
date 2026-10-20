"""Immutable RUB basis across CRM, bank receipts and stand conversion."""
import json
import uuid

import pytest

import app as m
from sber_acquiring import parse_sber_acquiring
from stand_sber_mirror import _board_income


def _id():
    return 'rubnet-' + uuid.uuid4().hex


@pytest.mark.parametrize('bad', [0, 1, 'true'])
def test_create_rejects_non_boolean_basis(monkeypatch, bad):
    monkeypatch.setenv('LOCAL_NO_AUTH', '1')
    response = m.app.test_client().post('/api/deals', json={
        'client_name': _id(), 'payin_method': 'sber_reqs',
        'payin_rub_is_net': bad})
    assert response.status_code == 400
    assert 'boolean' in response.json['error']


def test_legacy_null_accepts_false_without_rewriting_or_changing_parts(monkeypatch):
    monkeypatch.setenv('LOCAL_NO_AUTH', '1')
    db = m.get_session()
    deal = m.Deal(client_name=_id(), deal_type=m.DealType.PAY_IN,
        status=m.DealStatus.PENDING, payin_method=m.PayInMethod.SBER_REQS,
        payin_amount_rub=10000, payin_rub_is_net=None,
        payin_parts=json.dumps([{'uuid': 'old', 'amount_rub': 10000}]))
    db.add(deal); db.commit(); deal_id = deal.id; db.close()
    try:
        client = m.app.test_client()
        response = client.put(f'/api/deals/{deal_id}', json={
            'payin_rub_is_net': False, 'notes': 'ordinary edit'})
        assert response.status_code == 200, response.json
        db = m.get_session()
        saved = db.get(m.Deal, deal_id)
        assert saved.payin_rub_is_net is None
        assert json.loads(saved.payin_parts) == [{'uuid': 'old', 'amount_rub': 10000}]
        db.close()
        assert client.put(f'/api/deals/{deal_id}', json={
            'payin_rub_is_net': True}).status_code == 409
        for bad in (0, 1, 'true'):
            assert client.put(f'/api/deals/{deal_id}', json={
                'payin_rub_is_net': bad}).status_code == 400
        for key, part in (
            ('payin_parts', {'uuid': 'old', 'amount_rub': 10000, 'payin_rub_is_net': True}),
            ('payin_extra', {'method': 'sber_reqs', 'amount_usdt': 100,
                             'payin_rub_is_net': True}),
            ('payin_extra', {'method': 'sber_reqs', 'amount_usdt': 100,
                             'sber_parts': [{'payin_rub_is_net': True}]}),
        ):
            assert client.put(f'/api/deals/{deal_id}', json={key: [part]}).status_code == 409
        for bad in (0, 1, 'true'):
            assert client.put(f'/api/deals/{deal_id}', json={
                'payin_parts': [{'uuid': 'old', 'payin_rub_is_net': bad}]}).status_code == 400
    finally:
        db = m.get_session(); db.query(m.Deal).filter_by(id=deal_id).delete()
        db.commit(); db.close()


def test_known_zero_and_unknown_acquiring_fee_are_distinct():
    zero = parse_sber_acquiring('Эквайринг. Комиссия 0.00. Мерчант №123')
    unknown = parse_sber_acquiring('Эквайринг. Мерчант №123')
    assert zero['fee_known'] is True and zero['fee_rub'] == 0
    assert unknown['fee_known'] is False
    row = m.SberIncome(uuid=_id(), amount_rub=9000, operation_date='2026-10-20',
        purpose='Эквайринг. Мерчант №123')
    assert row.to_dict()['gross_rub'] is None
    assert row.to_dict()['fee_rub'] is None
    assert _board_income(row)['grossRub'] is None


def test_new_net_deal_rejects_gross_parts_and_extra(monkeypatch):
    monkeypatch.setenv('LOCAL_NO_AUTH', '1')
    for key, value in (
        ('payin_parts', [{'uuid': 'x', 'amount_rub': 100,
                          'payin_rub_is_net': False}]),
        ('payin_extra', [{'method': 'sber_reqs', 'amount_usdt': 1,
                          'payin_rub_is_net': False}]),
    ):
        result = m.app.test_client().post('/api/deals', json={
            'client_name': _id(), 'payin_method': 'sber_reqs',
            'payin_rub_is_net': True, key: value})
        assert result.status_code == 409


def test_extra_normalization_keeps_explicit_net_without_backfilling_legacy():
    base = {'method': 'sber_reqs', 'amount_rub': 9000, 'amount_usdt': 90}
    old = m._normalize_payin_extra([base])[0]
    new = m._normalize_payin_extra([{**base, 'payin_rub_is_net': True}])[0]
    assert 'payin_rub_is_net' not in old
    assert new['payin_rub_is_net'] is True


@pytest.mark.parametrize('is_net,taken,expected', [
    (True, 4500, 45.0), (False, 5000, 45.0),
])
def test_partial_conversion_uses_only_proportional_fee(monkeypatch, is_net, taken, expected):
    db = m.get_session()
    income = m.SberIncome(uuid=_id(), operation_date='2026-10-20',
        amount_rub=9000, purpose='Эквайринг. Комиссия 1000.00.')
    deal = m.Deal(client_name=_id(), deal_type=m.DealType.PAY_IN,
        status=m.DealStatus.PENDING, payin_method=m.PayInMethod.SBER_WL,
        payin_amount_rub=taken, payin_rub_is_net=is_net)
    db.add_all([income, deal]); db.flush()
    income.claimed_deal_id = deal.id
    deal.payin_parts = json.dumps([{'uuid': income.uuid, 'amount_rub': taken,
        'payin_rub_is_net': is_net}])
    monkeypatch.setattr(m.SberIncome, 'free_rub', lambda self: 0)
    monkeypatch.setattr(m, '_income_conversion_usdt', lambda db, ids: {income.id: 90.0})
    try:
        assert m._fill_payin_usdt_from_conversion(db, deal)
        assert deal.payin_amount_usdt == expected
    finally:
        db.rollback(); db.close()


def test_unknown_fee_suppresses_gross_result_but_allows_net(monkeypatch):
    db = m.get_session()
    income = m.SberIncome(uuid=_id(), operation_date='2026-10-20',
        amount_rub=9000, purpose='Эквайринг без указанной комиссии')
    deal = m.Deal(client_name=_id(), deal_type=m.DealType.PAY_IN,
        status=m.DealStatus.PENDING, payin_method=m.PayInMethod.SBER_WL,
        payin_amount_rub=9000, payin_rub_is_net=False)
    db.add_all([income, deal]); db.flush()
    income.claimed_deal_id = deal.id
    deal.payin_parts = json.dumps([{'uuid': income.uuid, 'amount_rub': 9000}])
    monkeypatch.setattr(m.SberIncome, 'free_rub', lambda self: 0)
    monkeypatch.setattr(m, '_income_conversion_usdt', lambda db, ids: {income.id: 90.0})
    try:
        assert not m._fill_payin_usdt_from_conversion(db, deal)
        assert deal.payin_amount_usdt is None
        deal.payin_rub_is_net = True
        deal.payin_parts = json.dumps([{'uuid': income.uuid, 'amount_rub': 9000,
            'payin_rub_is_net': True}])
        assert m._fill_payin_usdt_from_conversion(db, deal)
        assert deal.payin_amount_usdt == 90
    finally:
        db.rollback(); db.close()


@pytest.mark.parametrize('fees,taken,net,expected', [
    ([1000, 2000], 10000, False, 'needs_input'),
    ([1000, 2000], 23000, False, None),
    ([1000, 2000], 10000, True, None),
    ([1000, None], 10000, False, 'needs_input'),
    ([1000], 5000, False, None),
])
def test_extra_allocation_only_marks_undetermined_gross_shares(fees, taken, net, expected):
    db = m.get_session()
    rows = [m.SberIncome(uuid=_id(), operation_date='2026-10-20',
        amount_rub=9000 if i == 0 else 11000,
        purpose=('Эквайринг. Комиссия %.2f.' % fee if fee is not None
                 else 'Эквайринг без указанной комиссии'))
        for i, fee in enumerate(fees)]
    deal = m.Deal(client_name=_id(), deal_type=m.DealType.PAY_IN,
        status=m.DealStatus.PENDING, payin_rub_is_net=net,
        payin_extra=json.dumps([{'method': 'sber_wl', 'amount_rub': taken,
            'amount_usdt': 100, 'sber_uuids': [r.uuid for r in rows]}]))
    db.add_all([*rows, deal]); db.flush()
    try:
        m._refresh_payin_allocation_status(db, deal)
        assert deal.payin_allocation_status == expected
        if expected:
            deal.payin_amount_usdt = 100
            deal.payout_amount_usdt = 90
            deal.profit_usdt = 10
            m._clear_profit_if_payin_unknown(deal)
            assert deal.profit_usdt is None
            assert deal.to_dict()['payin_allocation_warning'] == 'не заданы доли по поступлениям'
    finally:
        db.rollback(); db.close()


def test_stand_mixed_basis_normalizes_to_credited_rub():
    gross = {'id': 'sber:g', 'source': 'sber', 'accountKey': 'sber',
        'rub': 9000, 'grossRub': 10000, 'kind': 'acquiring'}
    net = {'id': 'sber:n', 'source': 'sber', 'accountKey': 'sber',
        'rub': 4500, 'grossRub': None, 'kind': 'acquiring'}
    deal = {'id': 1, 'rubIsNet': False, 'conv': [2], 'payinParts': [
        {'incId': 'sber:g', 'amountRub': 10000}]}
    other = {'id': 2, 'rubIsNet': True, 'payinParts': [
        {'incId': 'sber:n', 'amountRub': 4500, 'rubIsNet': True}]}
    state = {'deals': [deal, other], 'incomes': [gross, net]}
    assert m._stand_broker_draft_rub(state, deal) == 13500
    gross['grossRub'] = None
    assert m._stand_broker_draft_rub(state, deal) is None


def test_flow_rub_entry_alone_is_not_verified_payin():
    deal = {'id': 1, 'payType': 'По реквизитам', 'rubIsNet': True,
        'amountRub': 12000, 'rubReceivingAccount': {'mode': 'flowsole'},
        'payinParts': [], 'payinHashes': []}
    source, problem = m._stand_close_fact_source({'deals': [deal], 'incomes': [], 'convs': []},
        deal, 'payin')
    assert source is None and problem == 'verified_payin_missing'
