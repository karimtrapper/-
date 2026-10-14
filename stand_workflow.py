"""Board workflow rules shared by the state and action endpoints."""
EXCHANGE_PAIRS = {
    'RUB → THB': ('rub', 'thb', ('rub', 'thb')),
    'THB → RUB': ('thb', 'rub', ('thb', 'rub')),
    'RUB → USDT': ('rub', 'usdt', ('rub',)),
    'THB → USDT': ('thb', 'usdt', ('thb',)),
    'USDT → THB': ('usdt', 'thb', ('thb',)),
}


def quote_dirs(deal):
    if deal.get('type') == 'Обмен валюты':
        default = 'USDT → THB' if deal.get('payType') == 'Крипта' else 'RUB → THB'
        return EXCHANGE_PAIRS.get(deal.get('pair') or default, (None, None, ()))[2]
    crypto = deal.get('payType') == 'Крипта' or deal.get('curBase') == 'usdt'
    return ('thb',) if crypto else ('rub',) if deal.get('kind') == 'Фрихолд' else ('rub', 'thb')
from copy import deepcopy
from decimal import Decimal, InvalidOperation

# Forward handoffs plus the explicit return buttons in STEPS/ret().
EDGES = {
    's4': {'s5', 's6'}, 's5': {'s4', 's6'}, 's6': {'s5', 's8'},
    's8': {'s5', 's11'}, 's11': {'s8', 's11b', 's12'},
    's11b': {'s11', 's12'}, 's12': {'s14'},
    's14': {'s14m', 's15', 's18', 's22'},
    's14m': {'s14', 's15', 's18', 's22'},
    's15': {'s18', 's22', 's26'}, 's18': {'s18w'}, 's18w': {'s22'},
    's22': {'s23', 's26'}, 's23': {'s24', 's25', 's26', 's27'},
    's24': {'s23', 's25', 's26', 's27'}, 's25': {'s26'},
    's26': {'s15', 's27'}, 's27': {'done'},
    'ready': {'pack'}, 'pack': {'s22'}, 'manual': {'done'}, 'done': set(),
}


def positive(value):
    try:
        number = Decimal(str(value).replace(',', '.'))
        return number.is_finite() and number > 0
    except (InvalidOperation, ValueError, TypeError):
        return False


def journal_problem(previous, submitted):
    """Past entries are immutable, including legacy entries without an at key."""
    old = {d['id']: d for d in previous.get('deals', [])}
    for deal in submitted.get('deals', []):
        stored = old.get(deal.get('id'), {}).get('log') or []
        incoming = deal.get('log') or []
        def canonical(entry):
            if isinstance(entry, str):
                return entry
            result = dict(entry)
            if result.get('at') is None:
                result.pop('at', None)
            return result
        if (not isinstance(incoming, list) or len(incoming) < len(stored)
                or any(not isinstance(x, (dict, str)) for x in incoming)
                or [canonical(x) for x in incoming[:len(stored)]] != [canonical(x) for x in stored]):
            return 'Прошлые записи журнала нельзя удалять или менять'
    return None


def accept_journal(previous, submitted, actor, author, stamp):
    """Preserve history byte-for-byte; append human input with server attribution."""
    old = {d['id']: d for d in previous.get('deals', [])}
    for deal in submitted.get('deals', []):
        stored = old.get(deal.get('id'), {}).get('log') or []
        appended = (deal.get('log') or [])[len(stored):]
        deal['log'] = deepcopy(stored)
        for entry in appended:
            text = str(entry if isinstance(entry, str) else entry.get('text') or '').strip()
            if text:
                deal['log'].append({'at': stamp, 'role': actor, 'author': author,
                                    'kind': 'comment', 'text': f'Комментарий · {author}: {text}'})


def accept_notes(previous, submitted, actor):
    """Only read acknowledgements may originate in a board snapshot."""
    proposed = {str(n.get('id')): n for n in submitted.get('notes') or [] if isinstance(n, dict)}
    notes = deepcopy(previous.get('notes') or [])
    for note in notes:
        incoming = proposed.get(str(note.get('id')), {})
        if (actor in ('admin', note.get('role')) and incoming.get('read') is True):
            note['read'] = True
    submitted['notes'] = notes
