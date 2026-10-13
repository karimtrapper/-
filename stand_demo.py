"""DEMO разрешён только явным флагом изолированного автотестового окружения."""
import json
import os
import time
from datetime import datetime


def enabled():
    return os.environ.get('STAND_ALLOW_DEMO') == '1'


def markers(value):
    """Денежные признаки DEMO, включая старые хеши без отдельного флага."""
    found = set()
    if isinstance(value, dict):
        if value.get('demo') or value.get('demoOutcome'):
            # Привязка существующего прихода к пачке не создаёт новый перевод.
            identity = {k: value[k] for k in ('id', 'incId', 'hash', 'ref', 'amount',
                'amountRub', 'rub', 'usdt', 'verifiedAmount', 'from', 'to', 'demo', 'demoOutcome') if k in value}
            found.add(json.dumps(identity, sort_keys=True, ensure_ascii=False))
        for item in value.values():
            found.update(markers(item))
    elif isinstance(value, list):
        for item in value:
            found.update(markers(item))
    elif isinstance(value, str) and value.startswith('demo:'):
        found.add(value)
    return found


def money(deal):
    return {k: deal.get(k) for k in ('payinHashes', 'payinParts', 'payinExtra',
        'pay', 'payout', 'mfPayout', 'transfer', 'reimbursement')}


def evidence(state, deal, *, include_logs=True):
    if markers(money(deal)):
        return True
    inc_ids = {p.get('incId') for p in deal.get('payinParts') or [] if isinstance(p, dict)}
    for income in state.get('incomes') or []:
        if (income.get('dealId') == deal.get('id') or income.get('id') in inc_ids) and markers(income):
            return True
    for conv in state.get('convs') or []:
        if (conv.get('id') == deal.get('cnvId') or any(
                p.get('dealId') == deal.get('id') for p in conv.get('sources') or [])) and markers(conv.get('txs')):
            return True
    # Старые записи журнала тоже не даём молча превратить в реальные деньги.
    return include_logs and any('demo' in str(entry).lower() or 'демо' in str(entry).lower()
               for entry in deal.get('log') or [])


def repair(state):
    """Снять ошибочный флаг только при полном отсутствии DEMO-истории."""
    repaired, warnings = [], []
    if enabled():
        return repaired, warnings
    for deal in state.get('deals') or []:
        if not deal.get('demoTransfers'):
            continue
        if evidence(state, deal):
            warnings.append(deal['id'])
            continue
        deal['demoTransfers'] = False
        deal.setdefault('log', []).append({'ts': datetime.now().strftime('%d.%m, %H:%M'),
            'at': int(time.time()*1000), 'role': 'system', 'text': 'Снят ошибочный тестовый флаг: тестовых приходов и переводов в истории нет'})
        repaired.append(deal['id'])
    return repaired, warnings


def guard(previous, incoming):
    if enabled():
        return None
    old = {d.get('id'): d for d in previous.get('deals') or []}
    for deal in incoming.get('deals') or []:
        before = old.get(deal.get('id'), {})
        if deal.get('demoTransfers') and not before.get('demoTransfers'):
            return 'DEMO отключён в этом окружении'
        if evidence(incoming, deal, include_logs=False) and not (before and evidence(previous, before, include_logs=False)):
            return 'Новый DEMO-приход запрещён в этом окружении'
        if markers(money(deal)) - markers(money(before)):
            return 'DEMO-приходы и переводы отключены в этом окружении'
        if before.get('demoTransfers') and evidence(previous, before):
            if (not deal.get('demoTransfers') or deal.get('step') != before.get('step')
                    or markers(money(before)) - markers(money(deal))):
                return 'В истории есть DEMO-приходы/переводы: требуется разбор, автоматическое продолжение запрещено'
    for key in ('convs', 'incomes'):
        if markers(incoming.get(key)) - markers(previous.get(key)):
            return 'DEMO-приходы и переводы отключены в этом окружении'
    return None
