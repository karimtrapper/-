"""Synthetic T31b discovery; run via scripts/run_t29_fenced_pytest.py."""

from decimal import Decimal
from unittest.mock import patch

import pytest

import stand_egress
from stand_transfer_discovery import (USDT_TRC20, discover_transfers,
                                      match_transfer, parse_transfer)


WALLET = 'TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn'
OTHER = 'TKkeEVf2zySaWTLyX2qPwvi6kcdHRuPxkJ'
THIRD = 'TVmgzMQ2zwV2DVPscBf98WRRdhrcpf5x5p'
MARKER = 1_700_000_000_000


def row(n=1, *, quant='1000000', ts=MARKER, sender=OTHER, recipient=WALLET,
        contract=USDT_TRC20, confirmed=True, result='SUCCESS', net='trc20'):
    return {'transaction_id': f'{n:064x}', 'quant': quant, 'block_ts': ts,
            'from_address': sender, 'to_address': recipient,
            'contract_address': contract, 'confirmed': confirmed,
            'finalResult': result, 'net': net}


def query(**overrides):
    values = dict(direction='incoming', wallet_addr=WALLET,
                  expected_amount=Decimal('1'), tolerance=Decimal('0'),
                  after_ts=MARKER, network='trc20', counterparty_addr=None)
    values.update(overrides)
    return values


def scan(pages, **kwargs):
    calls = []
    def fake(op, params):
        calls.append((op, params.copy()))
        return pages[params['start']]
    with patch.object(stand_egress, 'read_get', fake):
        result = discover_transfers(**query(**kwargs))
    assert all(op == 'tron_trc20_transfers' and params == {
        'relatedAddress': WALLET, 'contract_address': USDT_TRC20,
        'limit': 50, 'start': index * 50} for index, (op, params) in enumerate(calls))
    return result, calls


def match_query(**overrides):
    values = query(**overrides)
    values.pop('network')
    return values


@pytest.mark.parametrize('rows,count', [([], 0), ([row()], 1),
                                          ([row(1), row(2), row(3)], 3)])
def test_zero_one_many_candidates(rows, count):
    result, _ = scan({0: (200, {'token_transfers': rows, 'total': len(rows)}, None)})
    assert result['status'] == 'complete'
    assert len(result['candidates']) == count


def test_decimal_exact_tolerance_and_cent_boundary():
    rows = [row(1, quant='1000000'), row(2, quant='1009999'),
            row(3, quant='1010000'), row(4, quant='1010001'),
            row(5, quant='990000'), row(6, quant='989999')]
    result, _ = scan({0: (200, {'token_transfers': rows, 'total': len(rows)}, None)},
                     tolerance=Decimal('0.01'))
    assert [c['hash'] for c in result['candidates']] == [f'{n:064x}' for n in (1, 2, 3, 5)]
    assert all(type(c['amount']) is Decimal for c in result['candidates'])
    exact, _ = scan({0: (200, {'token_transfers': rows, 'total': len(rows)}, None)})
    assert [c['hash'] for c in exact['candidates']] == [f'{1:064x}']


def test_parser_rejects_bad_chain_facts_and_matches_direction():
    good = parse_transfer(row())
    assert good['amount'] == Decimal('1')
    for change in ({'sender': 'bad'}, {'recipient': 'bad'},
                   {'contract': OTHER}, {'confirmed': False}, {'result': 'FAILED'},
                   {'net': 'erc20'}, {'quant': '1.0'}, {'quant': 1.0},
                   {'ts': '1700000000000'}):
        assert parse_transfer(row(**change)) is None
    assert parse_transfer({**row(), 'transaction_id': 'bad'}) is None
    assert match_transfer(good, **match_query())
    assert not match_transfer(good, **match_query(counterparty_addr=THIRD))
    assert not match_transfer(good, **match_query(after_ts=MARKER + 1))
    assert not match_transfer(good, **match_query(claimed_hashes={good['hash']}))
    outgoing = parse_transfer(row(sender=WALLET, recipient=OTHER))
    assert match_transfer(outgoing, **match_query(direction='outgoing', counterparty_addr=OTHER))
    assert not match_transfer(outgoing, **match_query(direction='outgoing', counterparty_addr=THIRD))
    assert not match_transfer(outgoing, **match_query())


def test_bad_rows_duplicate_and_claimed_hash():
    rows = [row(1), row(1), row(2, confirmed=False), row(3, recipient=THIRD),
            row(4, sender=THIRD), row(5, contract=OTHER), row(6, ts=MARKER - 1)]
    result, _ = scan({0: (200, {'token_transfers': rows, 'total': len(rows)}, None)},
                     claimed_hashes=[f'{1:064X}'])
    assert result == {'status': 'complete', 'candidates': [parse_transfer(row(4, sender=THIRD))],
                      'reason': None}
    conflict, _ = scan({0: (200, {'token_transfers': [row(1), row(1, quant='2000000')],
                              'total': 2}, None)})
    assert conflict['status'] == 'incomplete'
    assert conflict['reason'] == 'conflicting_hash'


def test_full_pages_until_older_marker_and_partial_page():
    first = [row(i + 1, quant='2000000', ts=MARKER + 100 - i) for i in range(50)]
    second = [row(51, ts=MARKER), row(52, ts=MARKER - 1)]
    pages = {0: (200, {'token_transfers': first}, None),
             50: (200, {'token_transfers': second}, None)}
    result, calls = scan(pages)
    assert result['status'] == 'complete' and len(result['candidates']) == 1
    assert len(calls) == 2
    partial, _ = scan({0: (200, {'token_transfers': [row()]}, None)})
    assert partial['status'] == 'incomplete' and partial['reason'] == 'truncated_page'
    assert len(partial['candidates']) == 1


@pytest.mark.parametrize('response', [(429, {}, 'rate_limit'), (503, {}, 'server_error'),
                                       (200, {}, None), (200, {'token_transfers': None}, None),
                                       (200, {'token_transfers': [row()] * 51}, None)])
def test_first_page_errors_unavailable_or_incomplete(response):
    result, _ = scan({0: response})
    assert result['status'] in ('unavailable', 'incomplete')
    assert result['status'] != 'complete'


def test_second_page_error_preserves_provisional_candidates():
    first = [row(1)] + [row(i, quant='2000000') for i in range(2, 51)]
    result, _ = scan({0: (200, {'token_transfers': first}, None),
                      50: (503, None, 'server_error')})
    assert result['status'] == 'incomplete'
    assert len(result['candidates']) == 1


def test_timeout_and_truncated_total_fail_closed():
    with patch.object(stand_egress, 'read_get', side_effect=TimeoutError):
        result = discover_transfers(**query())
    assert result == {'status': 'unavailable', 'candidates': [], 'reason': 'fetch_error'}
    truncated, _ = scan({0: (200, {'token_transfers': [row()], 'total': 2}, None)})
    assert truncated['status'] == 'incomplete'
    assert truncated['reason'] == 'truncated_page'


def test_malformed_second_page_and_unordered_rows():
    first = [row(i + 1, ts=MARKER + 100 - i) for i in range(50)]
    malformed, _ = scan({0: (200, {'token_transfers': first}, None),
                         50: (200, {'token_transfers': None}, None)})
    assert malformed['status'] == 'incomplete'
    unordered, _ = scan({0: (200, {'token_transfers': [row(1, ts=MARKER),
                                                        row(2, ts=MARKER + 1)],
                              'total': 2}, None)})
    assert unordered['status'] == 'incomplete'


def test_page_limit_does_not_claim_completeness():
    pages = {start: (200, {'token_transfers': [
        row(start + i + 1, quant='2000000', ts=MARKER + 2000 - start - i)
        for i in range(50)]}, None) for start in range(0, 1001, 50)}
    result, calls = scan(pages)
    assert result['status'] == 'incomplete' and result['reason'] == 'page_limit'
    assert calls[-1][1]['start'] == 1000
    assert len(calls) == 21


def test_rejects_invalid_query_before_read():
    with patch.object(stand_egress, 'read_get', side_effect=AssertionError('network')):
        for overrides in ({'network': 'erc20'}, {'wallet_addr': 'bad'},
                          {'direction': 'outgoing'}, {'after_ts': 1.5},
                          {'tolerance': Decimal('NaN')},
                          {'expected_amount': 1.0}, {'claimed_hashes': ['bad']}):
            with pytest.raises(ValueError):
                discover_transfers(**query(**overrides))
