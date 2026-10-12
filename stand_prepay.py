"""Параллельная оплата фрихолда: выбранный источник не является приходом брокера."""

from decimal import Decimal, ROUND_HALF_UP


def amount(deal):
    """Та же сумма IPPS, что freeholdSend: инвойс + округлённая комиссия."""
    invoice = Decimal(str(deal.get('invoiceUsd') or 0))
    tariff = {'bank': Decimal('.008'), 'soft': Decimal('.015')}[deal.get('ippsTariff') or 'bank']
    fee = (invoice * tariff + 50).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
    return float((invoice + fee).quantize(Decimal('.01'), rounding=ROUND_HALF_UP))


def broker_wallet(state, deal):
    conv = next((c for c in state.get('convs') or [] if c.get('id') == deal.get('cnvId')), {})
    return next((w for w in state.get('wallets') or [] if w.get('id') == conv.get('walletId')), {})


def same_wallet(state, deal):
    """Сравниваем адреса: у старых сделок один кошелёк может иметь разные ID."""
    incoming = broker_wallet(state, deal).get('addr')
    return bool(incoming and incoming == wallet(state, deal).get('addr'))


def wallet_id(state, deal):
    """Кошелёк отправки отделён от кошелька получения USDT брокера."""
    if deal.get('prepay'):
        return deal['prepay']['wallet']['id']
    conv = next((c for c in state.get('convs') or [] if c.get('id') == deal.get('cnvId')), {})
    return conv.get('walletId') or deal.get('walletId')


def wallet(state, deal):
    if deal.get('prepay'):
        return deal['prepay']['wallet']
    return next((w for w in state.get('wallets') or [] if w.get('id') == wallet_id(state, deal)), {})


def received(state, deal):
    conv = next((c for c in state.get('convs') or [] if c.get('id') == deal.get('cnvId')), {})
    txs = conv.get('txs') or []
    return bool(txs) and all(t.get('status') == 'confirmed' for t in txs)


def close_problem(state, deal):
    prepay = deal.get('prepay')
    if not prepay:
        return None
    if prepay.get('brokerStep') != 'done' or not received(state, deal):
        return 'Ждём USDT брокера и завершения конвертации'
    if not (deal.get('payout') or {}).get('reimbursement'):
        return 'Сначала возместите отправленную в IPPS сумму на кошелёк оплаты'
    return None
