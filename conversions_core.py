"""Расчётное ядро конвертаций: доли USDT, матчинг WL-сделок, разбор даты.

Здесь только чистые функции — ни Flask, ни БД, ни сети. Это позволяет держать
формулы в одном коротком файле и проверять их без поднятия приложения:
в app.py они лежали россыпью между строками 2400 и 5800, и одна и та же
формула успела разойтись по четырём местам.

Правило: если функция ходит в базу или в сеть — ей здесь не место.
"""
from datetime import date, datetime


def conversion_shares(sources, received_usdt):
    """Разнести полученный USDT по поступлениям пропорционально рублям.

    U_i = R × доля_i / G. Пропорция сама размазывает и удержание, и расхождение
    с брокером (Δ), и всегда даёт Σ U_i = R — то есть один приход физически
    не может быть учтён дважды, как это случилось с хешем 2783…494.

    sources — [(sber_income_id, amount_rub)], возвращает {sber_income_id: usdt}.
    """
    if not sources:
        return {}
    total_rub = round(sum(a or 0 for _, a in sources), 2)
    if total_rub <= 0:
        return {sid: 0.0 for sid, _ in sources}
    got = received_usdt or 0
    shares = {sid: round(got * (amt or 0) / total_rub, 2) for sid, amt in sources}
    # Хвост округления добираем в наибольшую долю: иначе Σ долей меньше перевода
    # на копейки, PayinTx.free_usdt() не обнуляется и хеш висит «частично
    # свободным» — тот самый след, который прятал перевод из выбора.
    tail = round(got - sum(shares.values()), 4)
    if tail and shares:
        biggest = max(shares, key=lambda k: shares[k])
        shares[biggest] = round(shares[biggest] + tail, 4)
    return shares


def match_wl_deal(income, wl_deals, day_window=2):
    """Найти WL-сделку обменника, породившую этот приход на счёт.

    Клиент мерчанта платит по ссылке WL-бота → QR НСПК → эквайринг Сбера, и на
    счёт падает сумма за вычетом комиссии. В реестре бота сумма хранится как
    gross, поэтому сопоставляем именно с `gross_rub` прихода.

    Матчим только однозначно: две сделки на ту же сумму в те же дни — не гадаем,
    иначе припишем приход чужому мерчанту и сломаем расчёт выплат.
    Возвращает dict сделки либо None.
    """
    gross = round(income.get('gross_rub') or 0, 2)
    if gross <= 0:
        return None
    raw_date = (income.get('operation_date') or '')[:10]
    try:
        inc_date = datetime.strptime(raw_date, '%Y-%m-%d').date()
    except ValueError:
        return None
    hits = []
    for d in wl_deals or []:
        if abs(round(float(d.get('rub') or 0), 2) - gross) > 1.0:
            continue
        # dt в снапшоте — «17.08 14:20», без года: берём год прихода
        dt = str(d.get('dt') or '')[:5]
        try:
            day, month = int(dt[:2]), int(dt[3:5])
            wl_date = date(inc_date.year, month, day)
        except (ValueError, TypeError):
            continue
        if abs((wl_date - inc_date).days) <= day_window:
            hits.append(d)
    return hits[0] if len(hits) == 1 else None


def parse_sent_at(value):
    """Дата отправки брокеру. Пачку заводят задним числом, поэтому дата создания
    не годится: платёж мог уйти позавчера, а сводка должна называть его день.

    Принимаем 'ГГГГ-ММ-ДД' (или ISO), True — «сегодня», пусто — черновик.
    """
    if value is None or value is False or value == '':
        return None
    if value is True:
        return datetime.utcnow()
    if isinstance(value, datetime):
        return datetime.combine(value.date(), datetime.min.time())
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    if not isinstance(value, str):
        raise ValueError('Дата отправки должна быть строкой ГГГГ-ММ-ДД или true')
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError('Некорректная дата отправки: требуется ГГГГ-ММ-ДД или ISO')
    return datetime.combine(parsed.date(), datetime.min.time())
