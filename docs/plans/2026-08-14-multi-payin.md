# Мульти-Pay-In — план реализации

> **Для агентов:** ОБЯЗАТЕЛЬНЫЙ СУБ-СКИЛЛ — `superpowers:subagent-driven-development`
> (рекомендуется) или `superpowers:executing-plans`. Шаги отмечаются чекбоксами `- [ ]`.

**Цель:** одна сделка принимает приход несколькими способами сразу (наличные партнёра +
реквизиты + крипта), менеджер вводит это одним экраном, прибыль и выплаты агентам
считаются один раз от итога.

**Спека:** [`docs/specs/2026-08-14-multi-payin.md`](../specs/2026-08-14-multi-payin.md) —
читать до начала работы, особенно §3 (модель) и §8 (выгрузка).

**Архитектура:** дополнительные приходы живут в новой JSON-колонке `deals.payin_extra`,
основной приход остаётся в плоских `payin_*`. При каждом сохранении плоские поля
пересчитываются в агрегаты (итог USDT, сумма рублей, средневзвешенный курс, метод
крупнейшей части), поэтому весь остальной код — прибыль, каскад агентов, возмещения,
Битрикс, DealCloser — читает те же поля, что и раньше, и не переписывается.

**Стек:** Python 3.12, Flask, SQLAlchemy 2, pytest. Фронт — один файл
`static/crm/crm.html` без фреймворков.

**Прогон тестов:** `cd Dev/CalcCRM && python -m pytest tests/ -q` (~3 мин, 708 тестов).
Пре-коммит хук гоняет весь сьют — на `git commit` закладывай 3–4 минуты.

---

## Карта файлов

| Файл | Что меняется |
|---|---|
| `app.py` | колонка `payin_extra` + миграция; хелперы нормализации/чтения/пересчёта; POST и PUT `/api/deals`; разбиение на строки; 3 TG-шаблона; 3 сборщика строк Sheet; поиск и удаление строк |
| `static/crm/crm.html` | блок частей в форме (кнопка «+ ещё приход», карточки, живая сводка); строки частей в карточке сделки |
| `tests/test_multi_payin.py` | **новый** — нормализация, агрегаты, API, разбиение, защита от двойного учёта |
| `tests/test_multi_payin_export.py` | **новый** — строки выгрузки по трём листам, поиск и удаление |
| `tests/test_multi_payin_telegram.py` | **новый** — блок «— Приход —» в трёх шаблонах |
| `.claude/docs/CLAUDE-calccrm.md` | changelog после мержа |
| `wiki/projects/calccrm.md` | changelog после мержа |

Разбиение тестов на три файла — по границе ответственности: модель и API, выгрузка,
уведомления. Каждый прогоняется отдельно и читается за раз.

---

## Task 1: Колонка `payin_extra`, миграция, `to_dict`

**Файлы:**
- Изменить: `app.py` — модель `Deal` (~строка 938, рядом с `payin_parts`), блок миграций
  (~строка 1786, рядом с миграцией `payin_tx_hashes`), `Deal.to_dict()` (~строка 1032)
- Тест: `tests/test_multi_payin.py` (создать)

- [ ] **Шаг 1: Написать падающий тест**

Создать `tests/test_multi_payin.py`:

```python
"""
Мульти-Pay-In: несколько способов прихода в одной сделке.
Спека: docs/specs/2026-08-14-multi-payin.md

Запуск: cd Dev/CalcCRM && python -m pytest tests/test_multi_payin.py -v
"""
import pytest
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ['SECRET_KEY'] = 'test-secret-key-for-pytest'

from app import app, get_session, Deal, Client, AdminUser, PayInMethod


@pytest.fixture(autouse=True)
def clean_db():
    s = get_session()
    try:
        s.query(Deal).delete()
        s.query(Client).delete()
        s.commit()
    finally:
        s.close()
    yield


@pytest.fixture
def db():
    s = get_session()
    yield s
    s.close()


def test_payin_extra_column_roundtrip(db):
    """Колонка есть, JSON сохраняется и читается через to_dict."""
    extra = [{'method': 'sber_reqs', 'amount_rub': 200000.0,
              'rate_rub_usdt': 84.5537, 'amount_usdt': 2365.362,
              'partner_name': None, 'tx_hashes': [], 'sber_uuids': [], 'note': ''}]
    d = Deal(client_name='T', payin_method=PayInMethod.PARTNERS_CASH,
             payin_extra=json.dumps(extra, ensure_ascii=False))
    db.add(d)
    db.commit()

    got = db.query(Deal).filter(Deal.id == d.id).first()
    assert json.loads(got.payin_extra)[0]['amount_usdt'] == 2365.362
    assert got.to_dict()['payin_extra'][0]['method'] == 'sber_reqs'


def test_payin_extra_defaults_to_none(db):
    """Сделка с одним каналом: колонка пустая, to_dict отдаёт None."""
    d = Deal(client_name='T', payin_method=PayInMethod.PARTNERS_CASH)
    db.add(d)
    db.commit()
    assert d.payin_extra is None
    assert d.to_dict()['payin_extra'] is None
```

- [ ] **Шаг 2: Убедиться, что тест падает**

Запуск: `cd Dev/CalcCRM && python -m pytest tests/test_multi_payin.py -v`
Ожидаемо: FAIL — `TypeError: 'payin_extra' is an invalid keyword argument for Deal`

- [ ] **Шаг 3: Добавить колонку в модель**

В `app.py` сразу после объявления `payin_parts` (~строка 938):

```python
    # Дополнительные приходы сверх основного: JSON-список
    # [{method, amount_rub, rate_rub_usdt, amount_usdt, partner_name,
    #   tx_hashes, sber_uuids, note}]
    # Основной приход остаётся в плоских payin_* — часть 1 это он. Плоские поля
    # после сохранения хранят АГРЕГАТЫ (итог USDT, сумма рублей, средневзвешенный
    # курс), поэтому весь остальной код читает их как раньше.
    payin_extra = Column(Text, nullable=True)
```

- [ ] **Шаг 4: Добавить миграцию**

В `app.py` сразу после блока миграции `payin_tx_hashes` (~строка 1793):

```python
# Дополнительные приходы: несколько способов Pay-In в одной сделке
try:
    with engine.connect() as conn:
        if 'postgresql' in DATABASE_URL:
            conn.execute(text("ALTER TABLE deals ADD COLUMN IF NOT EXISTS payin_extra TEXT"))
        else:
            try: conn.execute(text("ALTER TABLE deals ADD COLUMN payin_extra TEXT"))
            except: pass
        conn.commit()
except Exception as e:
    print(f"ℹ️ payin_extra migration: {e}")
```

- [ ] **Шаг 5: Добавить поле в `to_dict`**

В `Deal.to_dict()` рядом с `'payin_parts'` (~строка 1032):

```python
            'payin_extra': json.loads(self.payin_extra) if self.payin_extra else None,
```

- [ ] **Шаг 6: Прогнать тест**

Запуск: `python -m pytest tests/test_multi_payin.py -v`
Ожидаемо: 2 passed

- [ ] **Шаг 7: Коммит**

```bash
git add app.py tests/test_multi_payin.py
git commit -m "feat(multi-payin): колонка payin_extra + миграция"
```

---

## Task 2: Нормализация и чтение частей

**Файлы:**
- Изменить: `app.py` — рядом с `_normalize_tx_hashes` (~строка 4366)
- Тест: `tests/test_multi_payin.py`

- [ ] **Шаг 1: Написать падающие тесты**

Дописать в `tests/test_multi_payin.py` (импорт расширить):

```python
from app import (app, get_session, Deal, Client, AdminUser, PayInMethod,
                 _normalize_payin_extra, _payin_extra_list, _payin_all_parts)

H_EXTRA = 'cc11dd22ee33ff44aa55bb66cc77dd88ee99ff00aa11bb22cc33dd44ee55ff66'


def test_normalize_drops_parts_without_money():
    """Часть без суммы USDT ничего не описывает — выбрасываем."""
    out = _normalize_payin_extra([
        {'method': 'crypto_direct', 'amount_usdt': 500},
        {'method': 'crypto_direct'},
        {'method': 'crypto_direct', 'amount_usdt': 0},
        {'method': 'crypto_direct', 'amount_usdt': 'абв'},
        'мусор',
    ])
    assert len(out) == 1
    assert out[0]['amount_usdt'] == 500


def test_normalize_rejects_unknown_method():
    """Метода нет в PayInMethod — часть не сохраняем, иначе выгрузка упадёт на лейбле."""
    assert _normalize_payin_extra([{'method': 'bitcoin_atm', 'amount_usdt': 100}]) == []


def test_normalize_derives_rate_from_rub():
    """Курс не прислали, рубли есть — считаем сами."""
    out = _normalize_payin_extra([
        {'method': 'sber_reqs', 'amount_rub': 200000, 'amount_usdt': 2365.362}])
    assert out[0]['rate_rub_usdt'] == pytest.approx(84.5537, abs=1e-4)


def test_normalize_crypto_part_has_no_rate():
    """Крипта пришла напрямую — рублей нет, курса нет."""
    out = _normalize_payin_extra([{'method': 'crypto_direct', 'amount_usdt': 500}])
    assert out[0]['amount_rub'] is None
    assert out[0]['rate_rub_usdt'] is None


def test_normalize_keeps_hashes_and_uuids():
    out = _normalize_payin_extra([{
        'method': 'crypto_direct', 'amount_usdt': 500,
        'tx_hashes': [{'hash': H_EXTRA, 'amount_usdt': 500}],
        'sber_uuids': ['uuid-1'],
    }])
    assert out[0]['tx_hashes'] == [{'hash': H_EXTRA, 'amount_usdt': 500.0}]
    assert out[0]['sber_uuids'] == ['uuid-1']


def test_all_parts_derives_main_from_totals(db):
    """Часть 1 восстанавливается как итог минус дополнительные —
    отдельно она нигде не хранится."""
    extra = _normalize_payin_extra([
        {'method': 'sber_reqs', 'amount_rub': 200000, 'amount_usdt': 2365.362}])
    d = Deal(client_name='T', payin_method=PayInMethod.PARTNERS_CASH,
             payin_partner_name='FOEX',
             payin_amount_rub=800000, payin_amount_usdt=9285.362,
             payin_extra=json.dumps(extra, ensure_ascii=False))
    db.add(d)
    db.commit()

    parts = _payin_all_parts(d)
    assert len(parts) == 2
    assert parts[0]['method'] == 'partners_cash'
    assert parts[0]['amount_usdt'] == pytest.approx(6920.0, abs=0.01)
    assert parts[0]['amount_rub'] == pytest.approx(600000, abs=0.01)
    assert parts[0]['rate_rub_usdt'] == pytest.approx(86.7052, abs=1e-4)
    assert parts[0]['partner_name'] == 'FOEX'
    assert parts[1]['amount_usdt'] == pytest.approx(2365.362, abs=0.01)


def test_all_parts_single_channel(db):
    """Сделка без дополнительных частей — ровно одна часть из плоских полей."""
    d = Deal(client_name='T', payin_method=PayInMethod.PARTNERS_CASH,
             payin_amount_rub=600000, payin_amount_usdt=6920.0)
    db.add(d)
    db.commit()
    parts = _payin_all_parts(d)
    assert len(parts) == 1
    assert parts[0]['amount_usdt'] == 6920.0
```

- [ ] **Шаг 2: Убедиться, что тесты падают**

Запуск: `python -m pytest tests/test_multi_payin.py -v`
Ожидаемо: FAIL — `ImportError: cannot import name '_normalize_payin_extra'`

- [ ] **Шаг 3: Реализовать хелперы**

В `app.py` сразу после `_normalize_tx_hashes` (перед `_normalize_payout_transfers`):

```python
def _normalize_payin_extra(raw):
    """Дополнительные приходы → список частей одного формата.

    Часть без суммы USDT выбрасывается: строка без денег ничего не описывает,
    а в выгрузке дала бы пустую строку с чужой долей. Неизвестный метод тоже
    выбрасываем — на нём упал бы лейбл в Sheet и в Telegram.

    Курс считается из рублей, если его не прислали: форма умеет вводить в обе
    стороны, интеграции могут прислать только рубли и USDT.
    """
    out = []
    for item in (raw or []):
        if not isinstance(item, dict):
            continue
        method = str(item.get('method') or '').strip()
        if method not in PAYIN_METHOD_LABELS:
            continue
        try:
            usdt = float(item.get('amount_usdt'))
        except (TypeError, ValueError):
            continue
        if usdt <= 0:
            continue

        def _pos(key):
            try:
                v = float(item.get(key))
            except (TypeError, ValueError):
                return None
            return v if v > 0 else None

        rub = _pos('amount_rub')
        rate = _pos('rate_rub_usdt')
        if rub and not rate:
            rate = round(rub / usdt, 6)
        out.append({
            'method': method,
            'amount_rub': rub,
            'rate_rub_usdt': rate,
            'amount_usdt': round(usdt, 6),
            'partner_name': (str(item.get('partner_name') or '').strip() or None),
            'tx_hashes': _normalize_tx_hashes(item.get('tx_hashes')),
            'sber_uuids': [str(u) for u in (item.get('sber_uuids') or []) if u],
            'note': str(item.get('note') or '').strip(),
        })
    return out


def _payin_extra_list(deal):
    """Дополнительные приходы сделки. Битый JSON = пустой список, не падаем."""
    if not deal.payin_extra:
        return []
    try:
        parsed = json.loads(deal.payin_extra)
    except (ValueError, TypeError):
        return []
    return parsed if isinstance(parsed, list) else []


def _payin_all_parts(deal):
    """Все части прихода, первая — основная, из плоских payin_* полей.

    Основная часть отдельно НЕ хранится: плоские поля после сохранения содержат
    агрегаты, поэтому её суммы восстанавливаются вычитанием дополнительных.
    Так у выгрузки и уведомлений один формат, и они не знают про асимметрию.
    """
    extra = _payin_extra_list(deal)
    main_usdt = round((deal.payin_amount_usdt or 0)
                      - sum(p.get('amount_usdt') or 0 for p in extra), 6)
    main_rub = round((deal.payin_amount_rub or 0)
                     - sum(p.get('amount_rub') or 0 for p in extra), 6)
    main = {
        'method': deal.payin_method.value if deal.payin_method else '',
        'amount_rub': main_rub if main_rub > 0 else None,
        'rate_rub_usdt': (round(main_rub / main_usdt, 6)
                          if main_rub > 0 and main_usdt > 0 else None),
        'amount_usdt': main_usdt,
        'partner_name': deal.payin_partner_name or None,
        'tx_hashes': _normalize_tx_hashes(
            json.loads(deal.payin_tx_hashes) if deal.payin_tx_hashes else []),
        'sber_uuids': [],
        'note': '',
    }
    return [main] + extra
```

- [ ] **Шаг 4: Прогнать тесты**

Запуск: `python -m pytest tests/test_multi_payin.py -v`
Ожидаемо: 9 passed

- [ ] **Шаг 5: Коммит**

```bash
git add app.py tests/test_multi_payin.py
git commit -m "feat(multi-payin): нормализация и чтение частей прихода"
```

---

## Task 3: Пересчёт агрегатов и защита от двойного учёта

**Файлы:**
- Изменить: `app.py` — после `_payin_all_parts`
- Тест: `tests/test_multi_payin.py`

Ключевое место всей задачи. `_apply_payin_extra` получает суммы **основной** части
явными аргументами — если брать их из уже записанных плоских полей, повторный PUT
прибавил бы дополнительные части второй раз и приход поехал бы вверх.

- [ ] **Шаг 1: Написать падающие тесты**

```python
from app import (..., _apply_payin_extra, _payin_hash_list)


def test_apply_aggregates_totals(db):
    """Итог = основная часть + дополнительные. Эталон спеки §4."""
    d = Deal(client_name='T', payin_method=PayInMethod.PARTNERS_CASH)
    db.add(d)
    db.commit()
    _apply_payin_extra(db, d, [
        {'method': 'sber_reqs', 'amount_rub': 200000, 'amount_usdt': 2365.362}],
        main_usdt=6920.0, main_rub=600000)
    assert d.payin_amount_usdt == pytest.approx(9285.362, abs=0.001)
    assert d.payin_amount_rub == pytest.approx(800000, abs=0.01)


def test_apply_weighted_rate_reconciles(db):
    """Средневзвешенный курс сходится делением — это и есть его смысл.
    Курс первой части (86.7052) дал бы 9226.67 вместо 9285.36."""
    d = Deal(client_name='T', payin_method=PayInMethod.PARTNERS_CASH)
    db.add(d); db.commit()
    _apply_payin_extra(db, d, [
        {'method': 'sber_reqs', 'amount_rub': 200000, 'amount_usdt': 2365.362}],
        main_usdt=6920.0, main_rub=600000)
    assert d.payin_rate_rub_usdt == pytest.approx(86.1571, abs=1e-4)
    assert d.payin_amount_rub / d.payin_rate_rub_usdt == pytest.approx(
        d.payin_amount_usdt, abs=0.01)


def test_apply_rate_ignores_crypto_part(db):
    """У крипты рублей нет — в знаменатель средневзвешенного она не идёт."""
    d = Deal(client_name='T', payin_method=PayInMethod.SBER_REQS)
    db.add(d); db.commit()
    _apply_payin_extra(db, d, [{'method': 'crypto_direct', 'amount_usdt': 500}],
                       main_usdt=2365.362, main_rub=200000)
    assert d.payin_amount_usdt == pytest.approx(2865.362, abs=0.001)
    assert d.payin_rate_rub_usdt == pytest.approx(84.5537, abs=1e-4)


def test_apply_method_is_largest_part(db):
    """payin_method читают Битрикс, фильтры и DealCloser — ставим метод
    крупнейшей части, а не первой введённой."""
    d = Deal(client_name='T', payin_method=PayInMethod.SBER_REQS)
    db.add(d); db.commit()
    _apply_payin_extra(db, d, [
        {'method': 'partners_cash', 'amount_rub': 600000, 'amount_usdt': 6920.0}],
        main_usdt=2365.362, main_rub=200000)
    assert d.payin_method == PayInMethod.PARTNERS_CASH


def test_apply_merges_hashes_for_double_spend_guard(db):
    """Хэш дополнительной части обязан попасть в payin_tx_hashes —
    иначе get_used_transaction_hashes его не увидит и приход спишут дважды."""
    d = Deal(client_name='T', payin_method=PayInMethod.PARTNERS_CASH,
             payin_tx_hashes=json.dumps([{'hash': 'a' * 64, 'amount_usdt': 6920.0}]))
    db.add(d); db.commit()
    _apply_payin_extra(db, d, [{
        'method': 'crypto_direct', 'amount_usdt': 500,
        'tx_hashes': [{'hash': 'b' * 64, 'amount_usdt': 500}]}],
        main_usdt=6920.0, main_rub=None)
    assert set(_payin_hash_list(d)) == {'a' * 64, 'b' * 64}


def test_apply_is_idempotent(db):
    """Повторный вызов с теми же аргументами не удваивает приход."""
    d = Deal(client_name='T', payin_method=PayInMethod.PARTNERS_CASH)
    db.add(d); db.commit()
    extra = [{'method': 'sber_reqs', 'amount_rub': 200000, 'amount_usdt': 2365.362}]
    _apply_payin_extra(db, d, extra, main_usdt=6920.0, main_rub=600000)
    _apply_payin_extra(db, d, extra, main_usdt=6920.0, main_rub=600000)
    assert d.payin_amount_usdt == pytest.approx(9285.362, abs=0.001)


def test_apply_empty_extra_clears_column(db):
    """Убрали все дополнительные части — колонка пустеет, агрегаты = основная часть."""
    d = Deal(client_name='T', payin_method=PayInMethod.PARTNERS_CASH,
             payin_extra=json.dumps([{'method': 'sber_reqs', 'amount_usdt': 100}]))
    db.add(d); db.commit()
    _apply_payin_extra(db, d, [], main_usdt=6920.0, main_rub=600000)
    assert d.payin_extra is None
    assert d.payin_amount_usdt == 6920.0
```

- [ ] **Шаг 2: Убедиться, что тесты падают**

Запуск: `python -m pytest tests/test_multi_payin.py -v`
Ожидаемо: FAIL — `cannot import name '_apply_payin_extra'`

- [ ] **Шаг 3: Реализовать**

В `app.py` после `_payin_all_parts`:

```python
def _apply_payin_extra(session, deal, raw_extra, main_usdt, main_rub):
    """Пишет дополнительные приходы и пересчитывает агрегаты в плоских полях.

    main_usdt / main_rub — суммы ОСНОВНОЙ части, передаются явно. Брать их из
    deal.payin_amount_* нельзя: там уже агрегат, и повторный вызов прибавил бы
    дополнительные части второй раз.

    Хэши и uuid'ы приходов Сбера сливаются в payin_tx_hashes / payin_parts —
    на этом стоит защита от двойного учёта (get_used_transaction_hashes и
    _sync_sber_claims), и она продолжает работать без правок.
    """
    extra = _normalize_payin_extra(raw_extra)
    deal.payin_extra = json.dumps(extra, ensure_ascii=False) if extra else None

    main_usdt = float(main_usdt or 0)
    main_rub = float(main_rub or 0)

    deal.payin_amount_usdt = round(
        main_usdt + sum(p['amount_usdt'] for p in extra), 6) or None
    total_rub = round(main_rub + sum(p['amount_rub'] or 0 for p in extra), 6)
    deal.payin_amount_rub = total_rub or None

    # Средневзвешенный курс — только по рублёвым частям. Курс первой части
    # разошёлся бы с итогом: 800 000 / 86.7052 = 9 226.67 при приходе 9 285.36.
    rub_usdt = main_usdt if main_rub else 0.0
    rub_usdt += sum(p['amount_usdt'] for p in extra if p['amount_rub'])
    deal.payin_rate_rub_usdt = round(total_rub / rub_usdt, 6) if (total_rub and rub_usdt) else None

    # Метод крупнейшей части: его читают Битрикс, фильтры списка и DealCloser
    if extra:
        biggest = max(extra, key=lambda p: p['amount_usdt'])
        if biggest['amount_usdt'] > main_usdt:
            try:
                deal.payin_method = PayInMethod(biggest['method'])
            except ValueError:
                pass

    # Слияние хэшей: без него приход дополнительной части можно списать второй раз
    merged_hashes = list(_normalize_tx_hashes(
        json.loads(deal.payin_tx_hashes) if deal.payin_tx_hashes else []))
    seen = {h['hash'] for h in merged_hashes}
    for p in extra:
        for h in p['tx_hashes']:
            if h['hash'] not in seen:
                seen.add(h['hash'])
                merged_hashes.append(h)
    _apply_payin_tx_hashes(deal, merged_hashes)

    # Слияние приходов Сбера: _sync_sber_claims забирает их из пула по payin_parts
    extra_uuids = [u for p in extra for u in p['sber_uuids']]
    if extra_uuids:
        base = []
        if deal.payin_parts:
            try:
                base = json.loads(deal.payin_parts) or []
            except (ValueError, TypeError):
                base = []
        known = {str(x.get('uuid')) for x in base if isinstance(x, dict) and x.get('uuid')}
        for uid in extra_uuids:
            if uid not in known:
                known.add(uid)
                base.append({'uuid': uid, 'amount_rub': None, 'payer': '',
                             'date': '', 'note': 'доп. приход'})
        deal.payin_parts = json.dumps(base, ensure_ascii=False)
        _sync_sber_claims(session, deal, base)
```

- [ ] **Шаг 4: Прогнать тесты**

Запуск: `python -m pytest tests/test_multi_payin.py -v`
Ожидаемо: 16 passed

- [ ] **Шаг 5: Коммит**

```bash
git add app.py tests/test_multi_payin.py
git commit -m "feat(multi-payin): пересчёт агрегатов, средневзвешенный курс, слияние хэшей"
```

---

## Task 4: API — POST и PUT принимают `payin_extra`

**Файлы:**
- Изменить: `app.py` — `create_deal` (~строка 4658, конструктор `Deal(...)`),
  `update_deal` (~строка 4860, после блока `payin_tx_hashes`)
- Тест: `tests/test_multi_payin.py`

Контракт: в запросе `payin_amount_usdt` и `payin_amount_rub` — суммы **основной**
части (ровно то, что менеджер ввёл в главные поля формы). Сервер записывает в эти
поля агрегаты. На чтение `to_dict` отдаёт агрегат плюс `payin_extra`, из которых
форма восстанавливает основную часть вычитанием.

Пересчёт запускается, только если в payload есть `payin_extra` **или** у сделки уже
есть дополнительные части. Интеграции (DealCloser, Битрикс), которые про части не
знают и шлют одноканальные сделки, ведут себя ровно как раньше.

- [ ] **Шаг 1: Написать падающие тесты**

```python
@pytest.fixture
def tc():
    app.config['TESTING'] = True
    s = get_session()
    try:
        a = s.query(AdminUser).first()
        if not a:
            a = AdminUser(username='test_admin', display_name='T',
                          password_hash=AdminUser.hash_password('x'))
            s.add(a); s.commit()
        aid = a.id
    finally:
        s.close()
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess['user_id'] = aid
        yield c


def _payload(**over):
    base = {
        'client_name': 'elena imaikina',
        'payin_method': 'partners_cash',
        'payin_amount_rub': 600000,
        'payin_amount_usdt': 6920.0,
        'payin_partner_name': 'FOEX',
        'payin_extra': [{'method': 'sber_reqs', 'amount_rub': 200000,
                         'amount_usdt': 2365.362}],
    }
    base.update(over)
    return base


def test_post_deal_aggregates(tc, db):
    r = tc.post('/api/deals', json=_payload())
    assert r.status_code in (200, 201), r.get_data(as_text=True)
    d = db.query(Deal).order_by(Deal.id.desc()).first()
    assert d.payin_amount_usdt == pytest.approx(9285.362, abs=0.001)
    assert d.payin_amount_rub == pytest.approx(800000, abs=0.01)
    assert d.payin_rate_rub_usdt == pytest.approx(86.1571, abs=1e-4)
    assert len(json.loads(d.payin_extra)) == 1


def test_put_deal_recomputes(tc, db):
    tc.post('/api/deals', json=_payload(payin_extra=[]))
    d = db.query(Deal).order_by(Deal.id.desc()).first()
    assert d.payin_amount_usdt == 6920.0

    r = tc.put(f'/api/deals/{d.id}', json={
        'payin_amount_rub': 600000, 'payin_amount_usdt': 6920.0,
        'payin_extra': [{'method': 'sber_reqs', 'amount_rub': 200000,
                         'amount_usdt': 2365.362}]})
    assert r.status_code == 200, r.get_data(as_text=True)
    db.expire_all()
    d = db.query(Deal).filter(Deal.id == d.id).first()
    assert d.payin_amount_usdt == pytest.approx(9285.362, abs=0.001)


def test_put_without_payin_extra_does_not_drift(tc, db):
    """Интеграция шлёт PUT без payin_extra — приход не должен вырасти."""
    tc.post('/api/deals', json=_payload())
    d = db.query(Deal).order_by(Deal.id.desc()).first()
    before = d.payin_amount_usdt

    tc.put(f'/api/deals/{d.id}', json={'notes': 'просто заметка'})
    db.expire_all()
    d = db.query(Deal).filter(Deal.id == d.id).first()
    assert d.payin_amount_usdt == pytest.approx(before, abs=0.001)


def test_put_removing_extra_returns_to_single(tc, db):
    tc.post('/api/deals', json=_payload())
    d = db.query(Deal).order_by(Deal.id.desc()).first()
    tc.put(f'/api/deals/{d.id}', json={
        'payin_amount_rub': 600000, 'payin_amount_usdt': 6920.0, 'payin_extra': []})
    db.expire_all()
    d = db.query(Deal).filter(Deal.id == d.id).first()
    assert d.payin_extra is None
    assert d.payin_amount_usdt == 6920.0
    assert d.payin_amount_rub == 600000
```

- [ ] **Шаг 2: Убедиться, что тесты падают**

Запуск: `python -m pytest tests/test_multi_payin.py -k "post_deal or put_deal or put_without or put_removing" -v`
Ожидаемо: FAIL — `payin_amount_usdt == 6920.0`, агрегат не посчитан

- [ ] **Шаг 3: POST — пересчёт после создания**

В `create_deal`, сразу после `db.add(deal)` и перед первым `db.flush()` /
`db.commit()` (найти по `db.add(deal)` в теле `create_deal`):

```python
        # Дополнительные приходы: плоские поля выше приняли суммы ОСНОВНОЙ части,
        # здесь они превращаются в агрегаты по всей сделке
        if data.get('payin_extra'):
            _apply_payin_extra(db, deal, data['payin_extra'],
                               main_usdt=data.get('payin_amount_usdt'),
                               main_rub=data.get('payin_amount_rub'))
```

- [ ] **Шаг 4: PUT — пересчёт с явным вычислением основной части**

В `update_deal` сразу после блока `if 'payin_tx_hashes' in data:` (~строка 4868):

```python
        # Дополнительные приходы. Основную часть вычисляем ДО записи агрегатов:
        # если поле не пришло в payload, восстанавливаем её вычитанием старых
        # дополнительных частей из сохранённого итога — иначе приход поедет вверх.
        if 'payin_extra' in data or deal.payin_extra:
            old_extra = _payin_extra_list(deal)
            old_usdt = sum(p.get('amount_usdt') or 0 for p in old_extra)
            old_rub = sum(p.get('amount_rub') or 0 for p in old_extra)
            main_usdt = (data['payin_amount_usdt'] if 'payin_amount_usdt' in data
                         else round((deal.payin_amount_usdt or 0) - old_usdt, 6))
            main_rub = (data['payin_amount_rub'] if 'payin_amount_rub' in data
                        else round((deal.payin_amount_rub or 0) - old_rub, 6))
            _apply_payin_extra(session, deal,
                               data.get('payin_extra', old_extra),
                               main_usdt=main_usdt, main_rub=main_rub)
```

> Имя сессии в `update_deal` — проверить по коду: в блоке `payin_parts` выше
> используется `session`. Использовать то же имя.

- [ ] **Шаг 5: Прогнать тесты**

Запуск: `python -m pytest tests/test_multi_payin.py -v`
Ожидаемо: 20 passed

- [ ] **Шаг 6: Полный прогон — не сломали ли соседей**

Запуск: `python -m pytest tests/ -q`
Ожидаемо: 728 passed (708 было + 20 новых)

- [ ] **Шаг 7: Коммит**

```bash
git add app.py tests/test_multi_payin.py
git commit -m "feat(multi-payin): POST и PUT /api/deals принимают payin_extra"
```

---

## Task 5: Пропорциональное разбиение

**Файлы:**
- Изменить: `app.py` — после `_payin_all_parts`
- Тест: `tests/test_multi_payin.py`

- [ ] **Шаг 1: Написать падающие тесты**

```python
from app import (..., split_by_payin_share)


def test_split_reconciles_with_total():
    """Сумма долей равна исходному числу — иначе лист перестанет сходиться."""
    assert split_by_payin_share(8669.00, [2365.362, 6920.0]) == [2208.35, 6460.65]
    assert sum(split_by_payin_share(8669.00, [2365.362, 6920.0])) == 8669.00


def test_split_agent_payout():
    assert split_by_payin_share(185.71, [2365.362, 6920.0]) == [47.31, 138.40]


def test_split_three_parts_residual_goes_last():
    """Некруглые доли: остаток округления добирает последняя часть."""
    res = split_by_payin_share(100.00, [1, 1, 1])
    assert res == [33.33, 33.33, 33.34]
    assert sum(res) == 100.00


def test_split_single_part_returns_total():
    assert split_by_payin_share(8669.00, [9285.362]) == [8669.00]


def test_split_zero_total():
    assert split_by_payin_share(0, [1, 2]) == [0.0, 0.0]


def test_split_handles_zero_denominator():
    """Приходов нет — делить нечего, но и падать нельзя."""
    assert split_by_payin_share(100.0, [0, 0]) == [0.0, 100.0]
```

- [ ] **Шаг 2: Убедиться, что тесты падают**

Запуск: `python -m pytest tests/test_multi_payin.py -k split -v`
Ожидаемо: FAIL — `cannot import name 'split_by_payin_share'`

- [ ] **Шаг 3: Реализовать**

```python
def split_by_payin_share(total, part_amounts, digits=2):
    """Делит число по долям приходов частей. Только для выгрузки — в БД доли
    не хранятся.

    Остаток округления добирает ПОСЛЕДНЯЯ часть: иначе сумма строк разойдётся
    с итогом сделки на копейки и лист перестанет сходиться при сверке месяца.
    """
    n = len(part_amounts)
    if not n:
        return []
    total = float(total or 0)
    denom = sum(float(a or 0) for a in part_amounts)
    out, acc = [], 0.0
    for a in part_amounts[:-1]:
        v = round(total * float(a or 0) / denom, digits) if denom else 0.0
        out.append(v)
        acc += v
    out.append(round(total - acc, digits))
    return out
```

- [ ] **Шаг 4: Прогнать тесты**

Запуск: `python -m pytest tests/test_multi_payin.py -k split -v`
Ожидаемо: 6 passed

- [ ] **Шаг 5: Коммит**

```bash
git add app.py tests/test_multi_payin.py
git commit -m "feat(multi-payin): пропорциональное разбиение с остатком в последней части"
```

---

## Task 6: Telegram — блок «— Приход —»

**Файлы:**
- Изменить: `app.py` — новый хелпер перед `_mf_realty_telegram_text` (~строка 3009);
  вставка в `_mf_realty_telegram_text` (~строка 3021), `_mf_freehold_telegram_text`
  (~строка 3072), `_send_deal_telegram` (~строка 3175)
- Тест: `tests/test_multi_payin_telegram.py` (создать)

- [ ] **Шаг 1: Написать падающие тесты**

Создать `tests/test_multi_payin_telegram.py`:

```python
"""
Блок «— Приход —» в трёх шаблонах уведомлений.
Спека: docs/specs/2026-08-14-multi-payin.md §7

Запуск: cd Dev/CalcCRM && python -m pytest tests/test_multi_payin_telegram.py -v
"""
import pytest
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ['SECRET_KEY'] = 'test-secret-key-for-pytest'

from app import (app, get_session, Deal, Client, PayInMethod,
                 _payin_parts_block, _mf_freehold_telegram_text,
                 MF_FREEHOLD_KIND)

EXTRA = [{'method': 'sber_reqs', 'amount_rub': 200000.0, 'rate_rub_usdt': 84.5537,
          'amount_usdt': 2365.362, 'partner_name': None,
          'tx_hashes': [], 'sber_uuids': [], 'note': ''}]


@pytest.fixture(autouse=True)
def clean_db():
    s = get_session()
    try:
        s.query(Deal).delete(); s.query(Client).delete(); s.commit()
    finally:
        s.close()
    yield


def _multi_deal(**over):
    d = Deal(client_name='elena imaikina',
             payin_method=PayInMethod.PARTNERS_CASH, payin_partner_name='FOEX',
             payin_amount_rub=800000, payin_amount_usdt=9285.362,
             payin_rate_rub_usdt=86.1571,
             payin_extra=json.dumps(EXTRA, ensure_ascii=False))
    for k, v in over.items():
        setattr(d, k, v)
    return d


def test_block_absent_for_single_channel():
    d = Deal(client_name='T', payin_method=PayInMethod.PARTNERS_CASH,
             payin_amount_rub=600000, payin_amount_usdt=6920.0)
    assert _payin_parts_block(d) == ''


def test_block_lists_every_channel():
    text = _payin_parts_block(_multi_deal())
    assert '— Приход (2) —' in text
    assert 'наличные FOEX · 600,000 ₽ @ 86.7052 → $6,920.00' in text
    assert 'сбер реквизиты · 200,000 ₽ @ 84.5537 → $2,365.36' in text


def test_crypto_part_without_rate():
    """У крипты рублей нет — курс не печатаем, а не рисуем ноль."""
    d = _multi_deal(payin_amount_rub=600000, payin_amount_usdt=7420.0,
                    payin_extra=json.dumps([{
                        'method': 'crypto_direct', 'amount_rub': None,
                        'rate_rub_usdt': None, 'amount_usdt': 500.0,
                        'partner_name': None, 'tx_hashes': [],
                        'sber_uuids': [], 'note': ''}], ensure_ascii=False))
    text = _payin_parts_block(d)
    assert '• крипта → $500.00' in text
    assert '@' not in text.split('крипта')[1]


def test_freehold_message_contains_block():
    d = _multi_deal(deal_kind=MF_FREEHOLD_KIND, transfer_sent_usd=8669.0,
                    profit_usdt=616.36, net_profit_usdt=430.65,
                    referrer_payout_usdt=185.71)
    msg = _mf_freehold_telegram_text(d)
    assert '— Приход (2) —' in msg
    assert msg.index('Приход: $9,285.36') < msg.index('— Приход (2) —')
    assert msg.index('— Приход (2) —') < msg.index('Отправлено:')
```

- [ ] **Шаг 2: Убедиться, что тесты падают**

Запуск: `python -m pytest tests/test_multi_payin_telegram.py -v`
Ожидаемо: FAIL — `cannot import name '_payin_parts_block'`

- [ ] **Шаг 3: Реализовать хелпер**

В `app.py` перед `_mf_realty_telegram_text`:

```python
def _payin_parts_block(deal):
    """Блок «— Приход —» для уведомлений. Пусто у сделки с одним каналом.

    Один и тот же во всех трёх шаблонах: получатель должен видеть, откуда
    сложился приход, независимо от типа сделки.
    """
    parts = _payin_all_parts(deal)
    if len(parts) < 2:
        return ''
    out = f"\n— Приход ({len(parts)}) —"
    for p in parts:
        name = PAYIN_METHOD_LABELS.get(p['method'], p['method'] or '—')
        if p['partner_name']:
            name += f" {p['partner_name']}"
        if p['amount_rub'] and p['rate_rub_usdt']:
            out += (f"\n• {name} · {p['amount_rub']:,.0f} ₽ @ {p['rate_rub_usdt']:.4f}"
                    f" → ${p['amount_usdt']:,.2f}")
        else:
            out += f"\n• {name} → ${p['amount_usdt']:,.2f}"
    return out
```

- [ ] **Шаг 4: Вставить в три шаблона**

В `_mf_realty_telegram_text` заменить строку прихода внутри `msg = (...)`:

```python
        f"Приход: ${deal.payin_amount_usdt or 0:,.2f}"
    )
    msg += _payin_parts_block(deal)
    msg += (
        f"\nОтправлено в MF Corp: {deal.company_sent_thb or 0:,.0f} ฿ "
```

В `_mf_freehold_telegram_text` — так же:

```python
        f"Приход: ${deal.payin_amount_usdt or 0:,.2f}"
    )
    msg += _payin_parts_block(deal)
    msg += (
        f"\nОтправлено: ${sent:,.2f}\n"
```

В `_send_deal_telegram` заменить формирование `msg` (~строка 3175):

```python
    # При смешанных валютах частей строка «Получено» в рублях занижает —
    # у крипто-части рублей нет. Тогда печатаем итог в USDT, разбивка ниже.
    parts = _payin_all_parts(deal)
    mixed = len(parts) > 1 and any(bool(p['amount_rub']) != bool(parts[0]['amount_rub'])
                                   for p in parts)
    if mixed:
        received_line = f"Получено: ${amount_in_usdt:,.2f} (несколько каналов)"
    else:
        received_line = f"Получено: {amount_in:,.2f} {currency} (${amount_in_usdt:,.2f})"

    msg = (
        f"✅ <b>Сделка {deal.id} — {(deal.client.name if deal.client else deal.client_name) or 'без имени'} — {date_str}</b>\n"
        f"{received_line}"
        f"{_payin_parts_block(deal)}\n"
        f"Выдано: {payout_val:,} {payout_cur} (${payout_usdt:,.2f}){source_note}\n"
        f"Прибыль: ${profit:,.2f}"
    )
```

- [ ] **Шаг 5: Прогнать тесты**

Запуск: `python -m pytest tests/test_multi_payin_telegram.py tests/test_mf_telegram_trigger.py -v`
Ожидаемо: все passed

- [ ] **Шаг 6: Коммит**

```bash
git add app.py tests/test_multi_payin_telegram.py
git commit -m "feat(multi-payin): блок «— Приход —» в трёх шаблонах Telegram"
```

---

## Task 7: Выгрузка «общая сделка» — строки по частям

**Файлы:**
- Изменить: `app.py` — новый `build_deal_rows(deal, start_num)` рядом с
  `_sync_deals_to_gsheet_impl` (~строка 2488); `_force_update_deal_row_in_gsheet`
  (~строка 2725); диапазон записи `A{n}:R{n}` → `A{n}:S{n}`
- Тест: `tests/test_multi_payin_export.py` (создать)

Строку собирает **чистая функция** — тесты не ходят в Google.

- [ ] **Шаг 1: Написать падающие тесты**

Создать `tests/test_multi_payin_export.py`:

```python
"""
Выгрузка мульти-Pay-In сделки: строки по частям, нумерация, поиск и удаление.
Спека: docs/specs/2026-08-14-multi-payin.md §8

Запуск: cd Dev/CalcCRM && python -m pytest tests/test_multi_payin_export.py -v
"""
import pytest
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ['SECRET_KEY'] = 'test-secret-key-for-pytest'

from app import (app, get_session, Deal, Client, PayInMethod, PayOutMethod,
                 build_deal_rows)

EXTRA = [{'method': 'sber_reqs', 'amount_rub': 200000.0, 'rate_rub_usdt': 84.5537,
          'amount_usdt': 2365.362, 'partner_name': None,
          'tx_hashes': [], 'sber_uuids': [], 'note': ''}]


@pytest.fixture(autouse=True)
def clean_db():
    s = get_session()
    try:
        s.query(Deal).delete(); s.query(Client).delete(); s.commit()
    finally:
        s.close()
    yield


def _deal(**over):
    d = Deal(id=512, client_name='elena imaikina',
             payin_method=PayInMethod.PARTNERS_CASH, payin_partner_name='FOEX',
             payin_amount_rub=800000, payin_amount_usdt=9285.362,
             payin_rate_rub_usdt=86.1571,
             payout_method=PayOutMethod.TRANSFER,
             payout_amount_thb=282600, payout_amount_usdt=8669.0,
             profit_usdt=616.36, referrer_name='FOEX',
             referrer_payout_usdt=185.71, net_profit_usdt=430.65,
             payin_extra=json.dumps(EXTRA, ensure_ascii=False))
    for k, v in over.items():
        setattr(d, k, v)
    return d


def test_single_channel_gives_one_row():
    """Сделка с одним каналом — ровно одна строка и «1/1» в колонке части."""
    rows = build_deal_rows(_deal(payin_extra=None, payin_amount_rub=600000,
                                 payin_amount_usdt=6920.0), 187)
    assert len(rows) == 1
    assert rows[0][0] == 187
    assert rows[0][18] == '1/1'


def test_two_parts_give_two_rows_with_numbering():
    rows = build_deal_rows(_deal(), 187)
    assert len(rows) == 2
    assert rows[0][0] == 187
    assert rows[1][0] == '187.2'
    assert [r[18] for r in rows] == ['1/2', '2/2']


def test_method_column_is_per_row():
    """Ради этого задача и делалась: способ пополнения честен построчно."""
    rows = build_deal_rows(_deal(), 187)
    assert rows[0][15] == 'наличные'
    assert rows[1][15] == 'сбер реквизиты'


def test_payin_columns_are_per_part():
    rows = build_deal_rows(_deal(), 187)
    assert rows[0][4] == '600,000.00'
    assert rows[1][4] == '200,000.00'
    assert rows[0][6] == '$6,920.00'
    assert rows[1][6] == '$2,365.36'


def test_divisible_columns_sum_to_deal_total():
    """Инвариант листа: сумма строк равна сделке."""
    rows = build_deal_rows(_deal(), 187)
    money = lambda s: float(str(s).replace('$', '').replace(',', '') or 0)
    assert sum(money(r[9]) for r in rows) == pytest.approx(8669.0, abs=0.01)
    assert sum(money(r[12]) for r in rows) == pytest.approx(185.71, abs=0.01)
    assert sum(money(r[13]) for r in rows) == pytest.approx(430.65, abs=0.01)
    assert sum(int(r[7]) for r in rows) == 282600


def test_deal_id_anchor_repeats_in_every_row():
    """Якорь upsert — обычный deal.id во всех строках блока."""
    rows = build_deal_rows(_deal(), 187)
    assert [r[17] for r in rows] == ['512', '512']
```

- [ ] **Шаг 2: Убедиться, что тесты падают**

Запуск: `python -m pytest tests/test_multi_payin_export.py -v`
Ожидаемо: FAIL — `cannot import name 'build_deal_rows'`

- [ ] **Шаг 3: Реализовать сборщик строк**

В `app.py` перед `_sync_deals_to_gsheet_impl`:

```python
def build_deal_rows(deal, start_num):
    """Строки листа «общая сделка» для одной сделки — по строке на часть Pay-In.

    Колонки A–R как раньше, S — «часть» (`1/2`, `2/2`; у одноканальной `1/1`).
    Номер первой строки обычный, дальше `.2`, `.3` — так видно, что строки
    принадлежат одной сделке, и счётчик остаётся счётчиком сделок.

    Делится всё, что пропорционально приходу: выдача клиенту, выдача в USDT,
    выплата партнёру, чистая доходность. Приход, метод и хэши идут построчно
    от самой части. Остальное дублируется.
    """
    parts = _payin_all_parts(deal)
    amounts = [p['amount_usdt'] for p in parts]
    n = len(parts)

    date_str = deal.created_at.strftime('%d.%m.%Y') if deal.created_at else ''
    payout_method_str = PAYOUT_METHOD_LABELS.get(
        deal.payout_method.value if deal.payout_method else '', '')
    net_profit = (deal.net_profit_usdt
                  if (deal.referrer_payout_usdt and deal.net_profit_usdt is not None)
                  else deal.profit_usdt)

    payout_thb = deal.custom_payout_amount or deal.payout_amount_thb or 0
    payout_currency = (deal.custom_payout_currency or 'THB').upper()
    payout_usdt = deal.payout_amount_usdt or 0

    thb_split = split_by_payin_share(payout_thb, amounts, digits=0)
    usdt_split = split_by_payin_share(payout_usdt, amounts)
    ref_split = split_by_payin_share(deal.referrer_payout_usdt or 0, amounts)
    net_split = split_by_payin_share(net_profit or 0, amounts)

    rows = []
    for i, p in enumerate(parts):
        if deal.is_custom:
            method_str = 'кастом'
            currency_in = (deal.custom_payin_currency or '').lower()
            amount_in = deal.custom_payin_amount or 0 if i == 0 else 0
        else:
            method_str = PAYIN_METHOD_LABELS.get(p['method'], '')
            if p['amount_rub']:
                currency_in, amount_in = 'rub', p['amount_rub']
            else:
                currency_in, amount_in = 'usdt', p['amount_usdt']
        rows.append([
            start_num if i == 0 else f'{start_num}.{i + 1}',       # A: номер
            (deal.client.name if deal.client else deal.client_name) or '',  # B
            '',                                                    # C
            date_str,                                              # D
            f'{amount_in:,.2f}' if amount_in else '',              # E: сумма части
            currency_in,                                           # F
            f"${p['amount_usdt']:,.2f}" if p['amount_usdt'] else '',  # G: USDT части
            int(thb_split[i]) if thb_split[i] else '',             # H: доля выдачи
            payout_currency,                                       # I
            f'${usdt_split[i]:,.2f}' if usdt_split[i] else '',     # J: доля выдачи USDT
            '',                                                    # K: брокеру
            deal.referrer_name or '',                              # L
            f'${ref_split[i]:,.2f}' if ref_split[i] else '',       # M: доля партнёру
            f'${net_split[i]:,.2f}' if net_profit is not None else '',  # N: доля чистой
            payout_method_str,                                     # O
            method_str,                                            # P: метод ЧАСТИ
            ', '.join(h['hash'] for h in p['tx_hashes']),          # Q: хэши части
            str(deal.id) if deal.id else '',                       # R: якорь upsert
            f'{i + 1}/{n}',                                        # S: часть
        ])
    return rows
```

- [ ] **Шаг 4: Прогнать тесты**

Запуск: `python -m pytest tests/test_multi_payin_export.py -v`
Ожидаемо: 6 passed

- [ ] **Шаг 5: Подключить к синку и расширить диапазон записи**

В `_sync_deals_to_gsheet_impl` заменить сборку `row = [...]` на:

```python
            new_rows.extend(build_deal_rows(deal, last_num))
```

(`last_num` инкрементируется как раньше — на **сделку**, а не на строку.)

В `_force_update_deal_row_in_gsheet` заменить построение `row` и запись на:

```python
    rows = build_deal_rows(deal, existing_num)
    ws.update(values=rows,
              range_name=f'A{row_num}:S{row_num + len(rows) - 1}',
              value_input_option='USER_ENTERED')
```

> Если у сделки стало больше строк, чем было в листе, `update` затрёт соседние.
> Поэтому перед записью блок строк выравнивается — это Task 8, где появляется
> `find_deal_rows_in_gsheet`. До Task 8 не деплоить.

- [ ] **Шаг 6: Коммит**

```bash
git add app.py tests/test_multi_payin_export.py
git commit -m "feat(multi-payin): лист «общая сделка» — строка на часть Pay-In"
```

---

## Task 8: Поиск и удаление строк — список вместо первой

**Файлы:**
- Изменить: `app.py` — `find_deal_row_in_gsheet` (~строка 2655),
  `_delete_deal_from_gsheet_impl` (~строка 2705), `_force_update_deal_row_in_gsheet`
- Тест: `tests/test_multi_payin_export.py`

Без этого удаление сделки снесёт первую строку и оставит вторую сиротой — с приходом,
прибылью и партнёром, за которыми нет ни одной сделки.

- [ ] **Шаг 1: Написать падающие тесты**

```python
from app import (..., find_deal_rows_in_gsheet)


def _sheet_rows():
    """Лист: сделка 512 в двух строках плюс соседняя 511."""
    blank = [''] * 19
    r511 = list(blank); r511[0] = '186'; r511[1] = 'другой клиент'
    r511[3] = '13.08.2026'; r511[6] = '$9,285.36'; r511[17] = '511'
    a = list(blank); a[0] = '187'; a[1] = 'elena imaikina'
    a[3] = '14.08.2026'; a[6] = '$6,920.00'; a[17] = '512'; a[18] = '1/2'
    b = list(blank); b[0] = '187.2'; b[1] = 'elena imaikina'
    b[3] = '14.08.2026'; b[6] = '$2,365.36'; b[17] = '512'; b[18] = '2/2'
    return [r511, a, b]


def test_finds_all_rows_of_deal():
    rows = find_deal_rows_in_gsheet(_sheet_rows(), _deal())
    assert rows == [2, 3]


def test_finds_single_row_legacy():
    d = _deal(id=511, client_name='другой клиент')
    assert find_deal_rows_in_gsheet(_sheet_rows(), d) == [1]


def test_fallback_disabled_for_multipart_deal():
    """Фолбэк «дата + сумма USDT» сравнивает с ИТОГОМ, а в строках лежат части:
    своё не найдёт, зато мог бы снести чужую сделку с той же суммой."""
    sheet = _sheet_rows()
    for r in sheet[1:]:
        r[17] = ''          # у своих строк якорь потерян
    assert find_deal_rows_in_gsheet(sheet, _deal()) == []


def test_fallback_allowed_for_single_part_deal():
    """Легаси-строка без якоря у одночастной сделки по-прежнему находится
    по «имя + дата» — этот путь ломать нельзя, старых строк в листе много."""
    from datetime import datetime
    legacy = [''] * 19
    legacy[1] = 'elena imaikina'
    legacy[3] = '14.08.2026'
    legacy[6] = '$6,920.00'
    single = _deal(id=999, payin_extra=None, payin_amount_rub=600000,
                   payin_amount_usdt=6920.0, created_at=datetime(2026, 8, 14))
    assert find_deal_rows_in_gsheet([legacy], single) == [1]
```

- [ ] **Шаг 2: Убедиться, что тесты падают**

Запуск: `python -m pytest tests/test_multi_payin_export.py -k find -v`
Ожидаемо: FAIL — `cannot import name 'find_deal_rows_in_gsheet'`

- [ ] **Шаг 3: Реализовать поиск списком**

В `app.py` рядом с `find_deal_row_in_gsheet`:

```python
def find_deal_rows_in_gsheet(all_rows, deal):
    """Номера ВСЕХ строк сделки (1-indexed), по порядку сверху вниз.

    Основной путь — `deal.id` в колонке R. Фолбэки по «имя + дата» и
    «дата + сумма USDT» оставлены только для сделок с ОДНОЙ частью: у
    многочастной в колонке G лежат суммы частей, а фолбэк сравнивает с итогом —
    своё он не найдёт никогда, зато может совпасть чужая сделка с близкой суммой
    в тот же день, и снесётся она.
    """
    deal_id_str = str(deal.id) if getattr(deal, 'id', None) else ''
    if deal_id_str:
        hits = [i + 1 for i, row in enumerate(all_rows)
                if len(row) >= 18 and str(row[17]).strip() == deal_id_str]
        if hits:
            return hits

    if len(_payin_all_parts(deal)) > 1:
        return []          # вслепую многочастную не ищем

    row_num = find_deal_row_in_gsheet(None, all_rows, deal)
    return [row_num] if row_num else []
```

- [ ] **Шаг 4: Переписать удаление**

Заменить тело `_delete_deal_from_gsheet_impl`:

```python
def _delete_deal_from_gsheet_impl(deal):
    """Удаляет ВСЕ строки сделки из листа «общая сделка».

    Снизу вверх: после первого delete_rows номера строк ниже съезжают на единицу,
    и удаление сверху вниз снесло бы соседнюю сделку.
    """
    try:
        gc = get_gsheet_client()
        if not gc:
            return
        sh = gc.open_by_key(GSHEET_ID)
        ws = sh.worksheet(GSHEET_WORKSHEET)
        all_rows = ws.get_all_values()
        row_nums = find_deal_rows_in_gsheet(all_rows, deal)
        if not row_nums:
            print(f'[GSheet] Rows not found for deal #{deal.id} ({deal.client_name})')
            return
        for row_num in sorted(row_nums, reverse=True):
            ws.delete_rows(row_num)
        print(f'[GSheet] Deleted {len(row_nums)} row(s) for deal #{deal.id}')
    except Exception as e:
        print(f'[GSheet] Delete error: {e}')
```

- [ ] **Шаг 5: Выровнять блок при перезаписи**

В `_force_update_deal_row_in_gsheet` заменить начало на:

```python
    row_nums = find_deal_rows_in_gsheet(all_rows, deal)
    if not row_nums:
        return False
    rows = build_deal_rows(deal, all_rows[row_nums[0] - 1][0] or deal.id)

    # Число частей могло измениться: лишние строки удаляем снизу вверх,
    # недостающие вставляем, иначе update затрёт соседнюю сделку
    while len(row_nums) > len(rows):
        ws.delete_rows(row_nums.pop())
    while len(row_nums) < len(rows):
        ws.insert_rows([[''] * 19], row=row_nums[-1] + 1)
        row_nums.append(row_nums[-1] + 1)

    ws.update(values=rows,
              range_name=f'A{row_nums[0]}:S{row_nums[-1]}',
              value_input_option='USER_ENTERED')
    print(f'[GSheet] Force-updated {len(rows)} row(s) for deal #{deal.id}')
    return True
```

- [ ] **Шаг 6: Прогнать тесты**

Запуск: `python -m pytest tests/test_multi_payin_export.py tests/test_realty_export.py -v`
Ожидаемо: все passed

- [ ] **Шаг 7: Коммит**

```bash
git add app.py tests/test_multi_payin_export.py
git commit -m "fix(multi-payin): удаление сносит все строки сделки, фолбэки только одночастным"
```

---

## Task 9: Выгрузки недвижимости — строки по частям

**Файлы:**
- Изменить: `app.py` — `GSHEET_REALTY_HEADERS` (~строка 2189),
  `GSHEET_FREEHOLD_HEADERS` (~строка 2201), `build_realty_row` → `build_realty_rows`
  (~строка 2286), `build_freehold_row` → `build_freehold_rows` (~строка 2331),
  вызовы в `sync_realty_deal_to_gsheet`
- Тест: `tests/test_multi_payin_export.py`

Что делится, что построчно и что стоит только в первой строке — спека §8,
раздел «Листы недвижимости». Читать перед реализацией.

- [ ] **Шаг 1: Написать падающие тесты**

```python
from app import (..., build_freehold_rows, build_realty_rows, MF_FREEHOLD_KIND)


def _freehold():
    return _deal(deal_kind=MF_FREEHOLD_KIND, realty_purpose='Кондо Layan',
                 invoice_amount_usd=8400.0, transfer_sent_usd=8669.0,
                 transfer_fee_percent=1.5, transfer_fee_fixed_usd=50.0,
                 transfer_fee_usd=177.37, transfer_arrive_usd=8491.63,
                 doc_invoice_url='https://drive/inv')


def test_freehold_two_rows():
    rows = build_freehold_rows(_freehold())
    assert len(rows) == 2


def test_freehold_payin_per_part():
    rows = build_freehold_rows(_freehold())
    assert rows[0][3] == 600000          # сумма руб части
    assert rows[1][3] == 200000
    assert rows[0][4] == pytest.approx(86.7052, abs=1e-4)   # курс ЧАСТИ, не средний
    assert rows[1][4] == pytest.approx(84.5537, abs=1e-4)


def test_freehold_sent_is_divided():
    rows = build_freehold_rows(_freehold())
    assert rows[0][8] == pytest.approx(2208.35, abs=0.01)
    assert rows[1][8] == pytest.approx(6460.65, abs=0.01)
    assert sum(r[8] for r in rows) == pytest.approx(8669.0, abs=0.01)


def test_freehold_indivisible_only_in_first_row():
    """Инвойс, комиссия перевода, «дойдёт застройщику» и документы описывают
    единственное событие — во второй строке пусто."""
    rows = build_freehold_rows(_freehold())
    for idx in (7, 9, 10, 11, 12, 16, 17, 18):
        assert rows[1][idx] == '', f'колонка {idx} должна быть пустой во 2-й строке'
    assert rows[0][7] == 8400.0
    assert rows[0][12] == 8491.63


def test_freehold_part_column_last():
    rows = build_freehold_rows(_freehold())
    assert [r[-1] for r in rows] == ['1/2', '2/2']
    assert [r[-2] for r in rows] == [512, 512]
```

- [ ] **Шаг 2: Убедиться, что тесты падают**

Запуск: `python -m pytest tests/test_multi_payin_export.py -k freehold -v`
Ожидаемо: FAIL — `cannot import name 'build_freehold_rows'`

- [ ] **Шаг 3: Добавить колонку «часть» в заголовки**

```python
GSHEET_REALTY_HEADERS = [
    ...,
    'хеш транзакции', 'CRM ID', 'часть',
]
GSHEET_FREEHOLD_HEADERS = [
    ...,
    'хеш транзакции', 'CRM ID', 'часть',
]
```

- [ ] **Шаг 4: Переписать `build_freehold_row` в `build_freehold_rows`**

```python
def build_freehold_rows(deal):
    """Строки выгрузки сделки во фрихолде — по строке на часть Pay-In.

    Делятся приход и всё, что от него пропорционально: отправка, доход, выплата
    агенту, чистый доход. Инвойс, комиссия за перевод, «дойдёт застройщику» и
    ссылки на документы описывают один SWIFT — стоят только в первой строке,
    делить их значило бы придумать переводы, которых не было.
    """
    d = deal
    parts = _payin_all_parts(d)
    amounts = [p['amount_usdt'] for p in parts]
    n = len(parts)

    agent_names = ', '.join(
        a.name for a in sorted(d.agents, key=lambda x: (x.tier or 1, x.id or 0)) if a.name
    ) if d.agents else ''
    date_str = d.created_at.strftime('%d.%m.%Y') if d.created_at else ''

    sent_split = split_by_payin_share(d.transfer_sent_usd or 0, amounts)
    profit_split = split_by_payin_share(d.profit_usdt or 0, amounts)
    agent_split = split_by_payin_share(d.referrer_payout_usdt or 0, amounts)
    net_split = split_by_payin_share(d.net_profit_usdt or 0, amounts)

    rows = []
    for i, p in enumerate(parts):
        first = (i == 0)
        rows.append([
            d.realty_purpose or '',                                    # Назначение
            date_str,
            'usdt-usd' if p['method'] == 'crypto_direct' else 'rub-usd',
            p['amount_rub'] or '',                                     # сумма руб части
            p['rate_rub_usdt'] or '',                                  # курс ЧАСТИ
            agent_names,
            p['amount_usdt'] or '',                                    # приход usdt части
            (d.invoice_amount_usd or '') if first else '',
            sent_split[i] or '',                                       # отправлено — доля
            (d.transfer_fee_percent or '') if first else '',
            (d.transfer_fee_fixed_usd or '') if first else '',
            (d.transfer_fee_usd or '') if first else '',
            (d.transfer_arrive_usd or '') if first else '',
            profit_split[i] or '',                                     # доход — доля
            agent_split[i] or '',                                      # выплата агенту — доля
            net_split[i] or '',                                        # чистый доход — доля
            (d.doc_invoice_url or '') if first else '',
            (d.doc_contract_url or '') if first else '',
            (d.doc_payment_url or '') if first else '',
            ', '.join(h['hash'] for h in p['tx_hashes']),
            d.id,
            f'{i + 1}/{n}',
        ])
    return rows
```

- [ ] **Шаг 5: Прогнать тесты фрихолда**

Запуск: `python -m pytest tests/test_multi_payin_export.py -k freehold -v`
Ожидаемо: 5 passed

- [ ] **Шаг 6: Тесты лизхолда**

```python
from app import (..., build_realty_rows, MF_REALTY_KIND)


def _leasehold():
    return _deal(deal_kind=MF_REALTY_KIND, realty_purpose='Кондо Layan',
                 invoice_amount_thb=290000.0, buy_rate_thb_usdt=32.8,
                 sell_rate_thb_usdt=32.3, company_percent=2.0,
                 company_sent_thb=295800.0, company_fee_thb=5800.0,
                 company_fee_usdt=176.83, crypto_remainder_usdt=81.36,
                 net_profit_usdt=258.19, doc_invoice_url='https://drive/inv')


def test_leasehold_two_rows_with_part_column():
    rows = build_realty_rows(_leasehold())
    assert len(rows) == 2
    assert [r[-1] for r in rows] == ['1/2', '2/2']
    assert [r[-2] for r in rows] == [512, 512]


def test_leasehold_payin_per_part():
    rows = build_realty_rows(_leasehold())
    assert rows[0][3] == 600000
    assert rows[1][3] == 200000
    assert rows[0][4] == pytest.approx(86.7052, abs=1e-4)
    assert rows[1][4] == pytest.approx(84.5537, abs=1e-4)


def test_leasehold_company_sent_is_divided():
    rows = build_realty_rows(_leasehold())
    assert sum(r[13] for r in rows) == pytest.approx(295800.0, abs=0.01)


def test_leasehold_indivisible_only_in_first_row():
    """Инвойс, курсы покупки/продажи, процент компании и документы —
    описывают одну отправку в MF Corp, делить их нечего."""
    rows = build_realty_rows(_leasehold())
    for idx in (6, 7, 8, 12, 21, 22, 23):
        assert rows[1][idx] == '', f'колонка {idx} должна быть пустой во 2-й строке'
    assert rows[0][6] == 290000.0
    assert rows[0][8] == 32.8
```

- [ ] **Шаг 6b: Переписать `build_realty_row` в `build_realty_rows`**

```python
def build_realty_rows(deal):
    """Строки выгрузки сделки через MF Corp — по строке на часть Pay-In.

    Порядок колонок — как в GSHEET_REALTY_HEADERS. Делится всё, что
    пропорционально приходу; инвойс, курсы, процент компании и ссылки на
    документы описывают одну отправку и стоят только в первой строке.
    """
    d = deal
    parts = _payin_all_parts(d)
    amounts = [p['amount_usdt'] for p in parts]
    n = len(parts)

    agent_names = ', '.join(
        a.name for a in sorted(d.agents, key=lambda x: (x.tier or 1, x.id or 0)) if a.name
    ) if d.agents else ''
    date_str = d.created_at.strftime('%d.%m.%Y') if d.created_at else ''

    invoice_cost = (round((d.invoice_amount_thb or 0) / d.buy_rate_thb_usdt, 2)
                    if d.buy_rate_thb_usdt else 0)
    income = (round((d.payin_amount_usdt or 0) - invoice_cost, 2)
              if d.buy_rate_thb_usdt else 0)

    cost_split = split_by_payin_share(invoice_cost, amounts)
    fee_usdt_split = split_by_payin_share(d.company_fee_usdt or 0, amounts)
    sent_thb_split = split_by_payin_share(d.company_sent_thb or 0, amounts)
    fee_thb_split = split_by_payin_share(d.company_fee_thb or 0, amounts)
    katika_thb_split = split_by_payin_share(d.katika_fee_thb or 0, amounts)
    katika_usdt_split = split_by_payin_share(d.katika_fee_usdt or 0, amounts)
    income_split = split_by_payin_share(income, amounts)
    agent_split = split_by_payin_share(d.referrer_payout_usdt or 0, amounts)
    wallet_split = split_by_payin_share(d.crypto_remainder_usdt or 0, amounts)
    net_split = split_by_payin_share(d.net_profit_usdt or 0, amounts)

    rows = []
    for i, p in enumerate(parts):
        first = (i == 0)
        rows.append([
            d.realty_purpose or '',                                     # 0 Назначение
            date_str,                                                   # 1 дата
            'usdt-thb' if p['method'] == 'crypto_direct' else 'rub-thb',  # 2 направление
            p['amount_rub'] or '',                                      # 3 сумма руб части
            p['rate_rub_usdt'] or '',                                   # 4 курс ЧАСТИ
            agent_names,                                                # 5 от кого
            (d.invoice_amount_thb or '') if first else '',              # 6 сумма thb
            (d.sell_rate_thb_usdt or '') if first else '',              # 7 курс продажи
            (d.buy_rate_thb_usdt or '') if first else '',               # 8 курс покупкт
            p['amount_usdt'] or '',                                     # 9 приход usdt части
            cost_split[i] or '',                                        # 10 потратили на инвойс
            fee_usdt_split[i] or '',                                    # 11 доход компании usdt
            ((d.company_percent / 100) if d.company_percent else '') if first else '',  # 12
            sent_thb_split[i] or '',                                    # 13 отправлено thb
            fee_thb_split[i] or '',                                     # 14 доход в батах
            katika_thb_split[i] or '',                                  # 15 Катика баты
            katika_usdt_split[i] or '',                                 # 16 Катика usdt
            income_split[i] or '',                                      # 17 доход
            agent_split[i] or '',                                       # 18 выплата агенту
            wallet_split[i] or '',                                      # 19 на кошельке
            net_split[i] or '',                                         # 20 чистый доход
            (d.doc_invoice_url or '') if first else '',                 # 21 инвойс
            (d.doc_contract_url or '') if first else '',                # 22 договор
            (d.doc_payment_url or '') if first else '',                 # 23 оплата
            ', '.join(h['hash'] for h in p['tx_hashes']),               # 24 хеш
            d.id,                                                       # 25 CRM ID
            f'{i + 1}/{n}',                                             # 26 часть
        ])
    return rows
```

- [ ] **Шаг 6c: Прогнать тесты лизхолда**

Запуск: `python -m pytest tests/test_multi_payin_export.py -k leasehold -v`
Ожидаемо: 4 passed

- [ ] **Шаг 7: Обновить вызовы в `sync_realty_deal_to_gsheet`**

Заменить `build_realty_row(deal)` / `build_freehold_row(deal)` на `*_rows(deal)` и
записывать блок строк с тем же выравниванием, что в Task 8 (лишние удалить снизу
вверх, недостающие вставить).

- [ ] **Шаг 8: Регрессы спеки §10 — эталон, приход Сбера, кастом, лист рефереров**

Дописать в `tests/test_multi_payin.py`:

```python
from app import compute_mf_freehold, SberIncome


def test_reference_case_end_to_end():
    """Эталон спеки §4 целиком: реальная сделка elena imaikina от 13.08.
    Ради этих цифр задача и делалась — если они поедут, поедут деньги."""
    payin = 2365.362 + 6920.0
    r = compute_mf_freehold(payin, sent_usd=8669.0,
                            agents=[{'comp_model': 'markup', 'percent': 2, 'tier': 1}])
    assert r['gross_profit_usdt'] == pytest.approx(616.36, abs=0.01)
    assert r['agents_total_usdt'] == pytest.approx(185.71, abs=0.01)
    assert r['net_profit_usdt'] == pytest.approx(430.65, abs=0.01)


def test_extra_sber_income_is_claimed(db):
    """Приход Сбера, забранный ДОПОЛНИТЕЛЬНОЙ частью, помечается claimed_deal_id —
    иначе его спишут во вторую сделку."""
    inc = SberIncome(uuid='uuid-extra-1', amount_rub=200000.0, kind='transfer')
    db.add(inc)
    d = Deal(client_name='T', payin_method=PayInMethod.PARTNERS_CASH)
    db.add(d)
    db.commit()

    _apply_payin_extra(db, d, [{
        'method': 'sber_reqs', 'amount_rub': 200000, 'amount_usdt': 2365.362,
        'sber_uuids': ['uuid-extra-1']}], main_usdt=6920.0, main_rub=600000)
    db.commit()

    assert db.query(SberIncome).filter(
        SberIncome.uuid == 'uuid-extra-1').first().claimed_deal_id == d.id


def test_custom_deal_supports_extra(tc, db):
    """Кастомные сделки: части складываются в итог, custom_* не трогаются."""
    r = tc.post('/api/deals', json=_payload(
        is_custom=True, custom_payin_currency='RUB', custom_payin_amount=600000))
    assert r.status_code in (200, 201), r.get_data(as_text=True)
    d = db.query(Deal).order_by(Deal.id.desc()).first()
    assert d.payin_amount_usdt == pytest.approx(9285.362, abs=0.001)
    assert d.custom_payin_amount == 600000
```

Дописать в `tests/test_multi_payin_export.py`:

```python
def test_referrer_sheet_row_is_not_split():
    """Лист «рефереры» — одна строка на сделку: выплата партнёру одна,
    делить её по каналам прихода незачем."""
    import inspect
    from app import _sync_referrer_to_gsheet
    src = inspect.getsource(_sync_referrer_to_gsheet)
    assert 'build_deal_rows' not in src
    assert '_payin_all_parts' not in src
```

> Имя функции синка листа рефереров сверить по коду (`GSHEET_REFERRERS_WORKSHEET`,
> ~строка 2960) и подставить фактическое.

- [ ] **Шаг 9: Полный прогон**

Запуск: `python -m pytest tests/ -q`
Ожидаемо: все passed

- [ ] **Шаг 10: Коммит**

```bash
git add app.py tests/test_multi_payin.py tests/test_multi_payin_export.py
git commit -m "feat(multi-payin): листы недвижимости — строки по частям, неделимое в первой"
```

---

## Task 10: Карточка сделки

**Файлы:**
- Изменить: `static/crm/crm.html` — рендер карточки (~строка 4043, рядом с
  `deal.payin_partner_name`)

- [ ] **Шаг 1: Добавить рендер частей**

После строки с `payin_partner_name` вставить:

```javascript
                        ${(deal.payin_extra && deal.payin_extra.length) ? `
                        <div style="margin:8px 0;padding:8px;background:#f8fafc;border-radius:6px;">
                            <div style="font-weight:600;margin-bottom:4px;">Приход по частям</div>
                            ${renderPayinParts(deal).map(p => `
                                <div style="font-size:0.9rem;color:#334155;">
                                    • ${escapeHtml(p.label)}
                                    ${p.amount_rub ? `· ${p.amount_rub.toLocaleString('ru')} ₽ @ ${p.rate_rub_usdt.toFixed(4)}` : ''}
                                    → $${p.amount_usdt.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}
                                </div>`).join('')}
                        </div>` : ''}
```

- [ ] **Шаг 2: Добавить хелпер восстановления частей**

Рядом с `applyPayinMethodFields` (~строка 5476):

```javascript
        // Лейблы методов — те же, что PAYIN_METHOD_LABELS на бэкенде
        const PAYIN_LABELS = {
            spp_doverka: 'СБП (Доверка)', crypto_direct: 'крипта',
            partners_cash: 'наличные', sber_wl: 'СБП', sber_reqs: 'сбер реквизиты',
        };

        // Основная часть отдельно не хранится — восстанавливаем вычитанием
        // дополнительных из агрегатов, как _payin_all_parts на бэкенде
        function renderPayinParts(deal) {
            const extra = deal.payin_extra || [];
            const mainUsdt = (deal.payin_amount_usdt || 0)
                - extra.reduce((s, p) => s + (p.amount_usdt || 0), 0);
            const mainRub = (deal.payin_amount_rub || 0)
                - extra.reduce((s, p) => s + (p.amount_rub || 0), 0);
            const main = {
                label: (PAYIN_LABELS[deal.payin_method] || deal.payin_method || '—')
                    + (deal.payin_partner_name ? ' ' + deal.payin_partner_name : ''),
                amount_rub: mainRub > 0 ? mainRub : null,
                rate_rub_usdt: (mainRub > 0 && mainUsdt > 0) ? mainRub / mainUsdt : null,
                amount_usdt: mainUsdt,
            };
            return [main].concat(extra.map(p => ({
                label: (PAYIN_LABELS[p.method] || p.method || '—')
                    + (p.partner_name ? ' ' + p.partner_name : ''),
                amount_rub: p.amount_rub, rate_rub_usdt: p.rate_rub_usdt,
                amount_usdt: p.amount_usdt,
            })));
        }
```

- [ ] **Шаг 2b: Проверить руками**

Запуск: `LOCAL_NO_AUTH=1 TRONSCAN_WARM_ENABLED=0 PORT=5055 python3 app.py`,
открыть `http://localhost:5055/crm`, создать сделку с двумя частями через
`POST /api/deals`, открыть карточку. Ожидаемо: две строки прихода, суммы сходятся
с итогом.

- [ ] **Шаг 3: Коммит**

```bash
git add static/crm/crm.html
git commit -m "feat(multi-payin): строки частей прихода в карточке сделки"
```

---

## Task 11: Форма — кнопка «+ ещё приход»

**Файлы:**
- Изменить: `static/crm/crm.html` — разметка после блока `payinRateGroup`
  (~строка 1236); функции рядом с `applyPayinMethodFields` (~строка 5476);
  сборка payload (~строка 6804, рядом с `payin_parts:`); заполнение формы при
  редактировании (~строка 4531)

- [ ] **Шаг 1: Разметка блока частей**

Сразу после закрывающего `</div>` группы `payinRateGroup` (~строка 1236):

```html
                        <!-- Дополнительные приходы: одна сделка, несколько каналов -->
                        <div id="payinExtraBox" style="margin-bottom:1rem;">
                            <div id="payinExtraList"></div>
                            <button type="button" class="btn btn-secondary" onclick="payinExtraAdd()"
                                style="margin-top:6px;">+ ещё приход</button>
                            <div id="payinExtraSummary"
                                style="margin-top:8px;font-size:0.9rem;color:#334155;"></div>
                        </div>
```

- [ ] **Шаг 2: Состояние и рендер карточек**

Рядом с `applyPayinMethodFields`:

```javascript
        // payinExtra — дополнительные приходы текущей формы:
        // [{method, amount_rub, rate_rub_usdt, amount_usdt, partner_name, tx_hash, note}]
        // Основной приход остаётся в главных полях формы.
        let payinExtra = [];

        function payinExtraAdd() {
            payinExtra.push({ method: 'crypto_direct', amount_rub: null,
                              rate_rub_usdt: null, amount_usdt: null,
                              partner_name: '', tx_hash: '', note: '' });
            payinExtraRender();
        }

        function payinExtraRemove(i) { payinExtra.splice(i, 1); payinExtraRender(); }

        function payinExtraSet(i, field, value) {
            const num = ['amount_rub', 'rate_rub_usdt', 'amount_usdt'].includes(field);
            payinExtra[i][field] = num ? (parseFloat(value) || null) : value;
            // Курс и USDT считаются друг из друга — как payinMode у основного приход
            const p = payinExtra[i];
            if (field === 'rate_rub_usdt' && p.amount_rub && p.rate_rub_usdt) {
                p.amount_usdt = +(p.amount_rub / p.rate_rub_usdt).toFixed(4);
            } else if (field === 'amount_usdt' && p.amount_rub && p.amount_usdt) {
                p.rate_rub_usdt = +(p.amount_rub / p.amount_usdt).toFixed(4);
            } else if (field === 'amount_rub' && p.amount_rub && p.rate_rub_usdt) {
                p.amount_usdt = +(p.amount_rub / p.rate_rub_usdt).toFixed(4);
            }
            payinExtraRender();
        }

        function payinExtraRender() {
            const box = document.getElementById('payinExtraList');
            if (!box) return;
            box.innerHTML = payinExtra.map((p, i) => {
                const isCrypto = p.method === 'crypto_direct';
                const isCash = p.method === 'partners_cash';
                return `
                <div style="border:1px solid #e2e8f0;border-radius:8px;padding:10px;margin-bottom:6px;">
                    <div style="display:flex;gap:8px;align-items:center;margin-bottom:6px;">
                        <strong style="white-space:nowrap;">Приход ${i + 2}</strong>
                        <select class="form-control" style="max-width:200px;"
                            onchange="payinExtraSet(${i}, 'method', this.value)">
                            ${Object.entries(PAYIN_LABELS).filter(([k]) => k !== 'spp_doverka')
                                .map(([k, v]) => `<option value="${k}" ${p.method === k ? 'selected' : ''}>${v}</option>`).join('')}
                        </select>
                        <button type="button" class="btn btn-danger" style="margin-left:auto;"
                            onclick="payinExtraRemove(${i})">✕</button>
                    </div>
                    <div style="display:flex;gap:8px;flex-wrap:wrap;">
                        ${isCrypto ? '' : `
                        <input type="number" step="any" class="form-control" style="max-width:150px;"
                            placeholder="Сумма RUB" value="${p.amount_rub ?? ''}"
                            oninput="payinExtraSet(${i}, 'amount_rub', this.value)">
                        <input type="number" step="any" class="form-control" style="max-width:150px;"
                            placeholder="Курс RUB/USDT" value="${p.rate_rub_usdt ?? ''}"
                            oninput="payinExtraSet(${i}, 'rate_rub_usdt', this.value)">`}
                        <input type="number" step="any" class="form-control" style="max-width:150px;"
                            placeholder="Пришло USDT" value="${p.amount_usdt ?? ''}"
                            oninput="payinExtraSet(${i}, 'amount_usdt', this.value)">
                        ${isCash ? `
                        <input type="text" class="form-control" style="max-width:150px;"
                            placeholder="Партнёр" value="${p.partner_name || ''}"
                            oninput="payinExtraSet(${i}, 'partner_name', this.value)">` : ''}
                        <input type="text" class="form-control" style="max-width:260px;"
                            placeholder="TxHash" value="${p.tx_hash || ''}"
                            oninput="payinExtraSet(${i}, 'tx_hash', this.value)">
                    </div>
                </div>`;
            }).join('');
            payinExtraSummary();
        }

        function payinExtraSummary() {
            const el = document.getElementById('payinExtraSummary');
            if (!el) return;
            if (!payinExtra.length) { el.textContent = ''; return; }
            const main = parseFloat(document.querySelector('[name="payin_amount_usdt"]')?.value) || 0;
            const total = main + payinExtra.reduce((s, p) => s + (p.amount_usdt || 0), 0);
            const money = v => '$' + v.toLocaleString('en-US',
                { minimumFractionDigits: 2, maximumFractionDigits: 2 });
            el.innerHTML = `<strong>Итого приход: ${money(total)}</strong>
                <span style="color:#64748b;">(основной ${money(main)} + ${payinExtra.length} доп.)</span>`;
        }
```

- [ ] **Шаг 3: Сериализация в payload**

Рядом с `payin_parts:` (~строка 6804) добавить в объект запроса:

```javascript
                payin_extra: payinExtra
                    .filter(p => p.amount_usdt > 0)
                    .map(p => ({
                        method: p.method,
                        amount_rub: p.amount_rub,
                        rate_rub_usdt: p.rate_rub_usdt,
                        amount_usdt: p.amount_usdt,
                        partner_name: p.partner_name || null,
                        tx_hashes: p.tx_hash ? [{ hash: p.tx_hash.trim(),
                                                  amount_usdt: p.amount_usdt }] : [],
                        sber_uuids: [],
                        note: p.note || '',
                    })),
```

- [ ] **Шаг 4: Восстановление при открытии сделки**

В `openDealEditor`, рядом с `if (deal.payin_partner_name)` (~строка 4531):

```javascript
                        // Основная часть = агрегат минус дополнительные:
                        // отдельно она не хранится (см. _payin_all_parts на бэкенде)
                        payinExtra = (deal.payin_extra || []).map(p => ({
                            method: p.method, amount_rub: p.amount_rub,
                            rate_rub_usdt: p.rate_rub_usdt, amount_usdt: p.amount_usdt,
                            partner_name: p.partner_name || '',
                            tx_hash: (p.tx_hashes && p.tx_hashes[0]) ? p.tx_hashes[0].hash : '',
                            note: p.note || '',
                        }));
                        if (payinExtra.length) {
                            const extraUsdt = payinExtra.reduce((s, p) => s + (p.amount_usdt || 0), 0);
                            const extraRub = payinExtra.reduce((s, p) => s + (p.amount_rub || 0), 0);
                            form.payin_amount_usdt.value =
                                +((deal.payin_amount_usdt || 0) - extraUsdt).toFixed(4);
                            form.payin_amount_rub.value =
                                +((deal.payin_amount_rub || 0) - extraRub).toFixed(2) || '';
                            form.payin_rate_rub_usdt.value =
                                (form.payin_amount_rub.value && form.payin_amount_usdt.value)
                                    ? +(form.payin_amount_rub.value / form.payin_amount_usdt.value).toFixed(4)
                                    : '';
                        }
                        payinExtraRender();
```

- [ ] **Шаг 5: Сброс между сделками**

Найти место, где форма очищается перед созданием новой сделки (там же, где
обнуляется `sberParts`), и добавить:

```javascript
            payinExtra = [];
            payinExtraRender();
```

> Это тот же класс бага, что чинили 05.08 и 06.08 — форма наследовала поля
> предыдущей сделки. Пропустить нельзя.

- [ ] **Шаг 6: Проверить руками на эталоне**

Запуск: `LOCAL_NO_AUTH=1 TRONSCAN_WARM_ENABLED=0 PORT=5055 python3 app.py`

Ввести сделку из спеки: тип «Недвижимость фрихолд», основной приход
`partners_cash` 600 000 ₽ / 6920 USDT (партнёр FOEX), «+ ещё приход» →
`sber_reqs` 200 000 ₽ / 2365.362 USDT, отправка 8669, агент markup 2%.

Ожидаемо в сводке формы: итого приход $9 285.36, прибыль $616.36, агент $185.71,
чистая $430.65. Сохранить, открыть заново — обе части на месте, основная часть
показывает 6920, а не 9285.36.

- [ ] **Шаг 7: Полный прогон и коммит**

```bash
python -m pytest tests/ -q
git add static/crm/crm.html
git commit -m "feat(multi-payin): кнопка «+ ещё приход» и живая сводка в форме сделки"
```

---

## Task 12: Проверка на живых сделках с подчисткой

**Где:** прод `https://grusha.up.railway.app/crm` после деплоя.

Юнит-тесты не видят Google Sheets и Telegram — там реальные сетевые вызовы.
Единственный способ убедиться, что строки легли и ушли, — завести настоящую сделку
и удалить её.

> **Флаг `is_test` здесь не подходит.** Он выпиливает сделку из выгрузки и из
> уведомлений (см. `sync_deals_to_gsheet`, `_send_deal_telegram`) — именно то, что
> надо проверить. Проверочная сделка заводится обычной и удаляется руками.

> **Уведомление в TG уйдёт в рабочий чат и не отзывается.** Клиента назвать так,
> чтобы никто не принял за настоящую сделку: `ТЕСТ мульти-payin — удаляю`.
> Предупредить в чате до начала.

- [ ] **Шаг 1: Завести сделку с двумя частями**

В CRM: тип «Недвижимость фрихолд», клиент `ТЕСТ мульти-payin — удаляю`.
Основной приход `partners_cash` 600 000 ₽ / 6920 USDT, партнёр FOEX.
«+ ещё приход» → `sber_reqs` 200 000 ₽ / 2365.362 USDT.
Отправка 8669, агент markup 2%. Статус — `completed` (иначе выгрузка не сработает).

Ожидаемо в сводке формы: итого приход $9 285.36, прибыль $616.36, агент $185.71,
чистая $430.65.

- [ ] **Шаг 2: Проверить лист «общая сделка»**

Открыть таблицу, найти строки по `CRM ID`. Ожидаемо: **две** строки,
номера `N` и `N.2`, колонка «часть» — `1/2` и `2/2`, способ пополнения
`наличные` и `сбер реквизиты` построчно. Сумма долей выдачи, партнёру и чистой
равна итогу сделки.

- [ ] **Шаг 3: Проверить лист `<месяц> freehold`**

Ожидаемо: две строки, курсы 86.7052 и 84.5537 построчно, `отправлено usd`
2208.35 и 6460.65, а `дойдёт застройщику usd` и ссылки на документы — только
в первой строке.

- [ ] **Шаг 4: Проверить уведомление в Telegram**

Ожидаемо: блок `— Приход (2) —` между строкой «Приход» и «Отправлено», обе части
с курсами, чистый доход $430.65.

- [ ] **Шаг 5: Проверить редактирование**

Убрать вторую часть, сохранить. Ожидаемо: в обоих листах осталась **одна** строка,
номер без `.2`, колонка «часть» = `1/1`, приход 6920. Вернуть вторую часть —
строка снова появилась.

- [ ] **Шаг 6: Удалить сделку и подчистить**

Удалить сделку в CRM. Ожидаемо: из листа «общая сделка» и из
`<месяц> freehold` пропали **обе** строки, соседние сделки на месте
(проверить номера соседей до и после).

Если строка осталась — удаление нашло не все: вернуться к Task 8, это тот самый
баг, ради которого он написан.

- [ ] **Шаг 7: Убедиться, что в CRM пусто**

`GET /api/deals?q=ТЕСТ мульти-payin` — пустой список. Клиент, заведённый
автоматически, тоже удаляется, если больше ни к чему не привязан.

---

## Task 13: Документация

**Файлы:**
- Изменить: `.claude/docs/CLAUDE-calccrm.md`, `wiki/projects/calccrm.md`
  (репозиторий верхнего уровня, не CalcCRM)

- [ ] **Шаг 1: Changelog в `CLAUDE-calccrm.md`**

Добавить запись в раздел бизнес-логики — что такое `payin_extra`, что плоские
`payin_*` теперь агрегаты, что `payin_rate_rub_usdt` средневзвешенный.

- [ ] **Шаг 2: Changelog в `wiki/projects/calccrm.md`**

Строка вида `2026-08-14: Feat: мульти-Pay-In ...` с указанием коммитов и числа тестов.

- [ ] **Шаг 3: Коммит (репозиторий верхнего уровня)**

```bash
cd "/Users/karimamirov/Desktop/untitled folder"
git add .claude/docs/CLAUDE-calccrm.md wiki/projects/calccrm.md
git commit -m "docs: мульти-Pay-In в CalcCRM"
```

---

## Порядок и точки проверки

Задачи 1→5 — бэкенд без внешних эффектов, можно катить подряд. **Задачи 7 и 8
деплоятся только вместе:** сборщик строк уже возвращает блок, а выравнивание блока
появляется в 8 — между ними `update` может затереть соседнюю сделку.

После задачи 9 обязательно прогнать `pytest tests/ -q` целиком: выгрузки трогают
общий код с реестром и возмещениями.

После деплоя на Railway — **Task 12 обязательна**. Юнит-тесты не ходят в Google
Sheets и Telegram, поэтому «строки легли» и «строки ушли» проверяются только живой
сделкой. Она заводится обычной (не `is_test` — иначе не попадёт ни в лист, ни в TG),
называется так, чтобы её не приняли за настоящую, и удаляется сразу после сверки.
