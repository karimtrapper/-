"""Сев известных кошельков реестра — только на стенде, идемпотентно.

Что ловим:
- повторный запуск не плодит дубликаты и не переписывает решение админа;
- в прод-режиме сев не запускается вовсе (проверяем и по коду, и по тому,
  что тестовый процесс — STAND_MODE=0 — не содержит этих строк без вызова).

Запуск: cd Dev/CalcCRM && python -m pytest tests/test_wallet_registry_seed.py -v
"""
import inspect

import pytest

import app
from app import Wallet, get_session, _stand_seed_wallets


SEED_ADDRESSES = [
    'TKkeEVf2zySaWTLyX2qPwvi6kcdHRuPxkJ',
    'TVmgzMQ2zwV2DVPscBf98WRRdhrcpf5x5p',
    'TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn',
    '0x68aEA0F5386a57b48953F6fFF2f22D29D00D9ba9',
]


@pytest.fixture(autouse=True)
def clean_wallets():
    s = get_session()
    try:
        s.query(Wallet).delete()
        s.commit()
    finally:
        s.close()
    yield


def test_prod_mode_does_not_seed():
    """В тестовом процессе STAND_MODE не установлен — прод-режим не сеет реестр."""
    assert app.STAND_MODE is False
    # Стартовый вызов _stand_seed_wallets() живёт только под `if STAND_MODE:`
    # рядом с _stand_seed_users() — если его вынесут из-под guard, этот grep поймает.
    source = inspect.getsource(app)
    guard = source[source.index('if STAND_MODE:\n    _stand_migrate()'):]
    guard = guard[:guard.index('\n\n\n')]
    assert '_stand_seed_wallets()' in guard
    # И по факту: без явного вызова функции реестр пуст
    s = get_session()
    try:
        assert s.query(Wallet).filter(Wallet.address.in_(SEED_ADDRESSES)).count() == 0
    finally:
        s.close()


def test_seed_creates_known_wallets():
    _stand_seed_wallets()
    s = get_session()
    try:
        rows = {w.address: w for w in s.query(Wallet).filter(Wallet.address.in_(SEED_ADDRESSES)).all()}
        assert len(rows) == 4
        grusha = rows['TKkeEVf2zySaWTLyX2qPwvi6kcdHRuPxkJ']
        assert grusha.is_multisig is True
        assert grusha.accepts_payin is True
        assert grusha.owner == 'компания'
        teodor_erc = rows['0x68aEA0F5386a57b48953F6fFF2f22D29D00D9ba9']
        assert teodor_erc.blockchain == 'ETH'
        assert teodor_erc.accepts_payin is True
        assert teodor_erc.is_multisig is False
    finally:
        s.close()


def test_seed_is_idempotent_and_does_not_touch_existing_rows():
    _stand_seed_wallets()
    s = get_session()
    try:
        count_before = s.query(Wallet).count()
    finally:
        s.close()
    _stand_seed_wallets()
    s = get_session()
    try:
        assert s.query(Wallet).count() == count_before
    finally:
        s.close()


def test_seed_never_overrides_admin_edited_wallet():
    """Владелец уже задан вручную — сев не переписывает флаги при рестарте."""
    s = get_session()
    try:
        s.add(Wallet(address='TKkeEVf2zySaWTLyX2qPwvi6kcdHRuPxkJ', blockchain='TRON',
                     is_multisig=False, accepts_payin=False, owner='Кто-то другой'))
        s.commit()
    finally:
        s.close()
    _stand_seed_wallets()
    s = get_session()
    try:
        w = s.query(Wallet).filter(Wallet.address == 'TKkeEVf2zySaWTLyX2qPwvi6kcdHRuPxkJ').one()
        assert w.owner == 'Кто-то другой'
        assert w.is_multisig is False
        assert w.accepts_payin is False
    finally:
        s.close()
