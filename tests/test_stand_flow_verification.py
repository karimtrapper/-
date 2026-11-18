"""Ворота на неподтверждённые флоу (тип сделки + способ Pay-In) при создании
заявки и смене способа на доске стенда. _stand_guard_transition вызывается
напрямую на чистых фикстурах — тот же код, что исполняется в PUT /api/stand/state.
"""

import pytest

pytestmark = pytest.mark.usefixtures('stand_demo_environment')

import app as appmod


def empty_board():
    return {'wallets': [], 'convs': [], 'deals': []}


def rental_cash_deal(deal_id=1, **overrides):
    deal = {
        'id': deal_id, 'code': f'СД-{deal_id}', 'client': 'Денис',
        'type': 'Оплата недвижимости', 'kind': 'Аренда', 'payType': 'Наличные',
        'step': 's4', 'pay': {}, 'payout': {}, 'payTo': {}, 'docs': {}, 'log': [],
    }
    deal.update(overrides)
    return deal


def freehold_requisites_deal(deal_id=1, **overrides):
    deal = {
        'id': deal_id, 'code': f'СД-{deal_id}', 'client': 'Клиент',
        'type': 'Оплата недвижимости', 'kind': 'Фрихолд', 'payType': 'По реквизитам',
        'step': 's4', 'pay': {}, 'payout': {}, 'payTo': {}, 'docs': {}, 'log': [],
    }
    deal.update(overrides)
    return deal


def test_stand_create_unverified_combo_rejected_for_manager():
    previous = empty_board()
    new_state = {'wallets': [], 'convs': [], 'deals': [rental_cash_deal()]}
    problem = appmod._stand_guard_transition(previous, new_state, 'manager')
    assert problem == 'Подтвердите выбор непроверенного способа оплаты.'


def test_stand_create_unverified_combo_rejected_for_admin_without_confirm():
    new_state = dict(empty_board(), deals=[rental_cash_deal()])
    assert appmod._stand_guard_transition(empty_board(), new_state, 'admin') == (
        'Подтвердите выбор непроверенного способа оплаты.')


def test_stand_create_unverified_combo_allowed_for_admin_with_confirm():
    previous = empty_board()
    new_state = {'wallets': [], 'convs': [],
                 'deals': [rental_cash_deal(unverified_confirmed=True)]}
    assert appmod._stand_guard_transition(previous, new_state, 'admin') is None


def test_stand_create_verified_combo_allowed_for_manager():
    previous = empty_board()
    new_state = {'wallets': [], 'convs': [], 'deals': [freehold_requisites_deal()]}
    assert appmod._stand_guard_transition(previous, new_state, 'manager') is None


def test_stand_existing_unverified_deal_progresses_untouched():
    previous = {'wallets': [], 'convs': [], 'deals': [rental_cash_deal(step='s4')]}
    new_state = {'wallets': [], 'convs': [], 'deals': [rental_cash_deal(step='s5')]}
    assert appmod._stand_guard_transition(previous, new_state, 'manager') is None


@pytest.mark.parametrize('kind,method,confirmation', [
    ('Аренда', 'Наличные', ['rental', 'cash']),
    ('Лизхолд', 'СБП', ['leasehold', 'sbp']),
    ('Фрихолд', 'Крипта', ['freehold', 'crypto']),
])
def test_stand_manager_can_create_with_exact_confirmation(kind, method, confirmation):
    new_state = dict(empty_board(), deals=[rental_cash_deal(
        kind=kind, payType=method, unverified_flow_confirmation=confirmation)])
    assert appmod._stand_guard_transition(empty_board(), new_state, 'manager') is None


@pytest.mark.parametrize('confirmation', [True, ['rental', 'crypto'], ['freehold', 'cash'], [None, None]])
def test_stand_manager_rejects_legacy_or_mismatched_confirmation(confirmation):
    new_state = dict(empty_board(), deals=[rental_cash_deal(
        unverified_confirmed=True, unverified_flow_confirmation=confirmation)])
    assert appmod._stand_guard_transition(empty_board(), new_state, 'manager') == (
        'Подтвердите выбор непроверенного способа оплаты.')


def test_stand_manager_cannot_confirm_unknown_combo():
    new_state = dict(empty_board(), deals=[rental_cash_deal(
        kind='unknown', payType='unknown', unverified_flow_confirmation=[None, None])])
    assert appmod._stand_guard_transition(empty_board(), new_state, 'manager') == (
        'Подтвердите выбор непроверенного способа оплаты.')


@pytest.mark.parametrize('actor', ['manager', 'admin'])
def test_stand_change_to_unverified_combo_requires_fresh_confirmation(actor):
    before = freehold_requisites_deal(unverified_confirmed=True)
    previous = dict(empty_board(), deals=[before])
    deal = dict(before, payType='Наличные')
    new_state = dict(empty_board(), deals=[deal])
    assert appmod._stand_guard_transition(previous, new_state, actor) == (
        'Подтвердите выбор непроверенного способа оплаты.')
    deal['unverified_flow_confirmation'] = ['freehold', 'cash']
    assert appmod._stand_guard_transition(previous, new_state, actor) is None


def test_stand_operator_cannot_confirm_unverified_combo():
    new_state = dict(empty_board(), deals=[rental_cash_deal(
        unverified_flow_confirmation=['rental', 'cash'])])
    assert appmod._stand_guard_transition(empty_board(), new_state, 'operator') == (
        'Этот флоу (тип сделки + способ оплаты) ещё не проверен. Проведите сделку через Карима.')
