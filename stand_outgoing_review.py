"""Проверка отправки с личного кошелька: снимок поручения и точная сумма."""
from datetime import datetime, timezone
from decimal import Decimal
import json

TOLERANCE = Decimal('0.005')


def timestamp(value):
    try:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return int(dt.replace(tzinfo=dt.tzinfo or timezone.utc).timestamp() * 1000)
    except (ValueError, TypeError):
        return None


def fingerprint(deal):
    """Подтверждение переплаты привязано к каждому выбранному переводу."""
    sends = (deal.get('transfer') or {}).get('sends') or []
    return json.dumps(sorted((s.get('hash') or s.get('ref'), str(s.get('verifiedAmount')))
                            for s in sends if s.get('status') == 'confirmed'), ensure_ascii=False)


def total(deal):
    return sum((Decimal(str(s.get('verifiedAmount') or 0))
                for s in (deal.get('transfer') or {}).get('sends') or []
                if s.get('status') == 'confirmed'), Decimal(0))


def complete(deal):
    review = deal.get('outgoingReview') or {}
    if any(s.get('status') not in ('confirmed', 'failed', 'mismatch')
           for s in (deal.get('transfer') or {}).get('sends') or []):
        return False
    required = Decimal(str((deal.get('transfer') or {}).get('amount') or 0))
    actual = total(deal)
    if required <= 0 or actual + TOLERANCE < required:
        return False
    accepted = review.get('accepted') == fingerprint(deal)
    if not accepted and review.get('scanStatus') != 'complete':
        return False
    return abs(actual-required) <= TOLERANCE or accepted


def claims(state, exclude_id=None, *, exclude_own_payout=False):
    """Хеш занят также приходом, возмещением и отправками других сделок."""
    hashes = set()
    for d in state.get('deals') or []:
        groups = [d.get('payinHashes') or []]
        if not exclude_own_payout or d.get('id') != exclude_id:
            groups.append((d.get('payout') or {}).get('hashes') or [])
        if d.get('id') != exclude_id:
            groups.append((d.get('transfer') or {}).get('sends') or [])
        groups.append([((d.get('payout') or {}).get('reimbursement') or {})])
        for group in groups:
            for tx in group:
                value = tx.get('hash') or tx.get('ref')
                if value:
                    hashes.add(str(value).lower())
    for c in state.get('convs') or []:
        hashes.update(str(t.get('hash')).lower() for t in c.get('txs') or [] if t.get('hash'))
    return hashes
