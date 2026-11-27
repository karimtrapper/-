"""Чистый разбор назначения поступления Сбера без загрузки приложения."""

import re


_ACQ_FEE_RE = re.compile(r'Комиссия\s+([0-9][0-9\s ]*(?:[.,]\d{1,2})?)', re.IGNORECASE)
_ACQ_MERCHANT_RE = re.compile(r'Мерчант\s*№\s*(\d+)')


def parse_sber_acquiring(purpose):
    """Разбор назначения прихода Сбера: эквайринг (СБП) или перевод по реквизитам.

    В выписку приходят оба потока, и в пуле они были неразличимы. Отличие —
    в назначении: у СБП-платежа (ссылка WL-бота → QR НСПК) банк пишет
    «Зачисление средств по операциям эквайринга. Мерчант №781003872118.
    Комиссия 700.00.», плательщик — «Московский банк Сбербанка России».
    У перевода по реквизитам плательщик — ФИО клиента, назначение произвольное.

    Главное: эквайринг зачисляется УЖЕ ЗА ВЫЧЕТОМ комиссии, а клиент заплатил
    больше — 99 300 ₽ на счёте при 100 000 ₽ от клиента. В сделку должен идти
    gross = зачислено + комиссия, иначе курс клиента и объём занижены.
    Ставку не хардкодим: у разных мерчантов она разная (видели 0.7% и 2.4%).
    """
    text_ = purpose or ''
    low = text_.lower()
    if 'эквайринг' not in low and 'мерчант' not in low:
        return {'kind': 'transfer', 'merchant': None, 'fee_rub': 0.0,
                'fee_known': True}
    fee = 0.0
    m = _ACQ_FEE_RE.search(text_)
    fee_known = bool(m)
    if m:
        raw = m.group(1).replace(' ', '').replace(' ', '').replace(',', '.')
        try:
            fee = float(raw)
        except ValueError:
            fee = 0.0
            fee_known = False
    mer = _ACQ_MERCHANT_RE.search(text_)
    return {'kind': 'acquiring', 'merchant': mer.group(1) if mer else None,
            'fee_rub': fee, 'fee_known': fee_known}
