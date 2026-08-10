"""Клиент Bitrix24 для закрытия сделок из CRM — перенос из бота DealCloser.

Бот выключается (решение Карима 10.08.2026): закрытие переезжает в CalcCRM,
чтобы конверсия считалась в одном месте, а разбор чата видел оператор на экране.
Код тот же, что крутился в проде с апреля, переписан с aiohttp на requests —
Flask синхронный, тянуть асинхронную сессию в воркер незачем.

Портал один — облачный Grusha (`b24-1tgrla.bitrix24.com`), вебхук целиком
в env `BITRIX_WEBHOOK`. Дефолта нет намеренно: раньше он вёл на реверс-прокси
старого портала, и при незаданной переменной CRM молча показывала чужую
воронку (сделки МаксФина с ООО/ЧОО вместо клиентов Grusha).
"""
import os

import requests

BITRIX_WEBHOOK = os.environ.get('BITRIX_WEBHOOK', '')

# default-воронка Grusha (b24-1tgrla.bitrix24.com)
BITRIX_PIPELINE_ID = 0
ACTIVE_STAGES = ['NEW', 'PREPARATION']
STAGE_WON = 'WON'
STAGE_LOSE = 'LOSE'

# Обязательные поля портала — без них Bitrix не даёт перевести в финальную стадию
WON_FIELDS_BASE = {
    'UF_CRM_1747386328579': '45',      # Выставлен расчёт? = Да
    'UF_CRM_1747386363677': '57',      # Подписан договор? = Да
    'UF_CRM_1747386416293': '53',      # Отправлены документы = Да
    'UF_CRM_CONTACT_PARTNER': '0',
}
LOSE_FIELDS_BASE = {
    'UF_CRM_1747386733488': '5951',    # Причина отказа = Просто интересовался
    'UF_CRM_1765303887148': '75',      # PAY_IN = крипта (дефолт)
    'UF_CRM_CONTACT_PARTNER': '0',
}

PAYIN_ENUM = {
    'crypto_direct': '75',
    'spp_doverka': '69',
    'sber_wl': '69',
    'sber_reqs': '69',
    'partners_cash': '71',
}
PAYOUT_ENUM = {
    'transfer': '63',
    'courier': '61',
    'office': '65',
    'atm': '65',
}


class BitrixError(RuntimeError):
    """Портал ответил ошибкой — текст пробрасываем оператору как есть."""


def _post(method: str, data: dict | None = None) -> dict:
    if not BITRIX_WEBHOOK:
        raise BitrixError('BITRIX_WEBHOOK не задан — вебхук портала берётся только из env')
    resp = requests.post(BITRIX_WEBHOOK + method, data=data or {}, timeout=20)
    try:
        return resp.json()
    except ValueError:
        raise BitrixError(f'{method}: HTTP {resp.status_code}, ответ не JSON')


def get_deal(deal_id: int) -> dict:
    return _post('crm.deal.get', {'id': str(deal_id)}).get('result', {})


def get_active_deals(limit: int = 50) -> list[dict]:
    """Незакрытые сделки основной воронки — то, что оператору предстоит разобрать.

    WON/LOSE отсекаются на портале, а не в Python: `crm.deal.list` отдаёт
    страницами по 50, и закрытые сделки (их подавляющее большинство) выбирали
    всю страницу целиком — список оператора оказывался пустым при живых
    активных сделках.
    """
    result = _post('crm.deal.list', {
        'filter[CATEGORY_ID]': BITRIX_PIPELINE_ID,
        'filter[!STAGE_ID][0]': STAGE_WON,
        'filter[!STAGE_ID][1]': STAGE_LOSE,
        'order[DATE_CREATE]': 'DESC',
        'select[0]': 'ID',
        'select[1]': 'TITLE',
        'select[2]': 'STAGE_ID',
        'select[3]': 'DATE_CREATE',
        'select[4]': 'CONTACT_ID',
    })
    deals = [d for d in result.get('result', []) or []
             if d.get('STAGE_ID') not in (STAGE_WON, STAGE_LOSE)]
    return deals[:limit]


def get_deal_chat_messages(deal_id: int, limit: int = 50) -> list[dict]:
    """Чат открытой линии: getLastId → im.dialog.messages.get.

    `crm.chat.get` тут не годится — у закрытых сессий он не отдаёт диалог,
    рабочая связка именно через getLastId (грабля из бота, см. память).
    """
    chat_id = _post('imopenlines.crm.chat.getLastId', {
        'CRM_ENTITY_TYPE': 'DEAL', 'CRM_ENTITY': str(deal_id),
    }).get('result')
    if not chat_id:
        return []
    msgs = _post('im.dialog.messages.get', {
        'DIALOG_ID': f'chat{chat_id}', 'LIMIT': str(limit),
    })
    return (msgs.get('result') or {}).get('messages', []) or []


def get_last_closed_deal_by_contact(contact_id, exclude_id) -> tuple[dict | None, int]:
    """Последняя закрытая сделка того же контакта + сколько их всего.

    Её CLOSEDATE — точка отсечки для анализатора: всё, что в чате раньше,
    относится к прошлому обмену и не должно попасть в суммы новой сделки.
    """
    if not contact_id:
        return None, 0
    result = _post('crm.deal.list', {
        'filter[CATEGORY_ID]': BITRIX_PIPELINE_ID,
        'filter[CONTACT_ID]': str(contact_id),
        'filter[STAGE_ID][0]': STAGE_WON,
        'filter[STAGE_ID][1]': STAGE_LOSE,
        'filter[!ID]': str(exclude_id),
        'order[CLOSEDATE]': 'DESC',
        'select[0]': 'ID',
        'select[1]': 'TITLE',
        'select[2]': 'STAGE_ID',
        'select[3]': 'CLOSEDATE',
        'select[4]': 'DATE_CREATE',
    })
    deals = result.get('result', []) or []
    if not deals:
        return None, 0
    return deals[0], len(deals)


def get_deal_utm(deal_id: int) -> str:
    return get_deal(deal_id).get('UTM_SOURCE') or ''


def set_deal_utm(deal_id: int, ref_code: str) -> bool:
    r = _post('crm.deal.update', {'id': str(deal_id), 'fields[UTM_SOURCE]': ref_code})
    return r.get('result') is True


def close_won(deal_id: int, data: dict) -> tuple[bool, str]:
    """WON с обязательными полями портала.

    OPPORTUNITY всегда в USD (USDT-эквивалент прихода), native-сумма и курс —
    в отдельных полях, выплата клиенту в THB.
    """
    fields = dict(WON_FIELDS_BASE)
    fields['STAGE_ID'] = STAGE_WON

    payin_usdt = data.get('payin_amount_usdt') or 0
    payin_rub = data.get('payin_amount_rub') or 0
    payin_method = data.get('payin_method') or 'crypto_direct'

    fields['OPPORTUNITY'] = str(payin_usdt)
    fields['CURRENCY_ID'] = 'USD'

    if payin_method == 'crypto_direct':
        fields['UF_CRM_PAYIN_NATIVE'] = f'{payin_usdt}|USD'
        fixed_rate = '1.00'
    else:
        fields['UF_CRM_PAYIN_NATIVE'] = f'{payin_rub}|RUB'
        fixed_rate = f'{payin_rub / payin_usdt:.4f}' if payin_usdt else ''
    if fixed_rate:
        fields['UF_CRM_FIXED_RATE'] = fixed_rate

    fields['UF_CRM_1761207574105'] = f"{data.get('payout_amount_thb') or 0}|THB"
    fields['UF_CRM_1765303887148'] = PAYIN_ENUM.get(payin_method, '75')
    fields['UF_CRM_1765303972133'] = PAYOUT_ENUM.get(data.get('payout_method') or 'transfer', '63')

    payload = {'id': str(deal_id)}
    for key, val in fields.items():
        payload[f'fields[{key}]'] = val
    result = _post('crm.deal.update', payload)
    if result.get('result') is True:
        return True, ''
    return False, str(result.get('error_description') or result.get('error') or result)


def close_lose(deal_id: int, reason: str = '') -> tuple[bool, str]:
    """LOSE. Причина обязательна на портале — пустую подменяем дефолтом."""
    fields = dict(LOSE_FIELDS_BASE)
    fields['STAGE_ID'] = STAGE_LOSE
    fields['UF_CRM_1610719896135'] = reason or 'Клиент не вернулся'

    payload = {'id': str(deal_id)}
    for key, val in fields.items():
        payload[f'fields[{key}]'] = val
    result = _post('crm.deal.update', payload)
    if result.get('result') is True:
        return True, ''
    return False, str(result.get('error_description') or result.get('error') or result)
