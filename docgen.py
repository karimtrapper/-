# -*- coding: utf-8 -*-
"""Генерация пакета документов MF Corp → клиент по проверенным юристом шаблонам.

Три флоу — три шаблона: freehold / leasehold / rental. Договор рамочный,
подписывается один раз на клиента И НА ТИП СДЕЛКИ (шаблоны юридически разные),
каждый последующий платёж оформляется своим Приложением 1 плюс инвойсом.

Правила зашиты по карте полей (wiki `crm-doc-generator-fields.md`):
  * комиссия по умолчанию вшита в курс, отдельно не взимается;
  * OUR/SHA/BEN — только фрихолд со SWIFT, на лизхолде и аренде внутренний
    тайский перевод без допрасходов;
  * назначение платежа генерируется и зависит от способа pay-in: на СБП его нет;
  * строки таблиц ищем по фрагменту текста, а не по индексу — юрист добавляет
    пункты и нумерация едет.
"""
from __future__ import annotations

import copy
import io
import os
import re
from datetime import datetime
import doc_routes

TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'doc_templates')
ASSETS = os.path.join(TEMPLATE_DIR, 'assets')

TEMPLATES = {
    'freehold': 'MF_Freehold_Payment_Agreement_Template_RU_EN.docx',
    'leasehold': 'MF_Leasehold_Payment_Agreement_Template_RU_EN.docx',
    'rental': 'MF_Rental_Payment_Agreement_Template_RU_EN_v2.docx',
    'payment': 'MF_Leasehold_Payment_Agreement_Template_RU_EN.docx',
}
INVOICE_TEMPLATE = 'MF_Invoice_Short_Template_RU_EN_v2.docx'
# Рублёвый «Коммерческий инвойс» — то, что реально уходит клиенту на оплату.
# Формат снят с MF-180-2808-1: позиция, назначение капсом, реквизиты ООО.
COMMERCIAL_INVOICE_TEMPLATE = 'MF_Commercial_Invoice_RU.docx'
PEC_TEMPLATE = 'MF_Payment_Execution_Confirmation_Template_RU_EN.docx'

DEAL_TYPE_TITLES = {
    'freehold': 'Фрихолд — покупка в собственность',
    'leasehold': 'Лизхолд — покупка права аренды',
    'rental': 'Аренда — депозит, арендная плата, коммунальные',
    'payment': 'Перевод / обмен',
}

AGENT = {
    'name': 'MF Corporation Company Limited',
    'reg': '0835565024547',
    'address': '9/31, Mu 5, Choeng Thale Sub-district, Thalang District, Phuket Province 83110, Thailand',
    'director': 'Miss Katika Sakornnoi',
    'email': 'mfcorpthai@gmail.com',
}

MONTHS_RU = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
             'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря']
MONTHS_EN = ['January', 'February', 'March', 'April', 'May', 'June',
             'July', 'August', 'September', 'October', 'November', 'December']

# Дефолты, снятые с живого договора Фролова (аренда, 01.09.2026)
# Срок исполнения различается по флоу — сверено с живыми договорами:
# аренда Фролова 1 рабочий день, фрихолд Антоненко и лизхолд Буровой по 3.
EXECUTION_DAYS = {'freehold': '3', 'leasehold': '3', 'rental': '1'}

DEFAULTS = {
    'execution_days': '3',
    'report_days': '5',
    'terminate_days': '10',
    'remaining_balance': 'отсутствует / none',
    'confirmation_contact': f"{AGENT['email']}; менеджер MF Corporation / MF Corporation manager",
    'bank_charges_local': ('Внутренний тайский перевод; дополнительные банковские расходы '
                           'с Клиента не взимаются / Domestic Thai transfer; no additional '
                           'bank charges are payable by the Client'),
    'fee_included': 'Включена в курс и в итоговую сумму / Included in the rate and in the total',
}

PAYIN_METHODS = {
    'bank': 'Банковский перевод / Bank transfer',
    'sbp': 'СБП (Система быстрых платежей) / SBP (Faster Payments System)',
    'usdt': 'USDT',
    'cash': 'Наличные / Cash',
}
PAYIN_EVIDENCE = {
    'bank': 'Платёжное поручение / Payment order',
    'sbp': 'Чек банковского приложения / Bank app receipt',
    'usdt': 'TXID транзакции / Transaction TXID',
    'cash': 'Кассовый документ / Cash receipt',
}


# ─────────────────────────── нумерация ───────────────────────────

def make_number(passport_no: str, when: datetime | None = None, seq: int = 1) -> str:
    """`MF-<3 последние цифры паспорта>-<ДДММ>-<номер соглашения>`.

    Схема Карима от 03.09.2026, подтверждена на договоре Бранова
    (паспорт 77 6892733, 16.06 → MF-733-1606).
    """
    digits = re.sub(r'\D', '', passport_no or '')
    tail = (digits[-3:] or '000').rjust(3, '0')
    when = when or datetime.now()
    return f'MF-{tail}-{when:%d%m}-{seq}'


def date_ru_en(when: datetime) -> str:
    return (f'{when.day} {MONTHS_RU[when.month - 1]} {when.year} / '
            f'{when.day} {MONTHS_EN[when.month - 1]} {when.year}')


# ─────────────────────── низкоуровневые правки docx ───────────────────────

def _para_replace(p, old: str, new: str) -> bool:
    """Замена подстроки в параграфе со склейкой runs (формат первого run)."""
    full = ''.join(r.text for r in p.runs)
    if old not in full:
        return False
    full = full.replace(old, new)
    for r in p.runs[1:]:
        r.text = ''
    if p.runs:
        p.runs[0].text = full
    return True


def _set_cell(cell, text: str) -> None:
    """Переписать ячейку, сохранив формат первого run. \n → перенос строки."""
    lines = str(text).split('\n')
    p = cell.paragraphs[0]
    for extra in cell.paragraphs[1:]:
        extra._element.getparent().remove(extra._element)
    if not p.runs:
        p.add_run('')
    base = p.runs[0]
    for r in p.runs[1:]:
        r._element.getparent().remove(r._element)
    base.text = lines[0]
    for line in lines[1:]:
        nr = copy.deepcopy(base._element)
        base._element.addnext(nr)
        base = p.runs[-1]
        base.text = line
        base._element.insert(0, base._element.makeelement(
            '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}br', {}))


def _find_row(table, needle: str):
    """Строка по фрагменту текста — устойчиво к сдвигу нумерации пунктов."""
    for row in table.rows:
        if any(needle in c.text for c in row.cells):
            return row
    return None


def _set_field(table, label: str, value) -> bool:
    """Приложения 1 и 2 — таблицы «метка | значение», значение в последней ячейке."""
    row = _find_row(table, label)
    if row is None or value in (None, ''):
        return False
    _set_cell(row.cells[-1], value)
    return True


def _unique_cells(doc):
    """Все ячейки документа по одному разу.

    Объединённая ячейка возвращается из row.cells несколько раз. Сравниваем сами
    элементы <w:tc>, а НЕ id() от них: lxml пересоздаёт прокси, адреса
    переиспользуются после сборки мусора, и дедупликация по id молча ломается.
    """
    cells, seen = [], []
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                if any(cell._tc is t for t in seen):
                    continue
                seen.append(cell._tc)
                cells.append(cell)
    return cells


def _sign_agent(doc, when: datetime) -> None:
    """Подпись Катики, дата и печать в блоки АГЕНТА — сразу, без прочерков.

    Клиенту документ уходит уже подписанным с нашей стороны: так просил Карим,
    прочерков под подпись Агента не оставляем.
    """
    from docx.shared import Inches  # noqa: PLC0415

    sig = os.path.join(ASSETS, 'signature.png')
    stamp = os.path.join(ASSETS, 'stamp.png')
    date_txt = f'Date: {when:%d.%m.%Y} / {when.day} {MONTHS_EN[when.month - 1]} {when.year}'
    for cell in _unique_cells(doc):
        text = cell.text
        # блок АГЕНТА: и в теле договора, и в приложении. У клиента в той же
        # строке отдельная ячейка — её не трогаем, там подпись ставит клиент.
        if AGENT['director'] not in text and 'Registration / Tax No.' not in text:
            continue
        signed = False
        for p in cell.paragraphs:
            for r in p.runs:
                if r.text.strip().startswith('Signature:') and os.path.exists(sig):
                    r.text = 'Signature: '
                    r.add_picture(sig, width=Inches(1.4))
                    signed = True
                elif r.text.strip().startswith('Date:'):
                    r.text = date_txt
        if signed and os.path.exists(stamp):
            sp = cell.add_paragraph()
            sp.add_run().add_picture(stamp, width=Inches(1.2))


def _strip_draft_mark(doc) -> None:
    for p in list(doc.paragraphs):
        if p.text.strip() == 'ОБЕЗЛИЧЕННЫЙ ШАБЛОН':
            p._element.getparent().remove(p._element)


# ─────────────────────── сборка значений полей ───────────────────────

# Гражданство в паспорте написано по-русски, а в английской колонке договора
# кириллица выглядит браком. Переводим известные, остальное оставляем как есть.
CITIZENSHIP_EN = {
    'российской федерации': 'the Russian Federation', 'россии': 'the Russian Federation',
    'рф': 'the Russian Federation', 'республики болгария': 'the Republic of Bulgaria',
    'болгарии': 'the Republic of Bulgaria', 'республики казахстан': 'the Republic of Kazakhstan',
    'казахстана': 'the Republic of Kazakhstan', 'республики беларусь': 'the Republic of Belarus',
    'беларуси': 'the Republic of Belarus', 'украины': 'Ukraine', 'армении': 'the Republic of Armenia',
    'узбекистана': 'the Republic of Uzbekistan', 'киргизии': 'the Kyrgyz Republic',
}


# В паспорте гражданство стоит в именительном («Российская Федерация»),
# а в договоре нужен родительный: «гражданин Российской Федерации».
CITIZENSHIP_RU = {
    'российская федерация': 'Российской Федерации', 'россия': 'Российской Федерации',
    'республика болгария': 'Республики Болгария', 'болгария': 'Республики Болгария',
    'республика казахстан': 'Республики Казахстан', 'казахстан': 'Республики Казахстан',
    'республика беларусь': 'Республики Беларусь', 'беларусь': 'Республики Беларусь',
    'украина': 'Украины', 'республика армения': 'Республики Армения', 'армения': 'Республики Армения',
    'республика узбекистан': 'Республики Узбекистан', 'узбекистан': 'Республики Узбекистан',
    'киргизская республика': 'Киргизской Республики', 'киргизия': 'Киргизской Республики',
}


def citizenship_ru(value: str) -> str:
    """Приводим к родительному. Приставку «гражданин» срезаем — в договоре
    она уже есть в шаблоне строки, иначе выйдет «гражданин гражданин ...»."""
    v = (value or '').strip()
    stripped = v
    for pref in ('гражданина', 'гражданин', 'гражданки', 'гражданка'):
        if stripped.lower().startswith(pref):
            stripped = stripped[len(pref):].strip()
            break
    return CITIZENSHIP_RU.get(stripped.lower(), stripped)


def citizenship_en(value: str) -> str:
    """Гражданство → английская колонка.

    Паспорт даёт именительный («Российская Федерация»), договоры и прошлые
    сделки — родительный («Российской Федерации»). Сначала приводим к
    родительному, потом переводим: одна таблица вместо двух.
    """
    # lstrip() режет символы, а не префикс — здесь нужен именно removeprefix
    v = (value or '').strip()
    key = v.lower().removeprefix('гражданин').removeprefix('гражданка').strip()
    genitive = CITIZENSHIP_RU.get(key, v)
    for candidate in (genitive.lower(), key, v.lower()):
        if candidate in CITIZENSHIP_EN:
            return CITIZENSHIP_EN[candidate]
    return v


def client_line(f: dict, lang: str = 'ru') -> str:
    """Преамбула клиента: ФИО, гражданство, паспорт, выдан, срок, ДР, нац. ID."""
    if lang == 'ru':
        parts = [f.get('client_name_ru') or f.get('client_name_en') or '']
        if f.get('client_name_en') and f.get('client_name_ru'):
            parts[0] += f" ({f['client_name_en']})"
        if f.get('client_citizenship'):
            parts.append(f"гражданин {citizenship_ru(f['client_citizenship'])}")
        if f.get('client_passport_no'):
            parts.append(f"паспорт № {f['client_passport_no']}")
        if f.get('client_passport_issue_date'):
            issued = f"выдан {f['client_passport_issue_date']}"
            if f.get('client_passport_issued_by'):
                issued += f" {f['client_passport_issued_by']}"
            parts.append(issued)
        if f.get('client_passport_expiry_date'):
            parts.append(f"действителен до {f['client_passport_expiry_date']}")
        if f.get('client_birth_date'):
            parts.append(f"дата рождения {f['client_birth_date']}")
        if f.get('client_national_id'):
            parts.append(f"персональный № {f['client_national_id']}")
        return ', '.join(p for p in parts if p)

    parts = [f.get('client_name_en') or f.get('client_name_ru') or '']
    if f.get('client_citizenship'):
        parts.append(f"a citizen of {citizenship_en(f['client_citizenship'])}")
    if f.get('client_passport_no'):
        parts.append(f"passport No. {f['client_passport_no']}")
    if f.get('client_passport_issue_date'):
        parts.append(f"issued on {f['client_passport_issue_date']}")
    if f.get('client_passport_expiry_date'):
        parts.append(f"valid until {f['client_passport_expiry_date']}")
    if f.get('client_birth_date'):
        parts.append(f"date of birth {f['client_birth_date']}")
    if f.get('client_national_id'):
        parts.append(f"personal No. {f['client_national_id']}")
    return ', '.join(p for p in parts if p)


def property_line(f: dict, deal_type: str) -> str:
    bits = []
    if f.get('project_name'):
        bits.append(f['project_name'])
    if f.get('unit_no'):
        bits.append(f"юнит / unit {f['unit_no']}")
    if f.get('property_address'):
        bits.append(f"адрес / address: {f['property_address']}")
    if deal_type == 'rental':
        if f.get('rent_amount'):
            bits.append(f"арендная плата / rent: {f['rent_amount']}")
        if f.get('deposit_amount'):
            bits.append(f"депозит / deposit: {f['deposit_amount']}")
    if deal_type == 'leasehold':
        if f.get('lease_term'):
            bits.append(f"срок leasehold / lease term: {f['lease_term']}")
        if f.get('lease_start_date'):
            bits.append(f"дата начала / start date: {f['lease_start_date']}")
    return ';\n'.join(bits)


def recipient_details(f: dict) -> str:
    rows = []
    if f.get('recipient_bank'):
        rows.append(f"Банк / Bank: {f['recipient_bank']}")
    if f.get('recipient_account'):
        rows.append(f"Счёт / Account No.: {f['recipient_account']}")
    if f.get('recipient_swift'):
        rows.append(f"SWIFT: {f['recipient_swift']}")
    if f.get('recipient_bik'):
        rows.append(f"БИК / BIK: {f['recipient_bik']}")
    if f.get('recipient_bank_address'):
        rows.append(f"Адрес банка / Bank address: {f['recipient_bank_address']}")
    return '\n'.join(rows)


def payment_basis(f: dict, deal_type: str) -> str:
    if deal_type == 'payment' and not f.get('invoice_no') and not f.get('contract_ref'):
        return 'Поручение Клиента на перевод средств / Client instruction to transfer funds'
    if deal_type == 'rental' and not f.get('invoice_no'):
        base = 'Договор аренды (Lease Agreement)'
        if f.get('contract_ref'):
            base += f" {f['contract_ref']}"
        return base + ';\nотдельный инвойс не выставлялся / no separate invoice issued'
    bits = []
    if f.get('invoice_no'):
        inv = f"Инвойс / Invoice № {f['invoice_no']}"
        if f.get('invoice_date'):
            inv += f" от / dated {f['invoice_date']}"
        bits.append(inv)
    if f.get('contract_ref'):
        bits.append(f"Договор-основание / Underlying contract: {f['contract_ref']}")
    return ';\n'.join(bits)


def building_of(unit: str) -> str:
    """Корпус из номера юнита: B2-711 → B2. У вилл и участков корпуса нет."""
    u = (unit or '').strip()
    if '-' in u:
        head = u.split('-', 1)[0].strip()
        if head and len(head) <= 4:
            return head
    return ''


def property_description(f: dict, deal_type: str) -> str:
    """Строка позиции коммерческого инвойса.

    Формат снят с реальных инвойсов MF-180-2808-1 и MF-180-3108-1:
    «Оплата по графику за апартаменты HEART BY BOTANICA (PHASE 1),
    Building B2, Unit B2-711 (leasehold).»
    """
    kind = {'freehold': 'freehold', 'leasehold': 'leasehold', 'rental': 'аренда'}.get(deal_type, '')
    bits = []
    if f.get('project_name'):
        bits.append(str(f['project_name']))
    building = building_of(f.get('unit_no', ''))
    if building:
        bits.append(f'Building {building}')
    if f.get('unit_no'):
        bits.append(f"Unit {f['unit_no']}")
    body = ', '.join(bits) if bits else 'объект по договору'
    tail = f' ({kind})' if kind else ''
    return f'Оплата по графику за апартаменты {body}{tail}.'


def payment_reference(f: dict, method: str, part: int | None = None) -> str:
    """Назначение платежа для банка клиента.

    Формулировка каноническая — переписана с реальных инвойсов MF Corp:
    «ОПЛАТА ПО ИНВОЙСУ № BBB1-2026018 ОТ 26.08.2026 ЗА АПАРТАМЕНТЫ
    UNIT B2-711, BUILDING B2, HEART BY BOTANICA (PHASE 1),
    ДЛЯ NADEZHDA BUROVA. БЕЗ НДС.»

    Капс, дата инвойса, корпус и ФИО ЛАТИНИЦЕЙ — банк сверяет платёж с
    инвойсом застройщика, поэтому отсебятина здесь дороже всего.
    """
    if method in ('sbp', 'usdt', 'cash'):
        return ('Без указания назначения платежа; подтверждение оплаты направляется менеджеру MF / '
                'No payment reference in the transfer; the payment evidence is sent to the MF manager')
    head = 'ОПЛАТА ПО ИНВОЙСУ'
    if f.get('invoice_no'):
        head += f" № {f['invoice_no']}"
    if f.get('invoice_date'):
        head += f" ОТ {f['invoice_date']}"
    obj = []
    if f.get('unit_no'):
        obj.append(f"UNIT {f['unit_no']}")
    building = building_of(f.get('unit_no', ''))
    if building:
        obj.append(f'BUILDING {building}')
    if f.get('project_name'):
        obj.append(str(f['project_name']))
    # после даты инвойса запятой нет — «… ОТ 26.08.2026 ЗА АПАРТАМЕНТЫ …»
    if obj:
        head += ' ЗА АПАРТАМЕНТЫ ' + ', '.join(obj)
    parts = [head]
    # в назначении ФИО латиницей — так его сверяет банк-получатель
    name = f.get('client_name_en') or f.get('client_name_ru') or ''
    if name:
        parts.append(f'ДЛЯ {name}')
    if part and part > 1:
        parts.append(f'ЧАСТЬ {part}')
    return (', '.join(parts) + '. БЕЗ НДС.').upper()


# ─────────────────────── заполнение приложений ───────────────────────

def _fill_client_signature(table, f: dict, money: dict) -> None:
    """Блок подписи Клиента — он повторяется в теле договора и в Приложении 1."""
    for row in table.rows:
        for cell in row.cells:
            if '[Full name / legal name]' not in cell.text:
                continue
            for p in cell.paragraphs:
                _para_replace(p, '[Full name / legal name]',
                              f.get('client_name_ru') or f.get('client_name_en') or '')
                _para_replace(p, '[ID / Registration No.]', f.get('client_passport_no') or '')
                _para_replace(p, '[Address]', money.get('client_address') or '')
                _para_replace(p, '[Email / phone]', money.get('client_contact') or '')
                _para_replace(p, '[Authorised signatory, if applicable]', '—')


def _fill_appendix1(doc, f: dict, deal_type: str, money: dict, number: str, when: datetime) -> None:
    t = doc.tables[1]
    _, incoming, outgoing = doc_routes.pair_for(money, deal_type)
    payin = doc_routes.amount(money.get('total_payin'), incoming)
    payout = doc_routes.amount((money.get('usd_equivalent') if deal_type == 'freehold' else None)
                              or money.get('transfer_amount'), outgoing)
    # Формулировки дословно из живых документов: у Фролова (аренда) и Буровой
    # (лизхолд) комиссия «в курсе», у Антоненко (фрихолд) курса RUB/THB нет
    # вовсе — там «в согласованной сумме pay-in».
    if deal_type == 'freehold':
        default_fee = ('Включена в согласованную сумму pay-in; отдельно не взимается / '
                       'Included in the agreed pay-in amount; no separate charge')
    else:
        default_fee = (f"Включена в курс {money.get('rate', '')} {incoming}/{outgoing}, отдельно не взимается / "
                       f"Included in the rate of {money.get('rate', '')} {incoming}/{outgoing}, "
                       f"not charged separately")
    fee_note = money.get('fee_note') or default_fee

    _set_field(t, 'Номер и дата', f'№ {number} от {date_ru_en(when)}')
    _set_field(t, 'Клиент / Client', client_line(f, 'ru') + '\n' + client_line(f, 'en'))
    _set_field(t, 'Основание платежа', payment_basis(f, deal_type))
    _set_field(t, 'Объект / Property', property_line(f, deal_type) or
               ('Перевод средств / Funds transfer' if deal_type == 'payment' else ''))
    _set_field(t, 'Получатель / Recipient', f.get('recipient_name'))
    _set_field(t, 'Реквизиты получателя', recipient_details(f))
    _set_field(t, 'Комиссия Агента / Agent', fee_note)
    _set_field(t, 'Всего к оплате Клиентом', payin)
    _set_field(t, 'Сумма для перечисления получателю', payout)
    if outgoing == 'USDT':
        _set_field(t, 'Реквизиты получателя',
                   f"Сеть / Network: {money.get('payout_network', '')}\nUSDT: {money.get('payout_wallet', '')}")
    _set_field(t, 'Остаток после исполнения', DEFAULTS['remaining_balance'])
    days = money.get('execution_days') or EXECUTION_DAYS.get(deal_type, DEFAULTS['execution_days'])
    word = 'рабочий день' if str(days) == '1' else 'рабочих дня'
    _set_field(t, 'Срок исполнения',
               f'{days} {word} после выполнения п. 2.2 Договора / '
               f'{days} business day(s) after Clause 2.2 is met')
    _set_field(t, 'Контакт для подтверждения', DEFAULTS['confirmation_contact'])

    # итоговый блок: обе комиссии по умолчанию вшиты в курс
    rows = [r for r in t.rows if 'Комиссия Агента' in r.cells[0].text]
    if len(rows) > 1:
        _set_cell(rows[-1].cells[-1], DEFAULTS['fee_included'])
    _set_field(t, 'Комиссия платёжного партнёра', DEFAULTS['fee_included'])

    if deal_type == 'freehold':
        _set_field(t, 'Банковские расходы', money.get('bank_charges') or 'OUR')
        _set_field(t, 'Сумма и валюта pay-in', payin)
        _set_field(t, 'Обязательство по инвойсу застройщика',
                   f"{f.get('invoice_currency') or 'THB'} {f.get('invoice_amount') or ''}".strip())
        _set_field(t, 'Источник курса и срок действия', money.get('rate_source'))
        _set_field(t, 'Подтверждённый USD-эквивалент', money.get('usd_equivalent'))
        _set_field(t, 'Статус зачёта THB-инвойса', money.get('thb_credit_status'))
        _set_field(t, 'Письменное подтверждение застройщика', money.get('developer_confirmation'))
    else:
        _set_field(t, 'Банковские расходы', DEFAULTS['bank_charges_local'] if outgoing == 'THB' else
                   money.get('bank_charges') or 'Включены в итоговую сумму / Included in the total')
        _set_field(t, 'Сумма, поступающая Агенту', payin)
        _set_field(t, 'Сумма и валюта перевода', payout)
        _set_field(t, 'Курс и срок его действия',
                   f"{money.get('rate', '')} {incoming} за 1 {outgoing} / {money.get('rate', '')} {incoming} per 1 {outgoing} — "
                   f"до {money.get('rate_valid_until') or f'{when:%d.%m.%Y}, 23:59 (GMT+7)'}")

    if deal_type == 'leasehold':
        _set_field(t, 'да / нет / не подтверждено', money.get('registration_needed') or 'не подтверждено / not confirmed')
        _set_field(t, 'клиент / застройщик / арендодатель',
                   money.get('registration_by') or 'застройщик / developer')
    if deal_type == 'rental':
        _set_field(t, 'Вид платежа', money.get('payment_type') or 'депозит / deposit')

    _fill_client_signature(t, f, money)


def _fill_appendix2(doc, f: dict, money: dict, number: str, when: datetime) -> None:
    """Приложение 2 — маршрут pay-in.

    Реквизиты и назначение здесь НЕ дублируются, а отсылают к коммерческому
    инвойсу: так в обоих живых договорах — у Буровой «Указывается в Invoice
    № MF-180-2808-1 / As stated in the Invoice», у Антоненко «По отдельному
    коммерческому инвойсу Агента». Дублировать опасно: реквизиты меняются,
    а подписанный договор — нет.
    """
    t = doc.tables[2]
    method = money.get('payin_method') or 'bank'
    valid = money.get('rate_valid_until') or f'{when:%d.%m.%Y}, 23:59 (GMT+7)'
    agent = AGENT['name']
    _set_field(t, 'Способ pay-in', doc_routes.METHODS.get(method, method))
    _set_field(t, 'Валюта / Currency', money.get('payin_currency') or 'RUB')
    _set_field(t, 'Получатель платежа',
               f'Указывается в актуальном Invoice № {number}: {agent} либо уполномоченный '
               f'платёжный партнёр Агента / As stated in the current Invoice: {agent} '
               f'or the Agent authorised payment partner')
    _set_field(t, 'Роль получателя',
               'Агент либо указанный им уполномоченный получатель / '
               'Agent or its authorised pay-in recipient')
    _set_field(t, 'Реквизиты / Payment details',
               money.get('payin_details')
               or f'Банковские реквизиты указываются в актуальном Invoice № {number} '
                  f'с номером, датой и сроком действия реквизитов; переносить реквизиты '
                  f'из предыдущих сделок запрещено / Bank details are stated in the current '
                  f'Invoice bearing its number, date and validity period')
    _set_field(t, 'Invoice / Instruction No.', f'№ {number} от {when:%d.%m.%Y}')
    _set_field(t, 'Срок действия реквизитов', valid)
    _set_field(t, 'Назначение платежа',
               f'Указывается в Invoice № {number} / As stated in the Invoice')
    _set_field(t, 'Подтверждение оплаты', PAYIN_EVIDENCE.get(method, ''))
    if money.get('payin_recipient'):
        _set_field(t, 'Получатель платежа', money['payin_recipient'])
        _set_field(t, 'Роль получателя', money.get('payin_recipient_role', ''))
    if method in ('usdt', 'cash') or money.get('payin_details'):
        _set_field(t, 'Реквизиты / Payment details', doc_routes.details(money))
    if method != 'bank':
        _set_field(t, 'Назначение платежа', payment_reference(f, method))
    _set_field(t, 'Наличные', doc_routes.details(money) if method == 'cash' else
               'Не применимо / Not applicable')


def _apply_route(doc, money, deal_type):
    """Валюта и способ оплаты в обеих языковых колонках рамочного договора."""
    _, incoming, outgoing = doc_routes.pair_for(money, deal_type)
    paragraphs = list(doc.paragraphs) + [p for c in _unique_cells(doc) for p in c.paragraphs]
    for p in paragraphs:
        _para_replace(p, 'RUB/THB', f'{incoming}/{outgoing}')
        if deal_type == 'payment':
            for old, new in [('LEASEHOLD PAYMENT ARRANGEMENT', 'PAYMENT ARRANGEMENT'),
                             ('ОПЛАТЫ LEASEHOLD', 'ПЕРЕВОДА СРЕДСТВ'),
                             ('Leasehold Payment Instruction', 'Payment Instruction'),
                             ('Leasehold Payment Arrangement', 'Payment Arrangement'),
                             ('LEASEHOLD PAYMENT INSTRUCTION', 'PAYMENT INSTRUCTION'),
                             ('оплаты leasehold', 'перевода средств'),
                             ('THB', outgoing)]:
                _para_replace(p, old, new)
            if outgoing == 'USDT':
                for old, new in [
                    ('платеж не был осуществлен Агентом Банку', 'перевод не был осуществлен Агентом получателю'),
                    ('Agent to the Bank', 'Agent to the recipient'),
                    ('направления платежа банку', 'направления перевода получателю'),
                    ('submitting the payment to the bank', 'submitting the transfer to the recipient'),
                    ('доступный банковский reference', 'доступный TXID перевода'),
                    ('available bank reference', 'available transaction ID (TXID)'),
                ]:
                    _para_replace(p, old, new)
    if deal_type == 'payment':
        replacements = {
            '1.1.': ('Агент по поручению и за счёт Клиента организует конвертацию и перевод средств получателю, указанному в отдельной Payment Instruction (Приложение 1). Основание, цель перевода, валюты и реквизиты определяются в этой инструкции (далее — «Основная сделка»).',
                     'At the Client’s instruction and expense, the Agent arranges conversion and transfer of funds to the recipient specified in a separate Payment Instruction (Appendix 1). The basis, purpose, currencies and payment details are specified in that instruction (the “Underlying Transaction”).'),
            '1.2.': ('Агент организует перевод средств и не является стороной Основной сделки между Клиентом и получателем.', 'The Agent arranges the funds transfer and is not a party to the Underlying Transaction between the Client and the recipient.'),
            '3.1.': ('До исполнения Клиент предоставляет документы, подтверждающие основание перевода, сведения о получателе и иные документы, разумно запрошенные Агентом.', 'Before execution, the Client provides documents supporting the transfer basis, recipient details and other documents reasonably requested by the Agent.'),
            '3.2.': ('Клиент самостоятельно проверяет основание перевода и реквизиты получателя. Агент не проводит юридическую проверку Основной сделки, если отдельно письменно не согласовано иное.', 'The Client independently verifies the transfer basis and recipient details. The Agent does not perform legal due diligence of the Underlying Transaction unless separately agreed in writing.'),
            '6.2.': ('Агент не отвечает за действия получателя, банка, платёжной системы или органа власти; а также косвенные убытки и упущенную выгоду.', 'The Agent is not liable for acts of the recipient, bank, payment system or public authority, or for indirect losses and lost profit.'),
        }
        for row in doc.tables[0].rows:
            ru = row.cells[-2].text.strip()
            for clause, (ru_text, en_text) in replacements.items():
                if ru.startswith(clause):
                    _set_cell(row.cells[-2], clause + ' ' + ru_text)
                    _set_cell(row.cells[-1], clause + ' ' + en_text)
            if ru.startswith('3. ДОКУМЕНТЫ'):
                _set_cell(row.cells[-2], '3. ДОКУМЕНТЫ ПО ПЕРЕВОДУ')
                _set_cell(row.cells[-1], '3. TRANSFER DOCUMENTS')
        if len(doc.tables) > 1:
            row = doc.tables[1].rows[1]
            _set_cell(row.cells[-2], 'Клиент подтверждает точность реквизитов получателя и согласие на исполнение перевода на указанных условиях.')
            _set_cell(row.cells[-1], 'The Client confirms the accuracy of recipient details and agrees to execution of the transfer on the stated terms.')
    row = _find_row(doc.tables[0], '2.1.')
    if row is not None:
        for cell, text in zip(row.cells[-2:], [
            f"Для настоящего Договора согласовано направление {incoming} → {outgoing}; способ оплаты Клиентом: {doc_routes.METHODS[money['payin_method']]}. Конкретные реквизиты и сеть, если применимо, указываются в Invoice и Payment Instruction.",
            f"The agreed route under this Agreement is {incoming} → {outgoing}; the Client’s pay-in method is {doc_routes.METHODS[money['payin_method']].split(' / ')[-1]}. Transaction details and network, where applicable, are specified in the Invoice and Payment Instruction."]):
            cell.add_paragraph(text)


# ─────────────────────────── публичное API ───────────────────────────

def _drop_annexes(doc) -> None:
    """Вырезать Приложения 1 и 2 из рамочного договора.

    Всё, что идёт после первого заголовка «ПРИЛОЖЕНИЕ», относится к приложениям
    и уезжает в доп. соглашение. Тело договора (таблица 0) остаётся.
    """
    body = doc.element.body
    dropping = False
    for child in list(body):
        if child.tag.endswith('}p'):
            text = ''.join(child.itertext()).strip().upper()
            if text.startswith('ПРИЛОЖЕНИЕ'):
                dropping = True
        if dropping and not child.tag.endswith('}sectPr'):
            body.remove(child)
    # Пустой абзац с разрывом перед первым приложением не должен создавать
    # пустую последнюю страницу рамочного договора.
    for child in reversed(list(body)):
        if child.tag.endswith('}sectPr'):
            continue
        if child.tag.endswith('}p') and not ''.join(child.itertext()).strip():
            body.remove(child)
        else:
            break


def build_agreement(deal_type: str, fields: dict, money: dict,
                    number: str | None = None, when: datetime | None = None,
                    blank_annexes: bool = True) -> tuple[bytes, str]:
    """Рамочный договор. → (docx-байты, номер).

    По умолчанию Приложения 1 и 2 остаются пустыми формами: договор клиент
    подписывает один раз и держит у себя неизменным, а суммы и курс каждого
    платежа живут в отдельном дополнительном соглашении. Заполненные
    приложения внутри договора сделали бы его привязанным к первому платежу.
    """
    from docx import Document  # noqa: PLC0415

    if deal_type not in TEMPLATES:
        raise ValueError(f'неизвестный тип сделки: {deal_type}')
    when = when or datetime.now()
    number = number or make_number(fields.get('client_passport_no', ''), when, 1)
    money = doc_routes.normalize(money, deal_type)

    doc = Document(os.path.join(TEMPLATE_DIR, TEMPLATES[deal_type]))
    _strip_draft_mark(doc)
    _apply_route(doc, money, deal_type)

    for p in doc.paragraphs:
        if p.text.startswith('АГЕНТСКИЙ ДОГОВОР'):
            p.add_run(f' № {number}')
        _para_replace(p, 'г. [●] / [●], [дата / date]',
                      f'г. Пхукет, Таиланд / Phuket, Thailand, {date_ru_en(when)}')

    body = doc.tables[0]
    for row in body.rows:
        for cell in row.cells:
            for p in cell.paragraphs:
                _para_replace(p, '[ФИО / полное наименование, ID/регистрационный номер, адрес]',
                              client_line(fields, 'ru'))
                _para_replace(p, '[full name / legal name, ID or registration number, address]',
                              client_line(fields, 'en'))
                _para_replace(p, '[учредительных документов / corporate documents]',
                              'учредительных документов')
                _para_replace(p, '[corporate documents]', 'the corporate documents')
                _para_replace(p, '[Full name / legal name]',
                              fields.get('client_name_ru') or fields.get('client_name_en') or '')
                _para_replace(p, '[ID / Registration No.]', fields.get('client_passport_no') or '')
                _para_replace(p, '[Address]', money.get('client_address') or '')
                _para_replace(p, '[Email / phone]', money.get('client_contact') or '')
                _para_replace(p, '[Authorised signatory, if applicable]', '—')
                _para_replace(p, '[5]', DEFAULTS['report_days'])
                _para_replace(p, '[10]', DEFAULTS['terminate_days'])

    row = _find_row(body, 'рабочих дней после выполнения пункта 2.2')
    if row is not None:
        # в rental пункт лежит в колонках 0/1, во freehold — в 1/2, поэтому все
        for cell in row.cells:
            for p in cell.paragraphs:
                _para_replace(p, '[●]', money.get('execution_days') or DEFAULTS['execution_days'])

    if blank_annexes:
        # Приложения из рамочного договора убираем совсем: они всё равно
        # выпускаются отдельным доп. соглашением на каждый платёж, а пустые
        # бланки внутри подписанного договора только путают клиента.
        _drop_annexes(doc)
    else:
        _fill_appendix1(doc, fields, deal_type, money, number, when)
        _fill_appendix2(doc, fields, money, number, when)
    _sign_agent(doc, when)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue(), number


def build_addendum(deal_type: str, fields: dict, money: dict, number: str,
                   parent_number: str, seq: int, when: datetime | None = None) -> bytes:
    """Доп. соглашение на очередной платёж: только Приложения 1 и 2.

    Договор не перевыпускаем — допник ссылается на него, как и требует шаблон
    инвойса («договор № … от …; платёжная инструкция № … от …»).
    """
    from docx import Document  # noqa: PLC0415

    when = when or datetime.now()
    money = doc_routes.normalize(money, deal_type)
    doc = Document(os.path.join(TEMPLATE_DIR, TEMPLATES[deal_type]))
    _strip_draft_mark(doc)
    _apply_route(doc, money, deal_type)
    _fill_appendix1(doc, fields, deal_type, money, number, when)
    _fill_appendix2(doc, fields, money, number, when)
    _sign_agent(doc, when)

    # выкидываем тело договора — остаются только приложения
    body = doc.tables[0]._element
    body.getparent().remove(body)
    kept = 0
    for p in list(doc.paragraphs):
        if 'ПРИЛОЖЕНИЕ' in p.text.upper():
            kept += 1
        if kept == 0:
            p._element.getparent().remove(p._element)

    # insert_paragraph_before вставляет ПЕРЕД якорем, поэтому якорь один и тот же,
    # а строки идут в нужном порядке: RU → EN → место и дата
    anchor = doc.paragraphs[0]
    anchor.insert_paragraph_before(
        f'ДОПОЛНИТЕЛЬНОЕ СОГЛАШЕНИЕ № {seq} к Агентскому договору № {parent_number}')
    anchor.insert_paragraph_before(
        f'SUPPLEMENTARY AGREEMENT No. {seq} to Agency Agreement No. {parent_number}')
    anchor.insert_paragraph_before(
        f'г. Пхукет, Таиланд / Phuket, Thailand, {date_ru_en(when)}')

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def build_invoice(fields: dict, money: dict, number: str, parent_number: str,
                  instruction_number: str, when: datetime | None = None) -> bytes:
    """Счёт клиенту на pay-in. Всегда ссылается на рамочный договор."""
    from docx import Document  # noqa: PLC0415

    when = when or datetime.now()
    doc = Document(os.path.join(TEMPLATE_DIR, INVOICE_TEMPLATE))
    _strip_draft_mark(doc)
    method = money.get('payin_method') or 'bank'
    valid = money.get('rate_valid_until') or f'{when:%d.%m.%Y}, 23:59 (GMT+7)'
    repl = {
        '[MF-INV-●]': number,
        '[дд.мм.гггг, время]': valid,
        '[дд.мм.гггг]': f'{when:%d.%m.%Y}',
        '[ФИО / наименование компании]': fields.get('client_name_ru')
                                          or fields.get('client_name_en') or '',
        '[проект, юнит / объект]': property_line(fields, money.get('deal_type') or 'leasehold'),
        '[договор № … от …; платёжная инструкция № … от …]':
            f'Договор № {parent_number}; платёжная инструкция № {instruction_number} '
            f'от {when:%d.%m.%Y}',
        '[например: оплата по сделке / бронирование / очередной платёж]':
            money.get('payment_purpose') or 'очередной платёж по договору',
        '[включена в сумму / дополнительно: …]': 'включена в сумму',
        '[валюта]': money.get('payin_currency') or 'RUB',
        '[сумма]': str(money.get('total_payin') or ''),
        '[банковский перевод / СБП / USDT / иной согласованный способ]':
            PAYIN_METHODS.get(method, method),
        '[полное наименование получателя]': AGENT['name'],
        '[счёт, банк, БИК / СБП / сеть и адрес кошелька]': money.get('payin_details') or '',
        '[указать строго в этой формулировке]':
            money.get('payment_reference') or payment_reference(fields, method, money.get('part')),
    }
    for p in doc.paragraphs:
        for old, new in repl.items():
            _para_replace(p, old, new)
    for t in doc.tables:
        for row in t.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    for old, new in repl.items():
                        _para_replace(p, old, new)
    _sign_agent(doc, when)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()



def money_ru(amount, currency: str = 'RUB') -> str:
    """«2 800 000 руб.» — формат сумм в коммерческом инвойсе."""
    raw = str(amount or '').replace('\u00a0', ' ').replace(' ', '').replace(',', '.')
    try:
        value = float(raw)
    except ValueError:
        return str(amount or '')
    whole = f'{value:,.0f}'.replace(',', '\u00a0') if value == int(value) else \
        f'{value:,.2f}'.replace(',', '\u00a0')
    suffix = {'RUB': 'руб.', 'THB': '฿', 'USD': 'USD', 'USDT': 'USDT'}.get(currency, currency)
    return f'{whole} {suffix}'


def build_commercial_invoice(fields: dict, money: dict, number: str,
                             deal_type: str, when: datetime | None = None) -> bytes:
    """Инвойс по выбранному маршруту и реквизитам конкретной операции.

    Старый RUB-шаблон оставлен лишь для совместимости прямых legacy-вызовов;
    API требует явно заполнить реквизиты и всегда использует route invoice.
    """
    from docx import Document  # noqa: PLC0415

    when = when or datetime.now()
    money = doc_routes.normalize(money, deal_type)
    # Один платёжный маршрут — один источник реквизитов. Старый банковский
    # шаблон допустим только для legacy-вызовов RUB/bank без новых полей.
    if money['payin_method'] != 'bank' or money['payin_currency'] != 'RUB' or money.get('payin_details'):
        return _route_invoice(fields, money, number, when)
    doc = Document(os.path.join(TEMPLATE_DIR, COMMERCIAL_INVOICE_TEMPLATE))
    method = money.get('payin_method') or 'bank'
    client_bits = [fields.get('client_name_en') or fields.get('client_name_ru') or '']
    if fields.get('client_passport_no'):
        client_bits.append(f"паспорт {fields['client_passport_no']}")
    if fields.get('client_passport_issue_date'):
        client_bits.append(f"дата выдачи {fields['client_passport_issue_date']}")
    repl = {
        '[CLIENT]': ', '.join(b for b in client_bits if b),
        '[NUMBER]': number,
        '[DATE]': f'{when:%d.%m.%Y}',
        '[DESCRIPTION]': money.get('invoice_description')
                         or property_description(fields, deal_type),
        '[AMOUNT]': money_ru(money.get('total_payin'), money.get('payin_currency') or 'RUB'),
        '[PURPOSE]': money.get('payment_reference')
                     or payment_reference(fields, method, money.get('part')),
    }
    targets = list(doc.paragraphs)
    for t in doc.tables:
        for row in t.rows:
            for cell in row.cells:
                targets.extend(cell.paragraphs)
    for p in targets:
        for old, new in repl.items():
            _para_replace(p, old, new)
    _sign_agent(doc, when)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _route_invoice(fields, money, number, when):
    from docx import Document
    doc = Document(io.BytesIO(build_invoice(fields, money, number,
                   money.get('parent_number') or number, number, when)))
    _set_field(doc.tables[1], 'Клиент', client_line(fields, 'ru') + '\n' + client_line(fields, 'en'))
    _set_field(doc.tables[1], 'Сделка', property_line(fields, money.get('deal_type', 'payment')) or
               f"Перевод / Transfer {money['pair'].replace('_', ' → ')}")
    _set_field(doc.tables[1], 'Основание',
               f"Договор / Agreement № {money.get('parent_number') or number}; Instruction № {number}\n" +
               payment_basis(fields, money.get('deal_type', 'payment')))
    _set_cell(doc.tables[2].rows[0].cells[-1], 'ИТОГО К ОПЛАТЕ / AMOUNT DUE\n' +
              doc_routes.amount(money.get('total_payin'), money['payin_currency']))
    _set_field(doc.tables[3], 'Получатель платежа', money.get('payin_recipient') or '')
    _set_field(doc.tables[3], 'Реквизиты', doc_routes.details(money))
    _set_field(doc.tables[3], 'Способ оплаты', doc_routes.METHODS[money['payin_method']])
    _set_field(doc.tables[3], 'Назначение платежа', money.get('payment_reference') or
               payment_reference(fields, money['payin_method']))
    row = doc.tables[3].rows[-1]
    role = money.get('payin_recipient_role') or ''
    _set_cell(row.cells[0], f'Роль получателя / Recipient role: {role}\n'
              'Оплата указанному получателю по реквизитам настоящего счёта является надлежащим исполнением обязательства Клиента перед MF Corporation Company Limited по указанной операции.\n'
              'Payment to the named recipient using the details in this Invoice constitutes due performance of the Client’s obligation to MF Corporation Company Limited for this transaction.\n'
              + PAYIN_EVIDENCE[money['payin_method']] + ': направить менеджеру MF / send to the MF manager.')
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()



# ─────────────────────────── docx → PDF ───────────────────────────

SOFFICE_CANDIDATES = (
    '/Applications/LibreOffice.app/Contents/MacOS/soffice',   # macOS
    '/usr/bin/soffice', '/usr/bin/libreoffice',                # Debian/Ubuntu
    # у пакетов -nogui симлинка в /usr/bin может не быть — бинарник лежит здесь
    '/usr/lib/libreoffice/program/soffice',
    '/usr/lib/libreoffice/program/soffice.bin',
    'soffice', 'libreoffice',                                  # из PATH
)


def soffice_path() -> str | None:
    """Путь к LibreOffice или None, если его нет в окружении."""
    import shutil  # noqa: PLC0415

    override = os.environ.get('SOFFICE_PATH')
    if override and (os.path.exists(override) or shutil.which(override)):
        return override
    for candidate in SOFFICE_CANDIDATES:
        if os.path.isabs(candidate):
            if os.path.exists(candidate):
                return candidate
        elif shutil.which(candidate):
            return shutil.which(candidate)
    return None


def to_pdf(docx_bytes: bytes, timeout: int = 120) -> bytes | None:
    """DOCX → PDF через LibreOffice. None, если конвертер недоступен.

    Каждому вызову — свой профиль пользователя (`-env:UserInstallation`):
    без него параллельные запуски soffice дерутся за общий профиль в HOME
    и второй молча завершается, ничего не создав.
    """
    import subprocess  # noqa: PLC0415
    import tempfile  # noqa: PLC0415

    binary = soffice_path()
    if not binary:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, 'doc.docx')
        with open(src, 'wb') as fh:
            fh.write(docx_bytes)
        profile = os.path.join(tmp, 'profile')
        cmd = [binary, f'-env:UserInstallation=file://{profile}', '--headless',
               '--norestore', '--convert-to', 'pdf', '--outdir', tmp, src]
        try:
            subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
        except (subprocess.TimeoutExpired, OSError):
            return None
        out = os.path.join(tmp, 'doc.pdf')
        if not os.path.exists(out):
            return None
        with open(out, 'rb') as fh:
            data = fh.read()
    return data or None


PDF_MIME = 'application/pdf'
DOCX_MIME = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'


def as_pdf(docx_bytes: bytes, basename: str) -> tuple[bytes, str, str]:
    """→ (байты, имя файла, mime). PDF, а при отсутствии конвертера — DOCX.

    Клиенту уходит PDF: его нельзя случайно поправить и он одинаково
    открывается на телефоне. DOCX остаётся аварийным вариантом, чтобы
    отсутствие LibreOffice не блокировало выпуск документов.
    """
    pdf = to_pdf(docx_bytes)
    if pdf:
        return pdf, f'{basename}.pdf', PDF_MIME
    return docx_bytes, f'{basename}.docx', DOCX_MIME


# ─────────────────────── проверка перед выдачей ───────────────────────

PLACEHOLDER_RE = re.compile(r'\[●\]|\[[^\]\n]{2,80}?\s/\s[^\]\n]{2,80}?\]')


def check(data: bytes, allow_forms: bool = False) -> list[str]:
    """Аналог check_doc.py: не отдаём документ с незаполненными местами.

    `allow_forms` — для рамочного договора: приложения в нём намеренно пустые
    бланки, плейсхолдеры там не дефект. В допнике и инвойсе — дефект всегда.
    """
    from docx import Document  # noqa: PLC0415

    doc = Document(io.BytesIO(data))
    problems = []
    texts = [p.text for p in doc.paragraphs]
    body_only = allow_forms and len(doc.tables) > 1
    for idx, t in enumerate(doc.tables):
        if body_only and idx > 0:
            continue          # таблицы 1 и 2 — бланки приложений
        for row in t.rows:
            for cell in row.cells:
                texts.append(cell.text)
    for txt in texts:
        if txt.strip() == 'ОБЕЗЛИЧЕННЫЙ ШАБЛОН':
            problems.append('осталась пометка «ОБЕЗЛИЧЕННЫЙ ШАБЛОН»')
        for m in PLACEHOLDER_RE.findall(txt):
            problems.append(f'незаполненный плейсхолдер: {m}')
    seen, out = set(), []
    for p in problems:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out
