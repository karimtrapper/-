"""Параллельная оплата фрихолда: выбранный источник не является приходом брокера."""

from decimal import Decimal, ROUND_HALF_UP


def amount(deal):
    """Та же сумма IPPS, что freeholdSend: инвойс + округлённая комиссия."""
    invoice = Decimal(str(deal.get('invoiceUsd') or 0))
    tariff = {'bank': Decimal('.008'), 'soft': Decimal('.015')}[deal.get('ippsTariff') or 'bank']
    return float(invoice + (invoice * tariff + 50).quantize(Decimal('.01'), rounding=ROUND_HALF_UP))


def broker_step(deal):
    return (deal.get('prepay') or {}).get('brokerStep') or deal.get('step')


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
    if prepay['source'] == 'founder' and not (deal.get('payout') or {}).get('reimbursement'):
        return 'Сначала возместите фаундеру отправленную в IPPS сумму'
    return None
