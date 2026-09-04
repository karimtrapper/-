# -*- coding: utf-8 -*-
"""Распознавание документов клиента через OpenRouter.

Вход: загранпаспорт, инвойс застройщика/арендодателя, договор с застройщиком.
Выход: поля для генератора договоров + список замаскированных полей + провенанс
(из какого файла взято значение), чтобы менеджер видел, что подтверждает.

Модель выбрана замером 04.09.2026 на обезличенном пакете (см. wiki
`crm-doc-generator-fields.md`): gemini-2.5-flash — 3.7 с и $0.0013 на документ,
единственная вместе с gpt-4.1-mini, кто не путает российский БИК с полем SWIFT.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re

DEFAULT_MODEL = os.environ.get('DOCPARSE_MODEL', 'google/gemini-2.5-flash')
# Запасные — если основная не ответила. gpt-5-nano намеренно исключён: на замере
# исказил юрнаименование («ЭМ ЭФ КОРПОРАЦИЯ» вместо «ЭМ ЭФ КОРПОРЕЙШН»).
FALLBACK_MODELS = ['openai/gpt-4.1-mini', 'google/gemini-2.5-flash-lite']
OPENROUTER_URL = 'https://openrouter.ai/api/v1/chat/completions'

# Поля, которые вынимаем из файлов. Всё остальное в договоре — константы MF Corp,
# ввод менеджера, дефолты или вычисление системой (карта полей в вики).
FIELD_DEFS = {
    'client_name_ru':      'ФИО клиента кириллицей, как в паспорте',
    'client_name_en':      'ФИО клиента латиницей, как в машиночитаемой зоне паспорта',
    'client_citizenship':  'гражданство клиента',
    'client_passport_no':  'номер паспорта вместе с серией, как напечатано',
    'client_passport_issued_by':   'орган, выдавший паспорт',
    'client_passport_issue_date':  'дата выдачи паспорта, ДД.ММ.ГГГГ',
    'client_passport_expiry_date': 'дата окончания действия паспорта, ДД.ММ.ГГГГ',
    'client_birth_date':   'дата рождения, ДД.ММ.ГГГГ',
    'client_national_id':  'национальный идентификатор: ЕГН, ИИН, personal No.',
    'invoice_no':          'номер инвойса застройщика или арендодателя',
    'invoice_date':        'дата инвойса, ДД.ММ.ГГГГ',
    'invoice_amount':      'сумма обязательства по инвойсу, только число',
    'invoice_currency':    'валюта обязательства: THB, USD, RUB',
    'project_name':        'название проекта или жилого комплекса',
    'unit_no':             'номер юнита, виллы, участка или дома',
    'property_address':    'адрес объекта',
    'recipient_name':      'полное юридическое наименование получателя платежа',
    'recipient_bank':      'наименование банка получателя',
    'recipient_account':   'номер счёта получателя',
    'recipient_swift':     'ТОЛЬКО SWIFT/BIC международного формата — 8 или 11 латинских букв и цифр. '
                           'Российский БИК из 9 цифр сюда НЕ писать',
    'recipient_bik':       'российский БИК, ровно 9 цифр',
    'recipient_bank_address': 'адрес банка получателя',
    'lease_term':          'срок leasehold или аренды',
    'lease_start_date':    'дата начала leasehold или аренды, ДД.ММ.ГГГГ',
    'rent_amount':         'размер арендной платы за период',
    'deposit_amount':      'размер депозита',
    'contract_ref':        'реквизиты договора-основания: номер и дата',
}

# Менеджер грузит документы по отдельности — мы знаем, что это за файл.
# Подсказка типа заметно поднимает качество и снимает конфликты: ФИО берём
# из паспорта, реквизиты получателя — из инвойса, срок leasehold — из SPA.
DOC_KINDS = {
    'passport': 'Это скан загранпаспорта клиента.',
    'invoice':  'Это инвойс застройщика или арендодателя.',
    'spa':      'Это договор с застройщиком (SPA / Reservation / Lease Agreement).',
}
# Какой документ — источник истины для какого поля. Значение из «своего»
# документа побеждает, даже если другой файл распознался раньше.
FIELD_OWNER = {
    'passport': ['client_name_ru', 'client_name_en', 'client_citizenship',
                 'client_passport_no', 'client_passport_issued_by',
                 'client_passport_issue_date', 'client_passport_expiry_date',
                 'client_birth_date', 'client_national_id'],
    'invoice': ['invoice_no', 'invoice_date', 'invoice_amount', 'invoice_currency',
                'recipient_name', 'recipient_bank', 'recipient_account',
                'recipient_swift', 'recipient_bik', 'recipient_bank_address'],
    'spa': ['lease_term', 'lease_start_date', 'contract_ref', 'rent_amount',
            'deposit_amount', 'project_name', 'unit_no', 'property_address'],
}

PROMPT = (
    'Ты извлекаешь данные из документа для оформления агентского договора на оплату '
    'недвижимости в Таиланде. Верни JSON строго по схеме.\n'
    'ПРАВИЛА:\n'
    '1. Значения переписывай ДОСЛОВНО как в документе. Не переводи, не сокращай, '
    'не исправляй юридические наименования.\n'
    '2. Если значения в документе нет — верни null. НИЧЕГО НЕ ДОДУМЫВАЙ.\n'
    '3. Если значение замаскировано (XXX, ___, [●], placeholder, звёздочки) — верни null '
    'и добавь имя поля в masked_fields.\n'
    '4. Числа возвращай без пробелов-разделителей: 16550000.00\n'
    '5. Даты — в формате ДД.ММ.ГГГГ.'
)


def _schema() -> dict:
    props = {k: {'type': ['string', 'null'], 'description': v} for k, v in FIELD_DEFS.items()}
    props['doc_kind'] = {'type': ['string', 'null'],
                         'description': 'passport | developer_invoice | developer_contract | '
                                        'lease_agreement | other'}
    props['masked_fields'] = {'type': 'array', 'items': {'type': 'string'},
                              'description': 'поля, значение которых в документе замаскировано'}
    return {
        'type': 'object',
        'properties': props,
        # OpenAI в strict-режиме требует ВСЕ свойства в required, иначе HTTP 400
        # «Invalid schema for response_format». У gemini такого требования нет,
        # но перечисляем всегда — так схема работает у обоих.
        'required': list(props.keys()),
        'additionalProperties': False,
    }


def pages_to_png(data: bytes, mime: str, max_pages: int = 3, dpi: int = 150) -> list[bytes]:
    """PDF → PNG постранично. Картинка возвращается как есть."""
    if 'pdf' not in (mime or '').lower() and not data[:5].startswith(b'%PDF'):
        return [data]
    import pymupdf  # noqa: PLC0415 — тяжёлый импорт, только для PDF
    out = []
    with pymupdf.open(stream=data, filetype='pdf') as doc:
        for page in list(doc)[:max_pages]:
            out.append(page.get_pixmap(dpi=dpi).tobytes('png'))
    return out


def _call(model: str, images: list[bytes], api_key: str, timeout: int = 180,
          kind: str | None = None) -> dict:
    from openai import OpenAI  # noqa: PLC0415

    client = OpenAI(base_url='https://openrouter.ai/api/v1', api_key=api_key, timeout=timeout)
    prompt = PROMPT
    if kind in DOC_KINDS:
        prompt = f'{DOC_KINDS[kind]}\n{PROMPT}'
    content = [{'type': 'text', 'text': prompt}]
    for img in images:
        b64 = base64.b64encode(img).decode()
        content.append({'type': 'image_url',
                        'image_url': {'url': 'data:image/png;base64,' + b64}})
    resp = client.chat.completions.create(
        model=model,
        messages=[{'role': 'user', 'content': content}],
        response_format={'type': 'json_schema',
                         'json_schema': {'name': 'doc', 'strict': True, 'schema': _schema()}},
        # Reasoning-модели тратят на рассуждение 5–8 тыс. токенов и при малом лимите
        # возвращают content=null — это выглядит как поломка. Держим запас.
        max_tokens=20000,
        temperature=0,
    )
    raw = resp.choices[0].message.content
    if not raw:
        raise RuntimeError(f'{model}: пустой ответ (упёрлись в лимит вывода)')
    return json.loads(raw)


# Поля, где ЗАГЛАВНЫЕ буквы — нормальное значение, а не заглушка из макета
UPPERCASE_OK = {'invoice_currency', 'recipient_swift', 'recipient_bik'}
NULLISH = {'null', 'none', 'n/a', 'na', '-', '—', 'нет', 'не указано'}
# Слова, из которых состоят подписи полей в макетах: «CLIENT FULL NAME»,
# «PASSPORT NO.», «FIXED RATE». Ловим заглушку только если ВСЕ слова отсюда —
# иначе постфильтр съедал настоящие значения вроде «INV-1» и «BBB1-2026019».
LABEL_WORDS = {
    'CLIENT', 'FULL', 'NAME', 'LEGAL', 'PASSPORT', 'NO', 'NUMBER', 'CITIZENSHIP',
    'NATIONALITY', 'DATE', 'DATES', 'BIRTH', 'ISSUE', 'ISSUED', 'EXPIRY', 'VALID',
    'FIXED', 'RATE', 'EXCHANGE', 'AMOUNT', 'TOTAL', 'SUM', 'INSTALLMENT', 'PAYMENT',
    'ADDRESS', 'BANK', 'ACCOUNT', 'SWIFT', 'CODE', 'BIC', 'INVOICE', 'CONTRACT',
    'AGREEMENT', 'PROJECT', 'UNIT', 'PROPERTY', 'RECIPIENT', 'CURRENCY', 'FEE',
    'SIGNATORY', 'AUTHORISED', 'REGISTRATION', 'ID', 'EMAIL', 'PHONE', 'TERM',
    'START', 'DEPOSIT', 'RENT', 'RENTAL', 'PURPOSE', 'DETAILS', 'REFERENCE',
    'LEASE', 'LEASEHOLD', 'SELLER', 'BUYER', 'DEVELOPER', 'LESSOR', 'PERIOD',
    'IF', 'APPLICABLE', 'OR', 'AND', 'OF', 'THE', 'TO', 'FOR', 'ST', 'ND', 'RD', 'TH',
}


def _is_label_text(value: str) -> bool:
    """Строка целиком собрана из слов-ярлыков макета и написана капсом."""
    words = [w for w in re.split(r'[^A-Za-z]+', value) if w]
    if not words or not all(w.isupper() for w in words):
        return False
    return all(w in LABEL_WORDS for w in words)


def is_placeholder(key: str, value) -> bool:
    """Значение — заглушка макета, а не данные.

    Модели возвращают текст рамки («CLIENT FULL NAME», «[DATE]», «MF-XXX-XXXX»)
    как будто это значение. Ловим до того, как оно попадёт в договор.
    """
    if not isinstance(value, str):
        return value is None
    v = value.strip()
    if not v or v.lower() in NULLISH:
        return True
    if 'XXX' in v or '___' in v or '●' in v:
        return True
    # рамка макета внутри строки: «[PROJECT / UNIT No.]», «1 USD = [FIXED RATE] RUB».
    # Квадратные скобки в настоящих реквизитах не встречаются.
    if re.search(r'\[[^\]]{1,60}\]', v):
        return True
    core = v.strip('[]<>()').strip()
    if not core:
        return True
    if core != v and not any(c.islower() for c in core):
        return True          # значение в скобках вида [DATE]
    if key in UPPERCASE_OK:
        return False
    return _is_label_text(core)


# В паспорте ФИО и гражданство напечатаны капсом. В договор это идёт как есть
# и читается как крик: «БУРОВА НАДЕЖДА ВАСИЛЬЕВНА, гражданин РОССИЙСКАЯ ФЕДЕРАЦИЯ».
CAPS_FIELDS = {'client_name_ru', 'client_name_en', 'client_citizenship',
               'client_passport_issued_by', 'recipient_name', 'recipient_bank',
               'project_name', 'property_address', 'recipient_bank_address'}
# Частицы фамилий и служебные слова, которые с заглавной не пишутся
LOWER_PARTICLES = {'де', 'ди', 'дю', 'ла', 'ле', 'фон', 'ван', 'дер', 'оглы', 'кызы',
                   'de', 'di', 'du', 'la', 'le', 'van', 'von', 'der', 'the', 'of', 'and'}


def _titlecase(text: str) -> str:
    out = []
    for i, word in enumerate(text.split(' ')):
        if not word:
            out.append(word)
            continue
        low = word.lower()
        if i and low.strip('.,') in LOWER_PARTICLES:
            out.append(low)
            continue
        # дефисные части пишутся с заглавной каждая: Салтыков-Щедрин
        out.append('-'.join(p[:1].upper() + p[1:].lower() if p else p for p in low.split('-')))
    return ' '.join(out)


def normalize(key: str, value):
    """Капс из паспорта → нормальный регистр. Аббревиатуры не трогаем."""
    if not isinstance(value, str) or key not in CAPS_FIELDS:
        return value
    v = value.strip()
    letters = [c for c in v if c.isalpha()]
    if not letters or not all(c.isupper() for c in letters):
        return v
    if len(letters) <= 4:
        return v          # ООО, THB, SWIFT-коды — оставляем как есть
    return _titlecase(v)


def parse_file(filename: str, data: bytes, mime: str, api_key: str,
               model: str | None = None, kind: str | None = None) -> dict:
    """Один файл → распознанные поля. При отказе модели пробуем запасные."""
    images = pages_to_png(data, mime)
    errors = []
    for m in [model or DEFAULT_MODEL] + FALLBACK_MODELS:
        try:
            res = _call(m, images, api_key, kind=kind)
            res['_model'] = m
            res['_file'] = filename
            res['_kind'] = kind
            return res
        except Exception as exc:  # noqa: BLE001 — падать нельзя, пробуем следующую
            errors.append(f'{m}: {exc}')
    raise RuntimeError('все модели отказали — ' + ' | '.join(errors))


def merge(results: list[dict]) -> dict:
    """Склейка нескольких файлов в один набор полей.

    Менеджер грузит документы по отдельности, поэтому у каждого поля есть
    документ-владелец: ФИО — паспорт, реквизиты получателя — инвойс, срок
    leasehold — SPA. Значение из «своего» документа побеждает независимо от
    порядка загрузки; из чужого берётся только чтобы закрыть пустоту.
    Разногласие между двумя равноправными источниками не затираем молча —
    складываем в `conflicts`, менеджер разрешает руками.
    """
    fields, provenance, conflicts, masked, slots = {}, {}, {}, set(), {}
    owned_by = {}
    for kind, keys in FIELD_OWNER.items():
        for key in keys:
            owned_by[key] = kind

    for res in results:
        src = res.get('_file') or '?'
        kind = res.get('_kind')
        for key in FIELD_DEFS:
            val = res.get(key)
            if is_placeholder(key, val):
                if val:
                    masked.add(key)
                continue
            val = normalize(key, val.strip()) if isinstance(val, str) else val
            is_owner = owned_by.get(key) == kind
            if key not in fields:
                fields[key], provenance[key] = val, src
                if kind:
                    slots[key] = kind
                if is_owner:
                    provenance[key + '__owner'] = True
                continue
            if fields[key] == val:
                continue
            if is_owner and not provenance.get(key + '__owner'):
                # приехал документ-владелец — он и есть источник истины
                fields[key], provenance[key] = val, src
                provenance[key + '__owner'] = True
                if kind:
                    slots[key] = kind
                conflicts.pop(key, None)
            elif provenance.get(key + '__owner') and not is_owner:
                pass          # владелец уже дал значение, чужое игнорируем
            else:
                conflicts.setdefault(key, [{'value': fields[key], 'file': provenance[key]}])
                conflicts[key].append({'value': val, 'file': src})
        for mf in res.get('masked_fields') or []:
            masked.add(mf)

    provenance = {k: v for k, v in provenance.items() if not k.endswith('__owner')}
    return {
        'fields': fields,
        'provenance': provenance,
        'slots': slots,
        'conflicts': conflicts,
        'masked_fields': sorted(masked),
        'models': [r.get('_model') for r in results],
    }


def validate(fields: dict) -> list[str]:
    """Постпроверка форматов — модели путают SWIFT с БИК (замер 04.09)."""
    problems = []
    swift = (fields.get('recipient_swift') or '').strip()
    if swift:
        compact = swift.replace(' ', '')
        if compact.isdigit():
            problems.append(f'В поле SWIFT стоит число «{swift}» — похоже на российский БИК, '
                            'перенесите в поле БИК')
        elif len(compact) not in (8, 11):
            problems.append(f'SWIFT «{swift}» не 8 и не 11 символов — проверьте')
    bik = (fields.get('recipient_bik') or '').strip().replace(' ', '')
    if bik and (not bik.isdigit() or len(bik) != 9):
        problems.append(f'БИК «{bik}» должен быть ровно из 9 цифр')
    return problems
