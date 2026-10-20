"""Чистый разбор назначения поступления Сбера без загрузки приложения."""

import re


_ACQ_FEE_RE = re.compile(r'Комиссия\s+([0-9][0-9\s ]*(?:[.,]\d{1,2})?)', re.IGNORECASE)
_ACQ_MERCHANT_RE = re.compile(r'Мерчант\s*№\s*(\d+)')


def parse_sber_acquiring(purpose):
    """Определить эквайринг и комиссию из назначения прихода Сбера.

    У эквайринга сумма выписки уже уменьшена на комиссию. Для сделки нужна
    исходная сумма клиента, поэтому комиссия читается из текста банка.
    """
    text_ = purpose or ''
    low = text_.lower()
    if 'эквайринг' not in low and 'мерчант' not in low:
        return {'kind': 'transfer', 'merchant': None, 'fee_rub': 0.0, 'fee_known': True}
    fee = 0.0
    m = _ACQ_FEE_RE.search(text_)
    if m:
        raw = m.group(1).replace(' ', '').replace(' ', '').replace(',', '.')
        try:
            fee = float(raw)
        except ValueError:
            fee = 0.0
    mer = _ACQ_MERCHANT_RE.search(text_)
    return {'kind': 'acquiring', 'merchant': mer.group(1) if mer else None,
            'fee_rub': fee, 'fee_known': bool(m)}
