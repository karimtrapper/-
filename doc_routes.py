"""Маршрут документов: валюты и реквизиты одной операции, без банковских дефолтов."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

INVERSE_RATE = 'payin_per_transfer'  # исторический формат, в том числе без маркера
DIRECT_RATE = 'transfer_per_payin'

PAIRS = {
    'RUB_THB': ('RUB', 'THB'), 'USDT_THB': ('USDT', 'THB'),
    'RUB_USDT': ('RUB', 'USDT'), 'RUB_USD': ('RUB', 'USD'),
    'USDT_USD': ('USDT', 'USD'), 'USD_THB': ('USD', 'THB'),
}
METHODS = {'bank': 'По реквизитам / Bank transfer', 'sbp': 'СБП / SBP',
           'usdt': 'Перевод USDT / USDT transfer', 'cash': 'Наличные / Cash'}
ROUTE_FIELDS = ('payin_recipient', 'payin_recipient_role', 'payin_details',
                'payin_network', 'payin_wallet', 'cash_network', 'cash_location',
                'cash_contact', 'cash_datetime', 'payout_network', 'payout_wallet')


def pair_for(money, deal_type='leasehold'):
    key = money.get('pair')
    if not key:
        key = f"{money.get('payin_currency') or 'RUB'}_{'USD' if deal_type == 'freehold' else 'THB'}"
    if key not in PAIRS:
        raise ValueError('Выберите валютную пару из списка')
    return key, *PAIRS[key]


def normalize(money, deal_type='leasehold'):
    m = dict(money)
    key, incoming, outgoing = pair_for(m, deal_type)
    basis = m.get('rate_basis', INVERSE_RATE)
    if basis not in (INVERSE_RATE, DIRECT_RATE):
        raise ValueError('Неизвестное направление курса')
    if basis == DIRECT_RATE and key != 'USDT_THB':
        raise ValueError('Курс за 1 USDT поддерживается только для USDT → THB')
    if m.get('payin_currency') and m['payin_currency'] != incoming:
        raise ValueError('Валюта оплаты не совпадает с выбранной парой')
    if m.get('transfer_currency') and m['transfer_currency'] != outgoing:
        raise ValueError('Валюта получателя не совпадает с выбранной парой')
    method = m.get('payin_method') or ('usdt' if incoming == 'USDT' else 'bank')
    if method not in METHODS:
        raise ValueError('Выберите способ оплаты: по реквизитам, СБП, USDT или наличные')
    if (incoming == 'USDT') != (method == 'usdt') or (method == 'sbp' and incoming != 'RUB'):
        raise ValueError('Способ оплаты не подходит к валюте клиента')
    m.update(pair=key, payin_currency=incoming, transfer_currency=outgoing,
             payin_method=method, rate_basis=basis)
    if method != 'bank':
        m['payment_reference'] = ''
    return m


def decimal_amount(value, currency):
    raw = str(value or '').replace('\u00a0', '').replace(' ', '').replace(',', '.')
    for suffix in (currency, 'руб.' if currency == 'RUB' else '฿' if currency == 'THB' else currency):
        raw = raw.replace(suffix, '')
    try:
        result = Decimal(raw)
    except InvalidOperation:
        raise ValueError(f'Введите числовую сумму в {currency}') from None
    if not result.is_finite() or result <= 0:
        raise ValueError(f'Сумма в {currency} должна быть положительной')
    return result


def amount(value, currency):
    if value in (None, ''):
        return ''
    number = decimal_amount(value, currency)
    places = max(0, -number.normalize().as_tuple().exponent)
    limit = 6 if currency == 'USDT' else 2
    if places > limit:
        raise ValueError(f'В сумме {currency} допустимо не более {limit} знаков после запятой')
    return f'{currency} {number:,.{max(2, places)}f}'.replace(',', ' ')


def details(m):
    if m['payin_method'] == 'usdt':
        return f"Сеть / Network: {m.get('payin_network', '')}\nUSDT: {m.get('payin_wallet', '')}"
    if m['payin_method'] == 'cash':
        return (f"Сеть / Cash collection network: {m.get('cash_network', '')}\n"
                f"Место / Location: {m.get('cash_location', '')}\n"
                f"Контакт / Contact: {m.get('cash_contact', '')}\n"
                f"Дата и время / Date and time: {m.get('cash_datetime', '')}")
    return m.get('payin_details', '')


def rate_text(m, deal_type='leasehold'):
    """Клиентская котировка; старые значения не переинтерпретируем и не пишем в БД."""
    key, incoming, outgoing = pair_for(m, deal_type)
    raw = m.get('rate')
    if key != 'USDT_THB':
        return f"{raw or ''} {incoming}/{outgoing}"
    if not raw:
        return ''
    rate = decimal_amount(raw, 'курс')
    if m.get('rate_basis', INVERSE_RATE) == INVERSE_RATE:
        # Старый курс из сумм округлялся до 6 знаков. Восстанавливаем прямой
        # из этих сумм; для точной котировки с округлением payout обращаем rate.
        a = decimal_amount(m.get('total_payin'), incoming)
        b = decimal_amount(m.get('transfer_amount'), outgoing)
        # На половине шага старый JS toFixed мог округлить вниз. Принимаем обе
        # границы для шестизначного значения; точную котировку не заменяем.
        rounded_from_amounts = (rate == rate.quantize(Decimal('0.000001'))
                                and abs(rate - a / b) <= Decimal('0.0000005000000001'))
        rate = b / a if rounded_from_amounts else 1 / rate
        rate = rate.quantize(Decimal('0.000001'), rounding=ROUND_HALF_UP)
    return f'1 USDT = {rate:f} THB'


def validate(m, deal_type):
    """Проверка перед выдачей; низкоуровневые builders пригодны и для черновиков."""
    normalize(m, deal_type)
    if deal_type == 'freehold' and m['transfer_currency'] != 'USD':
        raise ValueError('Для фрихолда выберите перевод получателю в USD')
    if deal_type in ('leasehold', 'rental') and m['transfer_currency'] != 'THB':
        raise ValueError('Для лизхолда/аренды выберите THB; для другого перевода — тип «Перевод / обмен»')
    required = ['payin_recipient', 'payin_recipient_role', 'rate_valid_until']
    required += {'bank': ['payin_details'], 'sbp': ['payin_details'],
                 'usdt': ['payin_network', 'payin_wallet'],
                 'cash': ['cash_network', 'cash_location', 'cash_contact', 'cash_datetime']}[m['payin_method']]
    if m['transfer_currency'] == 'USDT':
        required += ['payout_network', 'payout_wallet']
    missing = [k for k in required if not str(m.get(k) or '').strip()]
    if missing:
        return missing
    incoming = decimal_amount(m.get('total_payin'), m['payin_currency'])
    outgoing = decimal_amount(m.get('transfer_amount') or m.get('usd_equivalent'), m['transfer_currency'])
    amount(m.get('total_payin'), m['payin_currency'])
    amount(m.get('transfer_amount') or m.get('usd_equivalent'), m['transfer_currency'])
    if deal_type == 'freehold' and m.get('usd_equivalent'):
        if decimal_amount(m['usd_equivalent'], 'USD') != outgoing:
            raise ValueError('Подтверждённый USD-эквивалент должен совпадать с суммой получателю')
    if m.get('rate'):
        rate = decimal_amount(m['rate'], 'курс')
        # Форма может считать курс из сумм ИЛИ сумму получателя из котировки.
        # Во втором случае сумма округляется до 2/6 знаков, а сам курс не меняется.
        quantum = Decimal('0.000001') if m['transfer_currency'] == 'USDT' else Decimal('0.01')
        direct = m.get('rate_basis', INVERSE_RATE) == DIRECT_RATE
        expected_rate = outgoing / incoming if direct else incoming / outgoing
        expected_payout = incoming * rate if direct else incoming / rate
        rate_matches = abs(rate - expected_rate) <= Decimal('0.000001')
        rounded_payout_matches = abs(outgoing - expected_payout) <= quantum / 2
        if not rate_matches and not rounded_payout_matches:
            raise ValueError('Курс не соответствует суммам. Пересчитайте курс из суммы клиента и суммы получателя')
    return []
