# -*- coding: utf-8 -*-
"""Автоинструкция и счёт Flow Sole в форме согласованных двуязычных образцов.

Все значения берутся из текущей сделки. Процент вознаграждения не выводится
из итогового курса клиента: отдельного согласованного поля пока нет.
"""
from __future__ import annotations

import io
from datetime import datetime

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt, RGBColor
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

import doc_routes


GRAY = 'E8E8E8'


def _text(value):
    return str(value or '').strip()


def _amount(value, currency):
    return doc_routes.amount(value, currency)


def _style(doc):
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Inches(8.5), Inches(11)
    sec.top_margin = sec.bottom_margin = Inches(.58)
    sec.left_margin = sec.right_margin = Inches(.67)
    sec.header_distance = Inches(.25)
    st = doc.styles['Normal']
    st.font.name, st.font.size = 'Times New Roman', Pt(8.5)
    st.font.color.rgb = RGBColor(0, 0, 0)
    st.paragraph_format.space_after = Pt(3)
    st.paragraph_format.line_spacing = 1.05


def _set_cell(cell, text, bold=False):
    cell.text = ''
    p = cell.paragraphs[0]
    p.paragraph_format.space_after = Pt(2)
    r = p.add_run(_text(text))
    r.bold = bold
    r.font.name = 'Times New Roman'
    r.font.size = Pt(8.2)
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.TOP
    return p


def _shade(cell):
    shd = OxmlElement('w:shd')
    shd.set(qn('w:fill'), GRAY)
    cell._tc.get_or_add_tcPr().append(shd)


def _block(doc, heading_ru, heading_en, text_ru, text_en):
    t = doc.add_table(rows=2, cols=2)
    t.autofit = False
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for row in t.rows:
        row.cells[0].width = row.cells[1].width = Inches(3.55)
    for i, h in enumerate((heading_ru, heading_en)):
        _shade(t.rows[0].cells[i])
        _set_cell(t.rows[0].cells[i], h, True)
    _set_cell(t.rows[1].cells[0], text_ru)
    _set_cell(t.rows[1].cells[1], text_en)
    doc.add_paragraph().paragraph_format.space_after = Pt(0)
    return t


def _header(doc, agent):
    h = doc.sections[0].header
    t = h.add_table(rows=1, cols=2, width=Inches(7.1))
    t.autofit = False
    t.cell(0, 0).width = Inches(3.1)
    t.cell(0, 1).width = Inches(4.0)
    p = t.cell(0, 0).paragraphs[0]
    p.add_run().add_picture(agent.logo_path, width=Inches(1.55))
    p = t.cell(0, 1).paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    p.add_run(agent.name).bold = True
    p.add_run('\n' + agent.address + '\nTel.: ' + agent.phone)
    for r in p.runs:
        r.font.name = 'Times New Roman'
        r.font.size = Pt(8)


def _title(doc, ru, en, subtitle, when):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(15)
    p.paragraph_format.space_after = Pt(2)
    r = p.add_run(ru + '\n' + en)
    r.bold, r.font.size = True, Pt(12)
    p = doc.add_paragraph(subtitle + f'\n{when:%d.%m.%Y}')
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(8)


def _signature(doc, agent, when, client):
    p = doc.add_paragraph('ПОДПИСИ СТОРОН / SIGNATURES OF THE PARTIES')
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.runs[0].bold = True
    t = doc.add_table(rows=1, cols=2)
    t.autofit = False
    for c in t.rows[0].cells:
        c.width = Inches(3.55)
    left, right = t.rows[0].cells
    _set_cell(left, f'КЛИЕНТ / CLIENT\n{client}\n\nПодпись / Signature: ____________________')
    _set_cell(right, f'АГЕНТ / AGENT\n{agent.name}\nDirector: {agent.director}')
    p = right.add_paragraph()
    p.paragraph_format.space_after = Pt(0)
    p.add_run().add_picture(agent.signature_path, width=Inches(agent.signature_width_in))
    right.add_paragraph(f'Подпись / Signature:      {when:%d.%m.%Y}')
    right.add_paragraph().add_run().add_picture(agent.stamp_path, width=Inches(agent.stamp_width_in))


def _vehicle(fields):
    model = _text(fields.get('vehicle_model'))
    vin = _text(fields.get('vehicle_vin'))
    if not vin and fields.get('vehicle_vin_state') == 'pending':
        basis = _text(fields.get('vehicle_vin_pending_basis'))
        vin = 'ещё не присвоен / pending' + (f' ({basis})' if basis else '')
    return ', '.join(x for x in (model, ('VIN ' + vin if vin else '')) if x)


def _basis(fields, lang='ru'):
    contract = _text(fields.get('vehicle_contract_no'))
    date = _text(fields.get('vehicle_contract_date'))
    invoice = _text(fields.get('invoice_no'))
    inv_date = _text(fields.get('invoice_date'))
    no = '№' if lang == 'ru' else 'No.'
    dated = 'от' if lang == 'ru' else 'dated'
    return (f'Sales Contract {no} {contract}' + (f' {dated} {date}' if date else '')
            + (f'; Proforma Invoice {no} {invoice}' if invoice else '')
            + (f' {dated} {inv_date}' if inv_date else ''))


def build_instruction(fields: dict, money: dict, number: str, parent_number: str,
                      when: datetime, agent) -> bytes:
    """Платёжная инструкция по авто с данными конкретной сделки."""
    doc = Document()
    _style(doc)
    _header(doc, agent)
    _title(doc, f'ПЛАТЁЖНАЯ ИНСТРУКЦИЯ № {number}', f'PAYMENT INSTRUCTION NO. {number}',
           f'к Агентскому договору № {parent_number} / under Agency Agreement No. {parent_number}', when)
    client = _text(fields.get('client_name_ru') or fields.get('client_name_en'))
    client_en = _text(fields.get('client_name_en') or fields.get('client_name_ru'))
    passport = _text(fields.get('client_passport_no'))
    basis = _basis(fields)
    basis_en = _basis(fields, 'en')
    _block(doc, '1. СТОРОНЫ И ОСНОВАНИЕ', '1. PARTIES AND BASIS',
           f'Клиент: {client}, паспорт № {passport}.\nАгент: {agent.name}.\nОснование платежа: {basis}.',
           f'Client: {client_en}, passport No. {passport}.\nAgent: {agent.name}.\nUnderlying basis: {basis_en}.')
    seller = _text(fields.get('recipient_name') or fields.get('seller_name'))
    bank = _text(fields.get('recipient_bank'))
    account = _text(fields.get('recipient_account'))
    swift = _text(fields.get('recipient_swift'))
    recipient = '\n'.join(x for x in (
        f'Получатель: {seller}',
        f'Регистрационный код: {_text(fields.get("seller_id"))}' if fields.get('seller_id') else '',
        f'Адрес: {_text(fields.get("seller_address"))}' if fields.get('seller_address') else '',
        f'Банк: {bank}' if bank else '',
        f'Счёт: {account}' if account else '',
        f'SWIFT: {swift}' if swift else '') if x)
    recipient_en = '\n'.join(x for x in (
        f'Beneficiary: {seller}',
        f'Registration code: {_text(fields.get("seller_id"))}' if fields.get('seller_id') else '',
        f'Address: {_text(fields.get("seller_address"))}' if fields.get('seller_address') else '',
        f'Bank: {bank}' if bank else '',
        f'Account: {account}' if account else '',
        f'SWIFT: {swift}' if swift else '') if x)
    stage = {'advance': 'аванс / advance', 'balance': 'остаток / balance',
             'full': 'полная оплата / full payment'}.get(fields.get('vehicle_payment_stage'), '')
    _block(doc, '2. ПРЕДМЕТ ИНСТРУКЦИИ', '2. INSTRUCTION DETAILS',
           f'Покупка транспортного средства. Этап: {stage}.\n'
           f'Сумма перевода продавцу: {_amount(money.get("transfer_amount"), "USD")}.\n'
           f'Документ-основание: {basis}.\n{recipient}',
           f'Vehicle purchase. Payment stage: {stage}.\n'
           f'Amount to be transferred to seller: {_amount(money.get("transfer_amount"), "USD")}.\n'
           f'Underlying documents: {basis_en}.\n{recipient_en}')
    vehicle = _vehicle(fields)
    details = _text(fields.get('vehicle_details'))
    _block(doc, '2.1. СПЕЦИФИКАЦИЯ АВТОМОБИЛЯ', '2.1. VEHICLE SPECIFICATION',
           vehicle + (f'\nХарактеристики: {details}' if details else ''),
           vehicle + (f'\nSpecification: {details}' if details else ''))
    doc.add_page_break()
    rate = _text(money.get('rate'))
    total = _amount(money.get('total_payin'), money.get('payin_currency') or 'RUB')
    transfer = _amount(money.get('transfer_amount'), 'USD')
    _block(doc, '3. РАСЧЁТ И ОПЛАТА КЛИЕНТА', '3. CLIENT PAYMENT AND CALCULATION',
           f'Расчётный курс клиента: 1 USD = {rate} RUB.\n'
           f'Продавцу: {transfer}.\nИтого к оплате Клиентом: {total}.\n'
           f'Вознаграждение Агента включено в итоговую сумму.\n'
           f'Клиент оплачивает сумму одним банковским переводом по реквизитам счёта № {number}.',
           f'Client exchange rate: 1 USD = {rate} RUB.\n'
           f'To the seller: {transfer}.\nTotal payable by the Client: {total}.\n'
           f'The Agent’s fee is included in the total amount.\n'
           f'The Client pays in one bank transfer under Invoice No. {number}.')
    _block(doc, '4. ПОДТВЕРЖДЕНИЕ', '4. CONFIRMATION',
           'Клиент подтверждает точность приведённых данных и поручает Агенту исполнить '
           'настоящую инструкцию после получения полной суммы, прохождения комплаенс-проверки '
           'и при доступности платёжного маршрута. Агент осуществляет платёж только по '
           'реквизитам получателя, '
           + ('указанным в настоящей инструкции. ' if account else
              'указанным в приложенном инвойсе получателя. ') +
           'Настоящая инструкция является Приложением 1 к Агентскому договору. '
           'При расхождении преимущественную силу имеет русский текст.',
           'The Client confirms the accuracy of the stated details and instructs the Agent '
           'to execute this instruction after receipt of the full amount, completion of '
           'compliance checks and availability of the payment route. The Agent shall make '
           'the payment only to the beneficiary details '
           + ('stated in this Instruction. ' if account else
              'stated in the attached beneficiary invoice. ') +
           'This Instruction forms Appendix 1 to the Agency Agreement. '
           'In case of discrepancy, the Russian text prevails.')
    _signature(doc, agent, when, client)
    buf = io.BytesIO(); doc.save(buf)
    return buf.getvalue()


def build_invoice(fields: dict, money: dict, number: str, parent_number: str,
                  when: datetime, agent) -> bytes:
    """Одностраничный счёт по авто без выдуманного деления комиссии."""
    doc = Document()
    _style(doc)
    _header(doc, agent)
    _title(doc, f'СЧЁТ № {number}', f'INVOICE NO. {number}',
           f'к Агентскому договору № {parent_number} / to Agency Agreement No. {parent_number}', when)
    client = _text(fields.get('client_name_ru') or fields.get('client_name_en'))
    client_en = _text(fields.get('client_name_en') or fields.get('client_name_ru'))
    _block(doc, 'ВЫСТАВЛЕН АГЕНТОМ / ISSUED BY AGENT', 'ВЫСТАВЛЕН КЛИЕНТУ / BILLED TO CLIENT',
           f'{agent.name}\nНалоговый номер: {agent.reg_no}\nАдрес: {agent.address}',
           f'{client_en}\nPassport No. {_text(fields.get("client_passport_no"))}\n'
           f'{_text(fields.get("client_address"))}')
    basis = _basis(fields)
    basis_en = _basis(fields, 'en')
    vehicle = _vehicle(fields)
    rate = _text(money.get('rate'))
    seller = _text(fields.get('seller_name'))
    _block(doc, 'ОСНОВАНИЕ И ОБЪЕКТ ОПЛАТЫ', 'BASIS AND SUBJECT OF PAYMENT',
           f'Payment Instruction № {number}; {basis}.\nПродавец: {seller}.\nАвтомобиль: {vehicle}.\n'
           f'Расчётный курс клиента: 1 USD = {rate} RUB.',
           f'Payment Instruction No. {number}; {basis_en}.\nSeller: {seller}.\nVehicle: {vehicle}.\n'
           f'Client exchange rate: 1 USD = {rate} RUB.')
    p = doc.add_paragraph('СОСТАВ СЧЁТА / INVOICE BREAKDOWN')
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER; p.runs[0].bold = True
    t = doc.add_table(rows=3, cols=2, style='Table Grid')
    t.autofit = False
    for row in t.rows:
        row.cells[0].width, row.cells[1].width = Inches(5.45), Inches(1.65)
    _shade(t.cell(0, 0)); _shade(t.cell(0, 1))
    _set_cell(t.cell(0, 0), 'Наименование / Description', True)
    _set_cell(t.cell(0, 1), 'Сумма / Amount', True)
    _set_cell(t.cell(1, 0), 'Оплата продавцу по Payment Instruction / Payment to seller under Payment Instruction')
    _set_cell(t.cell(1, 1), _amount(money.get('transfer_amount'), 'USD'))
    _set_cell(t.cell(2, 0), 'ИТОГО К ОПЛАТЕ / TOTAL PAYABLE\nВознаграждение Агента включено в сумму / Agent’s fee included in total', True)
    _set_cell(t.cell(2, 1), _amount(money.get('total_payin'), 'RUB'), True)
    doc.add_paragraph().paragraph_format.space_after = Pt(0)
    payin = _text(money.get('payin_details'))
    ref = _text(money.get('payment_reference'))
    _block(doc, 'РЕКВИЗИТЫ ДЛЯ ОПЛАТЫ В RUB', 'RUB PAYMENT DETAILS',
           f'Получатель: {_text(money.get("payin_recipient"))}\n{payin}\n'
           f'Назначение платежа: {ref}\nСчёт оплачивается одним банковским переводом.',
           f'Payee: {_text(money.get("payin_recipient"))}\n{payin}\n'
           f'Payment reference: {ref}\nThis invoice shall be paid in one bank transfer.')
    p = doc.add_paragraph(f'{agent.name}  ·  Director: {agent.director}')
    p.paragraph_format.space_after = Pt(0)
    t = doc.add_table(rows=1, cols=2)
    t.cell(0, 0).paragraphs[0].add_run().add_picture(agent.signature_path, width=Inches(agent.signature_width_in))
    t.cell(0, 1).paragraphs[0].add_run().add_picture(agent.stamp_path, width=Inches(agent.stamp_width_in))
    buf = io.BytesIO(); doc.save(buf)
    return buf.getvalue()
