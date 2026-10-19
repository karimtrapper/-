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
    assert problem == ('Этот флоу (тип сделки + способ оплаты) ещё не проверен. '
                        'Проведите сделку через Карима.')


def test_stand_create_unverified_combo_rejected_for_admin_without_confirm():
    previous = empty_board()
    new_state = {'wallets': [], 'convs': [], 'deals': [rental_cash_deal()]}
    problem = appmod._stand_guard_transition(previous, new_state, 'admin')
    assert problem == ('Непроверенный флоу. Требуется подтверждение '
                        '(unverified_confirmed=true).')


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


def test_stand_manager_cannot_bypass_with_confirm_flag():
    previous = empty_board()
    new_state = {'wallets': [], 'convs': [],
                 'deals': [rental_cash_deal(unverified_confirmed=True)]}
    problem = appmod._stand_guard_transition(previous, new_state, 'manager')
    assert problem == ('Этот флоу (тип сделки + способ оплаты) ещё не проверен. '
                        'Проведите сделку через Карима.')


def test_stand_change_to_unverified_combo_rejected_for_manager():
    previous = {'wallets': [], 'convs': [], 'deals': [freehold_requisites_deal(step='s4')]}
    new_state = {'wallets': [], 'convs': [],
                 'deals': [freehold_requisites_deal(step='s4', payType='Наличные')]}
    problem = appmod._stand_guard_transition(previous, new_state, 'manager')
    assert problem == ('Этот флоу (тип сделки + способ оплаты) ещё не проверен. '
                        'Проведите сделку через Карима.')
