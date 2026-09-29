"""Confirmed stand wallet ownership and exact legacy-state compatibility.

С единым реестром кошельков (wallet-registry) источник истины для _stand_payin_target
переехал из state['wallets'] в таблицу CRM `wallets`. Тест проверяет, что легаси
walletId по-прежнему резолвится в те же адреса — через реестр, если строка там
есть, и по прежним правилам, если реестра ещё нет.
"""
import pytest

import app
from app import Wallet, get_session


GRUSHA = 'TKkeEVf2zySaWTLyX2qPwvi6kcdHRuPxkJ'
ANDREY = 'TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn'
TEODOR = 'TVmgzMQ2zwV2DVPscBf98WRRdhrcpf5x5p'
TEODOR_ERC = '0x68aEA0F5386a57b48953F6fFF2f22D29D00D9ba9'


@pytest.fixture(autouse=True)
def clean_wallets():
    s = get_session()
    try:
        s.query(Wallet).delete()
        s.commit()
    finally:
        s.close()
    yield


def test_legacy_ids_without_registry_row_use_fixed_network():
    """Реестр ещё не засеян — легаси-адрес резолвится по прежним правилам сети."""
    assert app._stand_payin_receiver({}, {}) == GRUSHA
    assert app._stand_payin_receiver({}, {'walletId': 'grusha'}) == GRUSHA
    assert app._stand_payin_receiver({}, {'walletId': 'vitaly'}) == GRUSHA
    assert app._stand_payin_receiver({}, {'walletId': 'andrey'}) == ANDREY
    assert app._stand_payin_receiver({}, {'walletId': 'teodor-erc'}) == TEODOR_ERC
    assert app._stand_payin_target({}, {'walletId': 'teodor-erc'})[0] == 'erc20'


def test_legacy_ids_resolve_through_registry_row():
    """Когда реестр знает адрес, сеть и владелец берутся из его строки."""
    s = get_session()
    try:
        s.add(Wallet(address=GRUSHA, blockchain='TRON', owner='компания',
                     is_multisig=True, accepts_payin=True))
        s.add(Wallet(address=ANDREY, blockchain='TRON', owner='Андрей',
                     is_multisig=False, accepts_payin=True))
        s.commit()
    finally:
        s.close()
    assert app._stand_payin_receiver({}, {'walletId': 'grusha'}) == GRUSHA
    assert app._stand_payin_receiver({}, {'walletId': 'vitaly'}) == GRUSHA
    assert app._stand_payin_receiver({}, {'walletId': 'andrey'}) == ANDREY
    assert app._stand_payin_target({}, {'walletId': 'grusha'})[0] == 'trc20'


def test_registry_wallet_by_numeric_id():
    """Новый формат: walletId — числовой id кошелька реестра (из дропдауна)."""
    s = get_session()
    try:
        w = Wallet(address=TEODOR, blockchain='TRON', owner='Теодор',
                  is_multisig=False, accepts_payin=True)
        s.add(w)
        s.commit()
        wid = w.id
    finally:
        s.close()
    assert app._stand_payin_receiver({}, {'walletId': str(wid)}) == TEODOR


def test_registry_wallet_without_accepts_payin_is_not_selectable():
    """Кошелёк без accepts_payin недоступен как приход, даже по своему id."""
    s = get_session()
    try:
        w = Wallet(address=ANDREY, blockchain='TRON', owner='Андрей', accepts_payin=False)
        s.add(w)
        s.commit()
        wid = w.id
    finally:
        s.close()
    assert app._stand_payin_target({}, {'walletId': str(wid)}) == (None, None)


def test_custom_wallet_is_not_replaced_by_registry():
    custom = {'network': 'TRC-20', 'addr': TEODOR}
    assert app._stand_payin_receiver({}, {'walletId': 'custom', 'payinCustom': custom}) == TEODOR
    assert app._stand_payin_receiver({}, {'walletId': 'grusha', 'payinCustom': custom}) is None


def test_unknown_wallet_id_resolves_to_nothing():
    assert app._stand_payin_receiver({}, {'walletId': 'unknown'}) is None
    assert app._stand_payin_receiver({}, {'walletId': 'w1699999999'}) is None
