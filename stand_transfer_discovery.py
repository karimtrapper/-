"""Read-only TRC-20 USDT discovery for future server-side callers.

`complete` means the requested time window was fully scanned. Candidates from
`incomplete` are provisional and must never be used for automatic attachment.
This module does not decide ownership or mutate claims; a caller must recheck
global uniqueness while holding its own lock.
"""

from decimal import Decimal
import hashlib
import re


USDT_TRC20 = 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t'
PAGE_SIZE = 50
MAX_START = 1000
_B58 = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
_HASH = re.compile(r'[0-9a-fA-F]{64}\Z')
_INTEGER = re.compile(r'[0-9]+\Z')


def _address(value):
    if not isinstance(value, str) or len(value) != 34 or value[0] != 'T':
        return False
    try:
        number = 0
        for char in value:
            number = number * 58 + _B58.index(char)
        raw = number.to_bytes(25, 'big')
    except (ValueError, OverflowError):
        return False
    return (raw[0] == 0x41 and
            hashlib.sha256(hashlib.sha256(raw[:-4]).digest()).digest()[:4] == raw[-4:])


def _nonnegative_decimal(value):
    if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
        raise ValueError('amount and tolerance must be finite nonnegative Decimals')
    return value


def _timestamp(value):
    return type(value) is int and value >= 0


def _hash(value):
    return value.lower() if isinstance(value, str) and _HASH.fullmatch(value) else None


def parse_transfer(row):
    """Pure, strict normalization of one TronScan transfer; invalid rows are ignored."""
    if not isinstance(row, dict):
        return None
    tx_hash = _hash(row.get('transaction_id'))
    sender, recipient = row.get('from_address'), row.get('to_address')
    quant = row.get('quant')
    if (not tx_hash or not _address(sender) or not _address(recipient)
            or row.get('contract_address') != USDT_TRC20
            or row.get('net', 'trc20') != 'trc20'
            or row.get('event_type') != 'Transfer'
            or row.get('contractRet') != 'SUCCESS'
            or type(row.get('status')) is not int or row['status'] != 0
            or row.get('confirmed') is not True
            or row.get('finalResult') != 'SUCCESS'
            or not _timestamp(row.get('block_ts'))
            or not isinstance(quant, str) or not _INTEGER.fullmatch(quant)):
        return None
    return {'hash': tx_hash, 'network': 'trc20', 'from': sender, 'to': recipient,
            'amount': Decimal(quant) / Decimal(1_000_000),
            'timestamp_ms': row['block_ts']}


def match_transfer(transfer, *, direction, wallet_addr, counterparty_addr,
                   expected_amount, tolerance, after_ts, claimed_hashes=frozenset()):
    """Pure predicate; caller supplies only trusted server-side query values."""
    if transfer is None or transfer['timestamp_ms'] < after_ts:
        return False
    if transfer['hash'] in claimed_hashes:
        return False
    if not (expected_amount - tolerance <= transfer['amount'] <= expected_amount + tolerance):
        return False
    if direction == 'incoming':
        return transfer['to'] == wallet_addr and (
            counterparty_addr is None or transfer['from'] == counterparty_addr)
    return transfer['from'] == wallet_addr and transfer['to'] == counterparty_addr


def _result(status, candidates, reason=None):
    return {'status': status, 'candidates': candidates, 'reason': reason}


def discover_transfers(*, direction, wallet_addr, expected_amount, tolerance,
                       after_ts, network='trc20', counterparty_addr=None,
                       claimed_hashes=()):
    """Scan newest-first pages using only the fixed T9 read channel.

    `after_ts` is an inclusive Unix timestamp in milliseconds. Incomplete
    results retain provisional candidates so a UI can explain ambiguity, but
    no caller may attach them until a later complete scan and locked recheck.
    """
    if (network != 'trc20' or direction not in ('incoming', 'outgoing')
            or not _address(wallet_addr)
            or (counterparty_addr is not None and not _address(counterparty_addr))
            or (direction == 'outgoing' and counterparty_addr is None)
            or not _timestamp(after_ts)):
        raise ValueError('invalid discovery query')
    _nonnegative_decimal(expected_amount)
    _nonnegative_decimal(tolerance)
    if not isinstance(claimed_hashes, (set, frozenset, list, tuple)):
        raise ValueError('claimed_hashes must be a collection of hashes')
    claimed = set()
    for item in claimed_hashes:
        normalized = _hash(item)
        if normalized is None:
            raise ValueError('invalid claimed hash')
        claimed.add(normalized)

    # Lazy import keeps parsing/matching independent of the network adapter.
    import stand_egress

    candidates, seen = [], {}
    previous_ts, known_total = None, None
    start = 0
    while start <= MAX_START:
        params = {'relatedAddress': wallet_addr, 'contract_address': USDT_TRC20,
                  'limit': PAGE_SIZE, 'start': start}
        try:
            status, payload, error = stand_egress.read_get('tron_trc20_transfers', params)
        except Exception:
            return _result('incomplete' if start else 'unavailable', candidates, 'fetch_error')
        if error or status != 200:
            return _result('incomplete' if start else 'unavailable', candidates, 'fetch_error')
        if not isinstance(payload, dict) or not isinstance(payload.get('token_transfers'), list):
            return _result('incomplete' if start else 'unavailable', candidates, 'malformed_page')
        rows = payload['token_transfers']
        total = payload.get('total')
        if (len(rows) > PAGE_SIZE or (total is not None and
            (type(total) is not int or total < 0 or (known_total is not None and total != known_total)))):
            return _result('incomplete', candidates, 'malformed_page')
        if total is not None:
            known_total = total
        if known_total is not None and start + len(rows) > known_total:
            return _result('incomplete', candidates, 'malformed_page')
        reached_marker = False
        for row in rows:
            if not isinstance(row, dict) or not _timestamp(row.get('block_ts')):
                return _result('incomplete', candidates, 'malformed_page')
            ts = row['block_ts']
            if previous_ts is not None and ts > previous_ts:
                return _result('incomplete', candidates, 'unordered_page')
            previous_ts = ts
            if ts < after_ts:
                reached_marker = True
                continue
            transfer = parse_transfer(row)
            if transfer is None:
                continue
            old = seen.get(transfer['hash'])
            if old is not None:
                if old != transfer:
                    return _result('incomplete', candidates, 'conflicting_hash')
                continue
            seen[transfer['hash']] = transfer
            if match_transfer(transfer, direction=direction, wallet_addr=wallet_addr,
                              counterparty_addr=counterparty_addr,
                              expected_amount=expected_amount, tolerance=tolerance,
                              after_ts=after_ts, claimed_hashes=claimed):
                candidates.append(transfer)
        if reached_marker or (known_total is not None and start + len(rows) == known_total):
            return _result('complete', candidates)
        # A short/empty page without an authoritative total may be truncated.
        if len(rows) < PAGE_SIZE:
            return _result('incomplete', candidates, 'truncated_page')
        start += PAGE_SIZE
    return _result('incomplete', candidates, 'page_limit')
