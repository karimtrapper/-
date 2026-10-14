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
