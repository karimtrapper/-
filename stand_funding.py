"""Money admission and wallet coverage for stand RUB conversion batches."""

from decimal import Decimal, InvalidOperation, ROUND_DOWN
import re


CENT = Decimal('0.01')


def money(value, *, positive=False):
    if isinstance(value, bool) or value is None:
        return None
    raw = str(value).replace(' ', '').replace('\u00a0', '').replace(',', '.')
    if not re.fullmatch(r'-?\d+(?:\.\d{1,2})?', raw):
        return None
    try:
        amount = Decimal(raw)
    except (InvalidOperation, ValueError):
        return None
    if not amount.is_finite() or amount < 0 or (positive and amount == 0):
        return None
    try:
        if amount != amount.quantize(CENT):
            return None
    except InvalidOperation:
        return None
    return amount


def _physical_send(deal, wallet_id):
    route = deal.get('postConv')
    if route in (None, 'keep'):
        return False
    if route == 'ipps':
        return (deal.get('transfer') or {}).get('back') is True
    if route == 'refund' and (deal.get('transfer') or {}).get('walletId') == wallet_id:
        return False
    return route in ('coins', 'client', 'refund', 'ipps_swift', 'ipps')


def check_batch(state, conv, *, dispatch=False):
    """Return a user-facing error, before any state or transfer mutation."""
    sources = conv.get('sources') or []
    deals = {d.get('id'): d for d in state.get('deals') or []}
    incomes = {str(i.get('id')): i for i in state.get('incomes') or []}
    ids = [s.get('dealId') for s in sources]
    if not ids or any(type(i) is not int for i in ids) or len(set(ids)) != len(ids):
        return 'В пачке дублируется или отсутствует источник'
    used_income = set()
    for source in sources:
        deal = deals.get(source['dealId'])
        rub = money(source.get('rub'), positive=True)
        if not deal or deal.get('cnvId') != conv.get('id') or rub is None:
            return 'Для RUB пачки нужен положительный подтверждённый рублёвый приход по каждой сделке'
        parts = deal.get('payinParts') or []
        if not parts:
            return 'Для RUB пачки нужен подтверждённый рублёвый приход по каждой сделке'
        total = Decimal(0)
        for part in parts:
            key = str(part.get('incId'))
            income = incomes.get(key)
            part_rub = money(part.get('amountRub'), positive=True)
            income_rub = money((income or {}).get('grossRub') or (income or {}).get('rub'), positive=True)
            if (key in used_income or not income or income.get('dealId') != deal['id']
                    or income.get('excluded') or part_rub is None or part_rub != income_rub
                    or not (income.get('source') == 'sber' or income.get('demo') is True)):
                return 'Приход RUB не подтверждён, повторно использован или не принадлежит сделке'
            used_income.add(key)
            total += part_rub
        if total != rub:
            return 'Сумма RUB источника не совпадает с подтверждёнными приходами'
    if any('usdtFact' in source for source in sources):
        total_rub = sum(money(source['rub'], positive=True) for source in sources)
        last = len(sources) - 1
        allocated = [Decimal(0) for _ in sources]
        for tx in conv.get('txs') or []:
            amount = money(tx.get('amount'), positive=True)
            if tx.get('status') != 'confirmed' or amount is None:
                return 'Распределять можно только подтверждённый приход USDT'
            used = Decimal(0)
            for index, source in enumerate(sources):
                part = (amount - used if index == last else
                        (amount * money(source['rub']) / total_rub).quantize(CENT, rounding=ROUND_DOWN))
                allocated[index] += part
                used += part
        if any(money(source.get('usdtFact')) != allocated[index]
               for index, source in enumerate(sources)):
            return 'Распределение USDT не совпадает с подтверждённым приходом и долями RUB'
    if not dispatch:
        return None
    incoming = Decimal(0)
    hashes = set()
    for tx in conv.get('txs') or []:
        amount = money(tx.get('amount'), positive=True)
        key = (str(tx.get('hash') or '').lower(), str(tx.get('net') or '').lower().replace('-', ''))
        if tx.get('status') != 'confirmed' or amount is None or not key[0] or key in hashes:
            return 'Для отправки нужен уникальный подтверждённый приход USDT'
        hashes.add(key)
        incoming += amount
    if incoming <= 0:
        return 'Нет подтверждённого прихода USDT по пачке'
    outgoing = Decimal(0)
    for source in sources:
        deal = deals[source['dealId']]
        transfer = deal.get('transfer') or {}
        sends = [s for s in transfer.get('sends') or []
                 if s.get('status') not in ('failed', 'mismatch')]
        if not _physical_send(deal, conv.get('walletId')):
            if sends:
                return 'По этому назначению перевод с кошелька не предусмотрен'
            continue
        amount = money(transfer.get('amount'), positive=True)
        if amount is None:
            return 'Сумма отправки USDT должна быть положительной с точностью до 0,01'
        outgoing += amount
        if sends:
            parts = [money(s.get('amount'), positive=True) for s in sends]
            if any(p is None for p in parts) or sum(parts) > amount:
                return 'Зарегистрированные переводы превышают назначение или имеют неверную сумму'
    if outgoing > incoming:
        return f'По задачам {outgoing} USDT, подтверждено {incoming} USDT — не хватает {outgoing - incoming} USDT'
    return None


def check_state(previous, state):
    """Check new funding sources and every committed batch after each PUT."""
    old_convs = {c.get('id'): c for c in previous.get('convs') or []}
    old_deals = {d.get('id'): d for d in previous.get('deals') or []}
    old_incomes = {str(i.get('id')): i for i in previous.get('incomes') or []}
    used_incomes = set()
    used_deals = set()
    used_hashes = set()
    for conv in state.get('convs') or []:
        # The conversions register also accepts unassigned bank receipts.
        # They are not a deal funding batch until a deal is explicitly linked.
        if (not any(source.get('dealId') is not None for source in conv.get('sources') or [])
                and not any(d.get('cnvId') == conv.get('id') for d in state.get('deals') or [])):
            for source in conv.get('sources') or []:
                key = str(source.get('incomeId'))
                if key != 'None':
                    if key in used_incomes:
                        return 'Один приход RUB нельзя использовать в двух пачках'
                    used_incomes.add(key)
            for tx in conv.get('txs') or []:
                key = (str(tx.get('hash') or '').lower(),
                       str(tx.get('net') or '').lower().replace('-', ''))
                if key in used_hashes:
                    return 'Один приход USDT нельзя использовать в двух пачках'
                used_hashes.add(key)
            continue
        before = old_convs.get(conv.get('id'))
        members = [d for d in state.get('deals') or [] if d.get('cnvId') == conv.get('id')]
        committed = any(d.get('step') in ('s23', 's24', 's25', 's26', 's27', 'done')
                        and d.get('postConv') in ('coins', 'ipps_swift') for d in members)
        newly_committed = any(d.get('step') in ('s23', 's24', 's25', 's26', 's27', 'done')
                              and (old_deals.get(d.get('id')) or {}).get('step') == 's22'
                              for d in members)
        source_changed = before is None or before.get('sources') != conv.get('sources')
        def assignment(deal):
            transfer = deal.get('transfer') or {}
            return (deal.get('postConv'), transfer.get('amount'), transfer.get('back'),
                    tuple((s.get('amount'), s.get('ref'), s.get('hash'), s.get('net'))
                          for s in transfer.get('sends') or []))
        money_changed = any(assignment(old_deals.get(d.get('id')) or {}) != assignment(d)
                            for d in members)
        if source_changed or newly_committed or (committed and money_changed):
            issue = check_batch(state, conv, dispatch=committed)
            if issue:
                return issue
            for source in conv.get('sources') or []:
                deal = next((d for d in members if d.get('id') == source.get('dealId')), {})
                for part in deal.get('payinParts') or []:
                    old_income = old_incomes.get(str(part.get('incId')))
                    if (not old_income or old_income.get('dealId') != deal.get('id')
                            or money(old_income.get('grossRub') or old_income.get('rub'), positive=True)
                            != money(part.get('amountRub'), positive=True)):
                        return 'Источник RUB должен быть зарегистрирован до создания пачки'
        for source in conv.get('sources') or []:
            deal_id = source.get('dealId')
            if deal_id in used_deals:
                return 'Одна сделка не может финансировать две пачки'
            used_deals.add(deal_id)
            for part in (next((d for d in members if d.get('id') == deal_id), {})
                         .get('payinParts') or []):
                income_id = str(part.get('incId'))
                if income_id in used_incomes:
                    return 'Один приход RUB нельзя использовать в двух пачках'
                used_incomes.add(income_id)
        for tx in conv.get('txs') or []:
            key = (str(tx.get('hash') or '').lower(),
                   str(tx.get('net') or '').lower().replace('-', ''))
            if key in used_hashes:
                return 'Один приход USDT нельзя использовать в двух пачках'
            used_hashes.add(key)
    return None
