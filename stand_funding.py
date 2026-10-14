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


def sent_money(value, reviewing=False):
    # После «Отправил» это проверка факта, а не разрешение тратить больше заявки.
    # USDT в сети имеет 6 знаков; переплату отдельно принимает операционист.
    if not reviewing:
        return money(value, positive=True)
    try:
        amount = Decimal(str(value))
        return amount if amount.is_finite() and amount > 0 and amount == amount.quantize(Decimal('0.000001')) else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def _physical_send(deal, wallet_id):
    route = deal.get('postConv')
    if route in (None, 'keep'):
        return False
    if route == 'ipps':
        return (deal.get('transfer') or {}).get('back') is True
    if route == 'refund' and (deal.get('transfer') or {}).get('walletId') == wallet_id:
        return False
    return route in ('coins', 'client', 'refund', 'ipps_swift', 'ipps')


def incoming_shares(weights, amount):
    """Preserve the on-chain micro-USDT tail on the final source (same as s18w)."""
    total = sum(weights, Decimal(0))
    if not weights or total <= 0:
        return []
    used = Decimal(0)
    result = []
    for index, weight in enumerate(weights):
        part = amount - used if index == len(weights) - 1 else (amount * weight / total).quantize(CENT, rounding=ROUND_DOWN)
        result.append(part)
        used += part
    return result


def check_batch(state, conv, *, dispatch=False, independent_id=None):
    """Return a user-facing error, before any state or transfer mutation."""
    sources = conv.get('sources') or []
    deals = {d.get('id'): d for d in state.get('deals') or []}
    incomes = {str(i.get('id')): i for i in state.get('incomes') or []}
    ids = [s.get('dealId') for s in sources if s.get('dealId') is not None]
    if not ids or any(type(i) is not int for i in ids) or len(set(ids)) != len(ids):
        return 'В пачке дублируется или отсутствует источник'
    used_income = set()
    account_keys = set()
    for source in sources:
        if source.get('dealId') is None:
            key = str(source.get('incomeId'))
            income = incomes.get(key)
            rub = money(source.get('rub'), positive=True)
            if (not key.startswith('sber:') or not income or income.get('source') not in ('sber', 'registry')
                    or income.get('dealId') is not None or income.get('excluded')
                    or income.get('cnvId') != conv.get('id') or rub is None
                    or money(income.get('batchRub') or income.get('rub'), positive=True) != rub
                    or key in used_income):
                return 'Поступление реестра уже использовано или не совпадает с пачкой'
            account_keys.add(income.get('accountKey') or 'sber')
            used_income.add(key)
            continue
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
            manual_receipt = deal.get('manualBankReceipt') or {}
            manual_ok = (income is not None and income.get('source') == 'manual_confirmed'
                         and manual_receipt.get('status') == 'confirmed'
                         and manual_receipt.get('confirmedAt')
                         and manual_receipt.get('confirmedBy')
                         and income.get('manualReceiptId') == manual_receipt.get('id')
                         and part_rub == money(manual_receipt.get('actualAmount'), positive=True))
            if (key in used_income or not income or income.get('dealId') != deal['id']
                    or income.get('excluded') or part_rub is None or part_rub != income_rub
                    or not (income.get('source') == 'sber' or income.get('demo') is True or manual_ok)):
                return 'Приход RUB не подтверждён, повторно использован или не принадлежит сделке'
            if income.get('accountKey') or income.get('source') == 'sber':
                account_keys.add(income.get('accountKey') or 'sber')
            used_income.add(key)
            if source.get('bankNet') and income.get('source') == 'sber':
                net = money(income.get('rub'), positive=True)
                if net is None:
                    return 'Нет суммы зачисления Сбера'
                total += (part_rub * net / income_rub).quantize(CENT)
            else:
                total += part_rub
        if total != rub:
            return 'Сумма RUB источника не совпадает с подтверждёнными приходами'
    if len(account_keys) > 1:
        return 'Поступления с разных счетов нельзя отправить одной пачкой'
    if any('usdtFact' in source for source in sources):
        total_rub = sum(money(source['rub'], positive=True) for source in sources)
        last = len(sources) - 1
        allocated = [Decimal(0) for _ in sources]
        for tx in conv.get('txs') or []:
            amount = sent_money(tx.get('amount'), reviewing=True)
            if tx.get('status') != 'confirmed' or amount is None:
                return 'Распределять можно только подтверждённый приход USDT'
            for index, part in enumerate(incoming_shares([money(src['rub']) for src in sources], amount)):
                allocated[index] += part
        if any(sent_money(source.get('usdtFact'), reviewing=True) != allocated[index]
               for index, source in enumerate(sources)):
            return 'Распределение USDT не совпадает с подтверждённым приходом и долями RUB'
    if not dispatch:
        return None
    if independent_id is not None:
        deal = deals.get(independent_id) or {}
        prepay = deal.get('prepay') or {}
        transfer = deal.get('transfer') or {}
        limit = money(prepay.get('amount'), positive=True)
        reviewing = bool((deal.get('outgoingReview') or {}).get('requestedAt'))
        parts = [sent_money(s.get('amount'), reviewing) for s in transfer.get('sends') or []
                 if s.get('status') not in ('failed', 'mismatch')]
        if (independent_id not in ids or limit is None or money(transfer.get('amount')) != limit
                or any(p is None for p in parts) or (not reviewing and sum(parts) > limit)):
            return 'Недостаточно разрешённых средств для оплаты наперёд'
        return None
    incoming = Decimal(0)
    hashes = set()
    for tx in conv.get('txs') or []:
        amount = sent_money(tx.get('amount'), reviewing=True)
        key = (str(tx.get('hash') or '').lower(), str(tx.get('net') or '').lower().replace('-', ''))
        if tx.get('status') != 'confirmed' or amount is None or not key[0] or key in hashes:
            return 'Для отправки нужен уникальный подтверждённый приход USDT'
        hashes.add(key)
        incoming += amount
    # Оплата наперёд финансируется отдельным разрешённым источником.
    # RUB и разнос по пачке по-прежнему проверяются; USDT брокера не выдумываем.
    independent = all(deals[i].get('prepay') for i in ids)
    if incoming <= 0 and not independent:
        return 'Нет подтверждённого прихода USDT по пачке'
    outgoing = Decimal(0)
    for source in sources:
        if source.get('dealId') is None:
            continue
        deal = deals[source['dealId']]
        transfer = deal.get('transfer') or {}
        reviewing = bool((deal.get('outgoingReview') or {}).get('requestedAt'))
        sends = [s for s in transfer.get('sends') or []
                 if s.get('status') not in ('failed', 'mismatch')]
        if deal.get('prepay'):
            limit = money(deal['prepay'].get('amount'), positive=True)
            assigned = money(transfer.get('amount'), positive=True)
            parts = [sent_money(s.get('amount'), reviewing) for s in sends]
            if (limit is None or assigned != limit or any(p is None for p in parts)
                    or (not reviewing and sum(parts) > limit)):
                return 'Отправки IPPS должны укладываться в разрешённую сумму оплаты наперёд'
            continue
        if not _physical_send(deal, conv.get('walletId')):
            if sends:
                return 'По этому назначению перевод с кошелька не предусмотрен'
            continue
        amount = money(transfer.get('amount'), positive=True)
        if amount is None:
            return 'Сумма отправки USDT должна быть положительной с точностью до 0,01'
        outgoing += amount
        if sends:
            parts = [sent_money(s.get('amount'), reviewing) for s in sends]
            if any(p is None for p in parts) or (not reviewing and sum(parts) > amount):
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
    used_hashes = {}
    def remember_hash(tx):
        key = (str(tx.get('hash') or '').lower(), str(tx.get('net') or '').lower().replace('-', ''))
        previous = used_hashes.setdefault(key, [])
        if previous:
            rows = previous + [tx]
            # Only server-persisted shares can repeat. preserve_server_fields
            # runs before this guard; a browser cannot mint a ledgerUseId.
            ids = [t.get('ledgerUseId') for t in rows]
            amounts = [sent_money(t.get('amount'), reviewing=True) for t in rows]
            totals = [sent_money(t.get('verifiedAmount'), reviewing=True) for t in rows]
            if (not all(ids) or len(set(ids)) != len(ids) or any(a is None for a in amounts)
                    or any(t is None for t in totals) or len(set(totals)) != 1
                    or sum(amounts) > totals[0] + Decimal('0.005')
                    or len({t.get('to') for t in rows}) != 1):
                return 'Один приход USDT нельзя использовать в двух пачках без проверенных долей'
        previous.append(tx)
        return None
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
                issue = remember_hash(tx)
                if issue:
                    return issue
            continue
        before = old_convs.get(conv.get('id'))
        members = [d for d in state.get('deals') or [] if d.get('cnvId') == conv.get('id')]
        committed = any(not d.get('prepay') and d.get('step') in ('s23', 's24', 's25', 's26', 's27', 'done')
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
                if source.get('dealId') is None:
                    continue
                deal = next((d for d in members if d.get('id') == source.get('dealId')), {})
                for part in deal.get('payinParts') or []:
                    old_income = old_incomes.get(str(part.get('incId')))
                    if (not old_income or old_income.get('dealId') != deal.get('id')
                            or money(old_income.get('grossRub') or old_income.get('rub'), positive=True)
                            != money(part.get('amountRub'), positive=True)):
                        return 'Источник RUB должен быть зарегистрирован до создания пачки'
        for source in conv.get('sources') or []:
            deal_id = source.get('dealId')
            if deal_id is None:
                income_id = str(source.get('incomeId'))
                if income_id in used_incomes:
                    return 'Один приход RUB нельзя использовать в двух пачках'
                used_incomes.add(income_id)
                continue
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
            issue = remember_hash(tx)
            if issue:
                return issue
    return None
