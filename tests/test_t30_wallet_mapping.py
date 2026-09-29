"""Confirmed stand wallet ownership and exact legacy-state compatibility."""
import app
from stand_transfers import DEFAULT_WALLETS, expected_addresses, stand_wallet_address


GRUSHA = 'TKkeEVf2zySaWTLyX2qPwvi6kcdHRuPxkJ'
ANDREY = 'TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn'
CUSTOM = 'TVmgzMQ2zwV2DVPscBf98WRRdhrcpf5x5p'


def test_default_and_explicit_legacy_ids():
    state = {'wallets': [
        {'id': 'grusha', 'addr': ANDREY},
        {'id': 'vitaly', 'addr': GRUSHA},
        {'id': 'andrey', 'addr': 'адрес уточнить'},
    ]}
    assert DEFAULT_WALLETS['grusha'] == GRUSHA
    assert DEFAULT_WALLETS['andrey'] == ANDREY
    assert app._stand_payin_receiver(state, {}) == GRUSHA
    assert app._stand_payin_receiver(state, {'walletId': 'grusha'}) == GRUSHA
    assert app._stand_payin_receiver(state, {'walletId': 'vitaly'}) == GRUSHA
    assert app._stand_payin_receiver(state, {'walletId': 'andrey'}) == ANDREY
    assert app._stand_payin_receiver({'wallets': []}, {}) == GRUSHA
    assert stand_wallet_address(state, 'andrey') == ANDREY


def test_custom_and_unknown_wallets_are_not_replaced():
    state = {'wallets': [{'id': 'grusha', 'addr': CUSTOM},
                         {'id': 'other', 'addr': ANDREY}]}
    assert app._stand_payin_receiver(state, {'walletId': 'grusha'}) == CUSTOM
    assert app._stand_payin_receiver(state, {'walletId': 'other'}) == ANDREY
    assert app._stand_payin_receiver(state, {'walletId': 'unknown'}) is None
    assert expected_addresses(state, {'walletId': 'other',
                                      'transfer': {'addr': GRUSHA}}) == (ANDREY, GRUSHA)


def test_saved_legacy_wallet_is_not_mutated():
    state = {'wallets': [{'id': 'grusha', 'addr': ANDREY, 'owner': 'компания'}]}
    assert app._stand_payin_receiver(state, {}) == GRUSHA
    assert state['wallets'][0]['addr'] == ANDREY
