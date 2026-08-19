# Конвертации рублёвых поступлений — план реализации (Фаза 1)

> **Для агентов:** шаги в чекбоксах, TDD, коммит после каждой задачи.

**Цель:** по каждому рублёвому поступлению видно, сконвертировано оно или нет, в какой
пачке, по какому курсу и сколько USDT на него пришлось.

**Архитектура:** три таблицы — `Conversion` (пачка), `ConversionSource` (доли поступлений),
`ConversionTx` (приходы USDT через существующий `PayinTx`). Доли USDT по сделкам не
вводятся, а выводятся: `U_i = R × доля_i / G`. Зеркало `Reimbursement` + `ReimbursementTx(Use)`.

**Стек:** Flask + SQLAlchemy, таблицы создаются `Base.metadata.create_all`, тесты pytest,
фронт — секция в `static/crm/crm.html`.

**Спека:** [2026-08-19-conversions.md](../specs/2026-08-19-conversions.md)

**Принятые дефолты:** факт выписки главнее расчёта по ставке · кошелёк выбирается,
подставляется последний по брокеру · перебор над остатком счёта разрешён с
предупреждением · доступ как у админа CRM · статус «не состоялась» есть · приходы
без сделки показываются строками без сделки.

---

### Task 1: Модели

**Файлы:** Изменить `app.py` (после `PayinTxUse`, ~строка 902)

- [ ] **Шаг 1: Тест на создание пачки и остаток поступления**

`tests/test_conversions.py`:

```python
"""Учёт конвертаций: пачка собирает рублёвые поступления, приход USDT разносится по ним.

Кейс 11.08 TRADEX: 144 435,47 ₽ → 1 732,8791 USDT @ 83,35 из трёх поступлений.
Доли, которые раньше правились руками через API, должны считаться сами.

Запуск: cd Dev/CalcCRM && python -m pytest tests/test_conversions.py -v
"""
import os, sys, uuid
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('SECRET_KEY', 'test-secret-key-for-pytest')
os.environ['REESTR_SYNC_ENABLED'] = '0'

import pytest
import app as appmod
from app import (app as flask_app, get_session, Conversion, ConversionSource,
                 ConversionTx, ConversionStatus, SberIncome, Deal, DealStatus,
                 DealType, PayInMethod, PayinTx, PayinTxUse)


def _uid():
    return uuid.uuid4().hex


@pytest.fixture
def cli(monkeypatch):
    flask_app.config['TESTING'] = True
    monkeypatch.setenv('LOCAL_NO_AUTH', '1')
    monkeypatch.setattr(appmod, 'sync_deals_to_gsheet', lambda *a, **kw: None)
    monkeypatch.setattr(appmod, '_send_deal_telegram', lambda *a, **kw: None)
    with flask_app.test_client() as c:
        yield c


@pytest.fixture
def incomes():
    """Три поступления пачки 11.08."""
    db = get_session()
    made = []
    try:
        for amount, payer in ((27786.44, 'Захаров'), (35000.0, 'Roman'), (83000.0, 'Olya')):
            inc = SberIncome(uuid=_uid(), operation_date='2026-08-11',
                             amount_rub=amount, payer=payer, purpose='тест')
            db.add(inc); db.flush(); made.append(inc.id)
        db.commit()
    finally:
        db.close()
    yield made
    db = get_session()
    try:
        db.query(ConversionSource).filter(ConversionSource.sber_income_id.in_(made)).delete(
            synchronize_session=False)
        db.query(SberIncome).filter(SberIncome.id.in_(made)).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def test_free_rub_учитывает_доли(incomes):
    """Поступление конвертируется частями — остаток считается по долям."""
    db = get_session()
    try:
        conv = Conversion(broker='TRADEX', rate_rub_usdt=83.35)
        db.add(conv); db.flush()
        db.add(ConversionSource(conversion_id=conv.id, sber_income_id=incomes[2],
                                amount_rub=50000.0))
        db.commit()
        inc = db.query(SberIncome).get(incomes[2])
        assert inc.converted_rub() == 50000.0
        assert inc.free_rub() == 33000.0
        db.query(ConversionSource).filter(ConversionSource.conversion_id == conv.id).delete()
        db.query(Conversion).filter(Conversion.id == conv.id).delete()
        db.commit()
    finally:
        db.close()
```

- [ ] **Шаг 2: Запустить, убедиться что падает**

`cd Dev/CalcCRM && python -m pytest tests/test_conversions.py -v`
Ожидание: `ImportError: cannot import name 'Conversion'`

- [ ] **Шаг 3: Модели в `app.py` после `PayinTxUse`**

```python
class ConversionStatus(str, Enum):
    DRAFT = 'draft'          # собираем состав, рубли ещё не ушли
    SENT = 'sent'            # рубли ушли брокеру, USDT ждём
    RECEIVED = 'received'    # USDT пришёл, доли разнесены
    CANCELLED = 'cancelled'  # не состоялась — поступления вернулись в свободные


class Conversion(Base):
    """Пачка конвертации: рублёвые поступления → рубли брокеру → USDT на кошелёк.

    Зеркало Reimbursement, только на входе. Возмещение раздаёт исходящий перевод
    по сделкам; конвертация собирает входящие рубли и раздаёт полученный USDT.
    Без неё связь «эти рубли → этот приход USDT» жила только в голове операциониста:
    доли PayinTxUse вбивались руками, и один перевод дважды съедал остаток
    (кейс хеша 2783…494 на сделках #469/#481).
    """
    __tablename__ = 'conversions'
    id = Column(Integer, primary_key=True)
    broker = Column(String(100))
    request_no = Column(String(60))            # заявка №46, поруч. 67
    sent_at = Column(DateTime)
    # Удержание — наша комиссия с конвертации (налоги + вознаграждение реферала),
    # НЕ расход. Внутрь не раскладываем. Ставка правится: по факту выписки сверх
    # фикса выходило и 0,2006 % (11.08), и 0,4005 % (13.08).
    held_percent = Column(Float, default=0.3)
    held_fixed_rub = Column(Float, default=40.0)
    amount_rub_sent = Column(Float)            # факт из выписки; пусто → расчётное
    rate_rub_usdt = Column(Float)
    wallet_id = Column(Integer, ForeignKey('wallets.id'), nullable=True)
    status = Column(SQLEnum(ConversionStatus), default=ConversionStatus.DRAFT)
    notes = Column(Text)
    created_by = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow)
    received_at = Column(DateTime)
    sources = relationship('ConversionSource', back_populates='conversion',
                           cascade='all, delete-orphan')
    txs = relationship('ConversionTx', back_populates='conversion',
                       cascade='all, delete-orphan')

    @property
    def display_name(self):
        return f'CNV-{self.id:04d}' if self.id else 'CNV-новая'

    def sources_rub(self):
        """Σ привязанных поступлений (G)."""
        return round(sum(s.amount_rub or 0 for s in (self.sources or [])), 2)

    def held_rub(self):
        """Удержание: расчётное по ставке, либо фактическое, если отправка из выписки."""
        g = self.sources_rub()
        if self.amount_rub_sent:
            return round(g - self.amount_rub_sent, 2)
        return round(g * (self.held_percent or 0) / 100 + (self.held_fixed_rub or 0), 2)

    def sent_rub(self):
        """Отправлено брокеру (S). Факт выписки главнее расчёта."""
        if self.amount_rub_sent:
            return round(self.amount_rub_sent, 2)
        return round(self.sources_rub() - self.held_rub(), 2)

    def expected_usdt(self):
        rate = self.rate_rub_usdt or 0
        return round(self.sent_rub() / rate, 4) if rate else 0.0

    def received_usdt(self):
        """Σ привязанных приходов USDT (R)."""
        return round(sum(t.amount_usdt or 0 for t in (self.txs or [])), 4)

    def delta_usdt(self):
        return round(self.received_usdt() - self.expected_usdt(), 4)

    def to_dict(self):
        return {
            'id': self.id, 'display_name': self.display_name,
            'broker': self.broker, 'request_no': self.request_no,
            'sent_at': self.sent_at.isoformat() if self.sent_at else None,
            'held_percent': self.held_percent, 'held_fixed_rub': self.held_fixed_rub,
            'held_rub': self.held_rub(),
            'sources_rub': self.sources_rub(), 'sent_rub': self.sent_rub(),
            'rate_rub_usdt': self.rate_rub_usdt,
            'expected_usdt': self.expected_usdt(),
            'received_usdt': self.received_usdt(),
            'delta_usdt': self.delta_usdt(),
            'wallet_id': self.wallet_id,
            'status': self.status.value if self.status else None,
            'notes': self.notes, 'created_by': self.created_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'received_at': self.received_at.isoformat() if self.received_at else None,
        }


class ConversionSource(Base):
    """Какой долей рублёвое поступление вошло в пачку.

    Долями, а не целиком: 200 000 от Имайкиной закрывали часть сделки на 800 000,
    а 14.08 конвертировали больше, чем пришло, добирая из буфера счёта.
    """
    __tablename__ = 'conversion_sources'
    __table_args__ = (UniqueConstraint('conversion_id', 'sber_income_id',
                                       name='uq_conversion_source'),)
    id = Column(Integer, primary_key=True)
    conversion_id = Column(Integer, ForeignKey('conversions.id'), nullable=False, index=True)
    sber_income_id = Column(Integer, ForeignKey('sber_incomes.id'), nullable=False, index=True)
    amount_rub = Column(Float, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    conversion = relationship('Conversion', back_populates='sources')


class ConversionTx(Base):
    """Каким приходом USDT закрыта пачка. Брокер может дробить выдачу."""
    __tablename__ = 'conversion_txs'
    __table_args__ = (UniqueConstraint('conversion_id', 'payin_tx_id',
                                       name='uq_conversion_tx'),)
    id = Column(Integer, primary_key=True)
    conversion_id = Column(Integer, ForeignKey('conversions.id'), nullable=False, index=True)
    payin_tx_id = Column(Integer, ForeignKey('payin_txs.id'), nullable=False, index=True)
    amount_usdt = Column(Float, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    conversion = relationship('Conversion', back_populates='txs')
```

- [ ] **Шаг 4: Методы остатка в `SberIncome`** (в класс, перед `to_dict`)

```python
    def converted_rub(self):
        """Сколько из прихода уже ушло в конвертации.

        Считаем запросом, а не по коллекции: доли добавляются и читаются в рамках
        одного запроса, коллекция в памяти к этому моменту не перечитана
        (та же причина, что в ReimbursementTx.used_usdt).
        """
        from sqlalchemy import func as _f
        from sqlalchemy.orm import object_session
        s = object_session(self)
        if s is not None and self.id:
            with s.no_autoflush:
                val = s.query(_f.sum(ConversionSource.amount_rub)).join(
                    Conversion, ConversionSource.conversion_id == Conversion.id
                ).filter(ConversionSource.sber_income_id == self.id,
                         Conversion.status != ConversionStatus.CANCELLED).scalar()
            return round(val or 0, 2)
        return 0.0

    def free_rub(self):
        """Не сконвертировано по этому приходу."""
        return round((self.amount_rub or 0) - self.converted_rub(), 2)
```

И в `SberIncome.to_dict()` добавить в возвращаемый словарь:

```python
            'converted_rub': self.converted_rub(),
            'free_rub': self.free_rub(),
```

- [ ] **Шаг 5: Тест зелёный**

`python -m pytest tests/test_conversions.py -v` → PASS

- [ ] **Шаг 6: Коммит**

```bash
git add app.py tests/test_conversions.py
git commit -m "feat(conversions): модели Conversion/ConversionSource/ConversionTx + остаток по приходу"
```

---

### Task 2: Разнос USDT по сделкам

**Файлы:** Изменить `app.py` (функция рядом с `_sync_sber_claims`), тест в `tests/test_conversions.py`

- [ ] **Шаг 1: Тест на кейсе 11.08**

```python
def test_разнос_usdt_воспроизводит_ручные_доли(incomes):
    """Кейс 11.08 TRADEX: 1 732,8791 USDT на три поступления.

    Эталон — доли, которые 17.08 правились руками через API:
    #469 → 330,28, #481 → 416,02, #495 → 986,57.
    """
    from app import _conversion_shares
    shares = _conversion_shares(
        sources=[(incomes[0], 27786.44), (incomes[1], 35000.0), (incomes[2], 83000.0)],
        received_usdt=1732.8791,
    )
    assert shares[incomes[0]] == 330.28
    assert shares[incomes[1]] == 416.02
    assert shares[incomes[2]] == 986.57
    # По построению Σ долей = полученному переводу, двойного учёта не бывает
    assert round(sum(shares.values()), 2) == 1732.88


def test_разнос_нулевой_базы_не_падает():
    from app import _conversion_shares
    assert _conversion_shares(sources=[], received_usdt=100.0) == {}
    assert _conversion_shares(sources=[(1, 0.0)], received_usdt=100.0) == {1: 0.0}
```

- [ ] **Шаг 2: Запустить, убедиться что падает** — `ImportError: _conversion_shares`

- [ ] **Шаг 3: Реализация**

```python
def _conversion_shares(sources, received_usdt):
    """Разнести полученный USDT по поступлениям пропорционально рублям.

    U_i = R × доля_i / G. Пропорция автоматически размазывает и удержание,
    и расхождение с брокером (Δ), и всегда даёт Σ U_i = R — то есть перевод
    физически не может быть учтён дважды.

    sources — [(sber_income_id, amount_rub)], возвращает {sber_income_id: usdt}.
    """
    total_rub = round(sum(a or 0 for _, a in sources), 2)
    if not sources:
        return {}
    if total_rub <= 0:
        return {sid: 0.0 for sid, _ in sources}
    return {sid: round((received_usdt or 0) * (amt or 0) / total_rub, 2)
            for sid, amt in sources}
```

- [ ] **Шаг 4: Тест зелёный** — `python -m pytest tests/test_conversions.py -v`

- [ ] **Шаг 5: Коммит**

```bash
git add app.py tests/test_conversions.py
git commit -m "feat(conversions): пропорциональный разнос USDT по поступлениям"
```

---

### Task 3: API — создание и чтение пачки

**Файлы:** Изменить `app.py` (рядом с `/api/sber-incomes`, ~строка 4740)

- [ ] **Шаг 1: Тест**

```python
def test_создание_пачки_с_поступлениями(cli, incomes):
    r = cli.post('/api/conversions', json={
        'broker': 'БРАЙТУМ/TRADEX', 'request_no': 'заявка №46',
        'rate_rub_usdt': 83.35,
        'sources': [{'sber_income_id': incomes[0], 'amount_rub': 27786.44},
                    {'sber_income_id': incomes[1], 'amount_rub': 35000.0},
                    {'sber_income_id': incomes[2], 'amount_rub': 83000.0}],
    })
    assert r.status_code == 200, r.get_data(as_text=True)
    conv = r.get_json()['conversion']
    assert conv['sources_rub'] == 145786.44
    # Удержание по дефолту 0,3 % + 40
    assert conv['held_rub'] == 477.36
    assert conv['display_name'].startswith('CNV-')
    cli.delete(f"/api/conversions/{conv['id']}")


def test_нельзя_забрать_больше_остатка(cli, incomes):
    r = cli.post('/api/conversions', json={
        'broker': 'TRADEX', 'rate_rub_usdt': 83.35,
        'sources': [{'sber_income_id': incomes[0], 'amount_rub': 99999.0}],
    })
    assert r.status_code == 409
    assert 'доступно' in r.get_json()['error']
```

- [ ] **Шаг 2: Запустить, убедиться что падает** — 404 на `/api/conversions`

- [ ] **Шаг 3: Эндпоинты**

```python
@app.route('/api/conversions', methods=['GET'])
def list_conversions():
    """Список пачек конвертации, свежие сверху."""
    db = get_session()
    try:
        rows = db.query(Conversion).order_by(Conversion.id.desc()).limit(200).all()
        return jsonify({'success': True, 'conversions': [c.to_dict() for c in rows]})
    finally:
        db.close()


@app.route('/api/conversions/<int:conv_id>', methods=['GET'])
def get_conversion(conv_id):
    """Пачка с составом: какие поступления вошли, сколько USDT на каждое, чьи сделки."""
    db = get_session()
    try:
        conv = db.query(Conversion).get(conv_id)
        if not conv:
            return jsonify({'success': False, 'error': 'not_found'}), 404
        pairs = [(s.sber_income_id, s.amount_rub) for s in conv.sources]
        shares = _conversion_shares(pairs, conv.received_usdt())
        composition = []
        for s in conv.sources:
            inc = db.query(SberIncome).get(s.sber_income_id)
            deal = db.query(Deal).get(inc.claimed_deal_id) if inc and inc.claimed_deal_id else None
            composition.append({
                'sber_income_id': s.sber_income_id,
                'amount_rub': round(s.amount_rub or 0, 2),
                'usdt': shares.get(s.sber_income_id, 0.0),
                'payer': inc.payer if inc else None,
                'operation_date': inc.operation_date if inc else None,
                'deal_id': deal.id if deal else None,
                'client_name': (deal.client_name if deal else None),
            })
        txs = []
        for t in conv.txs:
            tx = db.query(PayinTx).get(t.payin_tx_id)
            txs.append({'tx_hash': tx.tx_hash if tx else '', 'amount_usdt': t.amount_usdt})
        return jsonify({'success': True, 'conversion': conv.to_dict(),
                        'composition': composition, 'txs': txs})
    finally:
        db.close()


def _attach_sources(db, conv, sources_req, force=False):
    """Привязать поступления к пачке долями. Бросает ValueError при переборе.

    Перебор над остатком счёта возможен осознанно (14.08 конвертировали больше,
    чем пришло, добирая из буфера) — поэтому force снимает запрет, но молча
    это не проходит.
    """
    db.query(ConversionSource).filter(ConversionSource.conversion_id == conv.id).delete()
    db.flush()
    for item in sources_req or []:
        sid = int(item.get('sber_income_id'))
        inc = db.query(SberIncome).filter(SberIncome.id == sid).with_for_update().first()
        if not inc:
            raise ValueError(f'Приход #{sid} не найден')
        try:
            take = round(float(item.get('amount_rub') or 0), 2)
        except (TypeError, ValueError):
            raise ValueError(f'Некорректная сумма по приходу #{sid}')
        if not take:
            take = inc.free_rub()
        free = inc.free_rub()
        if take > free + 0.01 and not force:
            raise ValueError(
                f'По приходу {inc.amount_rub:,.2f} ₽ ({inc.payer or sid}) '
                f'доступно {free:,.2f} ₽, запрошено {take:,.2f} ₽')
        db.add(ConversionSource(conversion_id=conv.id, sber_income_id=sid, amount_rub=take))
    db.flush()


@app.route('/api/conversions', methods=['POST'])
def create_conversion():
    """Создать пачку: брокер, курс, ставка удержания, состав поступлений."""
    db = get_session()
    try:
        data = request.get_json(silent=True) or {}
        conv = Conversion(
            broker=(data.get('broker') or '').strip()[:100],
            request_no=(data.get('request_no') or '').strip()[:60],
            rate_rub_usdt=float(data['rate_rub_usdt']) if data.get('rate_rub_usdt') else None,
            held_percent=float(data.get('held_percent', 0.3)),
            held_fixed_rub=float(data.get('held_fixed_rub', 40.0)),
            amount_rub_sent=float(data['amount_rub_sent']) if data.get('amount_rub_sent') else None,
            wallet_id=data.get('wallet_id'),
            notes=(data.get('notes') or '').strip() or None,
            created_by=session.get('admin_username') if 'admin_username' in session else None,
            status=ConversionStatus.SENT if data.get('sent_at') else ConversionStatus.DRAFT,
            sent_at=datetime.utcnow() if data.get('sent_at') else None,
        )
        db.add(conv)
        db.flush()
        try:
            _attach_sources(db, conv, data.get('sources'), force=bool(data.get('force')))
        except ValueError as e:
            db.rollback()
            return jsonify({'success': False, 'error': str(e)}), 409
        db.commit()
        return jsonify({'success': True, 'conversion': conv.to_dict()})
    finally:
        db.close()


@app.route('/api/conversions/<int:conv_id>', methods=['DELETE'])
def delete_conversion(conv_id):
    """Удалить пачку — поступления возвращаются в несконвертированные."""
    db = get_session()
    try:
        conv = db.query(Conversion).get(conv_id)
        if not conv:
            return jsonify({'success': False, 'error': 'not_found'}), 404
        _clear_conversion_payin_uses(db, conv)
        db.delete(conv)
        db.commit()
        return jsonify({'success': True})
    finally:
        db.close()
```

- [ ] **Шаг 4: Тест зелёный** — `python -m pytest tests/test_conversions.py -v`

- [ ] **Шаг 5: Коммит**

```bash
git add app.py tests/test_conversions.py
git commit -m "feat(conversions): API создания пачки с долями поступлений"
```

---

### Task 4: Привязка прихода USDT и автоматические доли по сделкам

**Файлы:** Изменить `app.py`

- [ ] **Шаг 1: Тест — самый важный в плане**

```python
def test_привязка_прихода_проставляет_доли_сделок(cli, incomes):
    """То, ради чего всё: PayinTxUse считается сам, а не правится руками.

    Кейс 17.08: 1733 USDT записали целиком на #469 (её доля 330,28), реестр решил,
    что перевод разобран, и спрятал хеш; потом #481 съела остаток 1402,72
    вместо своих 416,02.
    """
    db = get_session()
    deal_ids = []
    try:
        for inc_id, name in zip(incomes, ('Захаров', 'Roman', 'Olya')):
            d = Deal(deal_type=DealType.RUB_TO_THB, status=DealStatus.PENDING,
                     client_name=name, payin_method=PayInMethod.SBER_WL)
            db.add(d); db.flush()
            deal_ids.append(d.id)
            db.query(SberIncome).filter(SberIncome.id == inc_id).update(
                {'claimed_deal_id': d.id})
        db.commit()
    finally:
        db.close()

    conv = cli.post('/api/conversions', json={
        'broker': 'TRADEX', 'rate_rub_usdt': 83.35, 'amount_rub_sent': 144435.47,
        'sources': [{'sber_income_id': incomes[0], 'amount_rub': 27786.44},
                    {'sber_income_id': incomes[1], 'amount_rub': 35000.0},
                    {'sber_income_id': incomes[2], 'amount_rub': 83000.0}],
    }).get_json()['conversion']

    tx_hash = _uid() + _uid()
    r = cli.post(f"/api/conversions/{conv['id']}/txs", json={
        'tx_hash': tx_hash, 'amount_usdt': 1732.8791})
    assert r.status_code == 200, r.get_data(as_text=True)

    db = get_session()
    try:
        tx = db.query(PayinTx).filter(PayinTx.tx_hash == tx_hash).first()
        uses = {u.deal_id: u.amount_usdt
                for u in db.query(PayinTxUse).filter(PayinTxUse.tx_id == tx.id).all()}
        assert uses[deal_ids[0]] == 330.28
        assert uses[deal_ids[1]] == 416.02
        assert uses[deal_ids[2]] == 986.57
        # Остаток разобран полностью — хеш больше не «свободен» и не уйдёт в чужую сделку
        assert tx.free_usdt() == 0.0
        db.query(PayinTxUse).filter(PayinTxUse.tx_id == tx.id).delete()
        db.query(PayinTx).filter(PayinTx.id == tx.id).delete()
        db.query(Deal).filter(Deal.id.in_(deal_ids)).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()
    cli.delete(f"/api/conversions/{conv['id']}")
```

- [ ] **Шаг 2: Запустить, убедиться что падает** — 404 на `/txs`

- [ ] **Шаг 3: Реализация**

```python
def _clear_conversion_payin_uses(db, conv):
    """Снять доли PayinTxUse, проставленные этой пачкой (перед пересчётом/удалением)."""
    tx_ids = [t.payin_tx_id for t in conv.txs]
    if not tx_ids:
        return
    db.query(PayinTxUse).filter(PayinTxUse.tx_id.in_(tx_ids)).delete(synchronize_session=False)
    db.flush()


def _apply_conversion_shares(db, conv):
    """Разнести полученный USDT по сделкам поступлений пачки.

    Одна сделка может забрать несколько поступлений — доли суммируются.
    Поступление без сделки просто пропускается: конвертировать приход,
    у которого сделки ещё нет, разрешено (порядок «приход → конвертация →
    USDT → сделка»).
    """
    _clear_conversion_payin_uses(db, conv)
    pairs = [(s.sber_income_id, s.amount_rub) for s in conv.sources]
    shares = _conversion_shares(pairs, conv.received_usdt())
    per_deal = {}
    for sid, usdt in shares.items():
        inc = db.query(SberIncome).get(sid)
        if not inc or not inc.claimed_deal_id:
            continue
        per_deal[inc.claimed_deal_id] = round(per_deal.get(inc.claimed_deal_id, 0) + usdt, 2)
    if not per_deal or not conv.txs:
        return
    # Доли вешаем на первый перевод пачки: брокер обычно шлёт одним, а при
    # дроблении разбивка по переводам роли не играет — важна сумма на сделку.
    tx_id = conv.txs[0].payin_tx_id
    for deal_id, amount in per_deal.items():
        db.add(PayinTxUse(tx_id=tx_id, deal_id=deal_id, amount_usdt=amount))
    db.flush()


@app.route('/api/conversions/<int:conv_id>/txs', methods=['POST'])
def attach_conversion_tx(conv_id):
    """Привязать приход USDT к пачке и разнести доли по сделкам."""
    db = get_session()
    try:
        conv = db.query(Conversion).get(conv_id)
        if not conv:
            return jsonify({'success': False, 'error': 'not_found'}), 404
        data = request.get_json(silent=True) or {}
        h = str(data.get('tx_hash') or '').strip()
        if not h:
            return jsonify({'success': False, 'error': 'Нужен хеш прихода'}), 400
        tx = db.query(PayinTx).filter(PayinTx.tx_hash == h).first()
        if tx is None:
            onchain = _tron_tx_amount(h)
            amount = onchain if onchain is not None else float(data.get('amount_usdt') or 0)
            tx = PayinTx(tx_hash=h, amount_usdt=amount,
                         source='tronscan' if onchain is not None else 'manual')
            db.add(tx)
            db.flush()
        take = round(float(data.get('amount_usdt') or tx.amount_usdt or 0), 4)
        existing = db.query(ConversionTx).filter(
            ConversionTx.conversion_id == conv.id,
            ConversionTx.payin_tx_id == tx.id).first()
        if existing:
            existing.amount_usdt = take
        else:
            db.add(ConversionTx(conversion_id=conv.id, payin_tx_id=tx.id, amount_usdt=take))
        db.flush()
        db.refresh(conv)
        conv.status = ConversionStatus.RECEIVED
        conv.received_at = datetime.utcnow()
        _apply_conversion_shares(db, conv)
        db.commit()
        return jsonify({'success': True, 'conversion': conv.to_dict()})
    finally:
        db.close()
```

- [ ] **Шаг 4: Тест зелёный** — `python -m pytest tests/test_conversions.py -v`

- [ ] **Шаг 5: Полный прогон** — `python -m pytest -q` (ожидание: прежние 882 + новые, 0 упавших)

- [ ] **Шаг 6: Коммит**

```bash
git add app.py tests/test_conversions.py
git commit -m "feat(conversions): приход USDT разносится по сделкам автоматически"
```

---

### Task 5: Сводка «не сконвертировано» в пуле приходов

**Файлы:** Изменить `app.py` — `list_sber_incomes` (~строка 4696)

- [ ] **Шаг 1: Тест**

```python
def test_список_приходов_отдаёт_статус_конвертации(cli, incomes):
    r = cli.get('/api/sber-incomes?all=1&with_conversion=1')
    assert r.status_code == 200
    body = r.get_json()
    assert 'unconverted_rub' in body
    row = next(i for i in body['incomes'] if i['id'] == incomes[0])
    assert row['free_rub'] == 27786.44
    assert row['conversion'] is None
```

- [ ] **Шаг 2: Запустить, убедиться что падает** — нет ключа `unconverted_rub`

- [ ] **Шаг 3: Дополнить `list_sber_incomes`** — перед `return jsonify(...)`:

```python
        total_free = 0.0
        if request.args.get('with_conversion') == '1':
            by_income = {}
            for src, conv in db.query(ConversionSource, Conversion).join(
                    Conversion, ConversionSource.conversion_id == Conversion.id).filter(
                    Conversion.status != ConversionStatus.CANCELLED).all():
                by_income.setdefault(src.sber_income_id, []).append({
                    'id': conv.id, 'display_name': conv.display_name,
                    'broker': conv.broker, 'rate_rub_usdt': conv.rate_rub_usdt,
                    'amount_rub': round(src.amount_rub or 0, 2),
                    'status': conv.status.value if conv.status else None,
                })
            for r_ in rows:
                links = by_income.get(r_['id'], [])
                r_['conversion'] = links[0] if len(links) == 1 else (links or None)
                total_free += r_.get('free_rub', 0) or 0
        return jsonify({'success': True, 'incomes': rows[:300],
                        'unconverted_rub': round(total_free, 2)})
```

Старую строку `return jsonify({'success': True, 'incomes': rows[:300]})` удалить.

- [ ] **Шаг 4: Тест зелёный** — `python -m pytest tests/test_conversions.py -v`

- [ ] **Шаг 5: Коммит**

```bash
git add app.py tests/test_conversions.py
git commit -m "feat(conversions): статус конвертации и сумма несконвертированного в пуле приходов"
```

---

### Task 6: Вкладка «Поступления»

**Файлы:** Изменить `static/crm/crm.html` — навигация (строка 689), секция (после 1810), `showSection` (4953)

- [ ] **Шаг 1: Кнопка навигации** — после `data-section="reimbursements"`:

```html
            <button class="nav-tab" data-section="incomes">💵 Поступления</button>
            <button class="nav-tab" data-section="conversions">🔄 Конвертации</button>
```

- [ ] **Шаг 2: Секция** — перед `<section id="transactions"`:

```html
        <section id="incomes" class="section">
            <div class="card">
                <h2>Поступления на счёт</h2>
                <div id="incomesSummary" class="summary-row"></div>
                <table class="table">
                    <thead><tr>
                        <th>Дата</th><th>Плательщик</th><th>Сумма</th><th>Вид</th>
                        <th>Сделка</th><th>Конвертация</th>
                    </tr></thead>
                    <tbody id="incomesTable"></tbody>
                </table>
            </div>
        </section>

        <section id="conversions" class="section">
            <div class="card">
                <h2>Конвертации</h2>
                <button class="btn btn-primary" onclick="openConversionForm()">+ Новая пачка</button>
                <table class="table">
                    <thead><tr>
                        <th>CNV</th><th>Дата</th><th>Брокер</th><th>Заявка</th>
                        <th>Отправлено ₽</th><th>Курс</th><th>Ожидали</th>
                        <th>Получили</th><th>Δ</th><th>Статус</th>
                    </tr></thead>
                    <tbody id="conversionsTable"></tbody>
                </table>
            </div>
        </section>
```

- [ ] **Шаг 3: Роутинг** — в `switch (sectionName)` после `case 'reimbursements'`:

```javascript
                case 'incomes': loadIncomes(); break;
                case 'conversions': loadConversions(); break;
```

- [ ] **Шаг 4: Загрузчик** — рядом с `loadReimbursements`:

```javascript
        async function loadIncomes() {
            const r = await fetch('/api/sber-incomes?all=1&with_conversion=1');
            const d = await r.json();
            if (!d.success) return;
            document.getElementById('incomesSummary').innerHTML =
                `<b>На счёте не сконвертировано: ${fmt(d.unconverted_rub)} ₽</b>`;
            document.getElementById('incomesTable').innerHTML = d.incomes.map(i => {
                const c = Array.isArray(i.conversion) ? i.conversion[0] : i.conversion;
                let conv;
                if (!c) conv = '<span style="color:#999">⏳ не сконвертировано</span>';
                else if (i.free_rub > 0.01)
                    conv = `🔄 частично: ${fmt(i.converted_rub)} из ${fmt(i.amount_rub)} ₽`;
                else conv = `✅ ${c.display_name} · ${c.broker || ''} · ${c.rate_rub_usdt || ''}`;
                return `<tr>
                    <td>${(i.operation_date || '').slice(0, 10)}</td>
                    <td>${i.payer || '—'}</td>
                    <td>${fmt(i.gross_rub)} ₽</td>
                    <td>${i.kind === 'acquiring' ? 'СБП' : 'реквизиты'}</td>
                    <td>${i.claimed_deal_id ? '#' + i.claimed_deal_id : '—'}</td>
                    <td>${conv}</td></tr>`;
            }).join('');
        }

        async function loadConversions() {
            const r = await fetch('/api/conversions');
            const d = await r.json();
            if (!d.success) return;
            document.getElementById('conversionsTable').innerHTML = d.conversions.map(c => `
                <tr onclick="showConversion(${c.id})" style="cursor:pointer">
                    <td>${c.display_name}</td>
                    <td>${(c.sent_at || c.created_at || '').slice(0, 10)}</td>
                    <td>${c.broker || '—'}</td><td>${c.request_no || '—'}</td>
                    <td>${fmt(c.sent_rub)} ₽</td><td>${c.rate_rub_usdt || '—'}</td>
                    <td>${fmt(c.expected_usdt)}</td><td>${fmt(c.received_usdt)}</td>
                    <td>${c.delta_usdt ? fmt(c.delta_usdt) : '—'}</td>
                    <td>${c.status}</td></tr>`).join('');
        }
```

Если хелпера `fmt` в файле нет — добавить рядом:

```javascript
        function fmt(n) {
            return (n === null || n === undefined) ? '—'
                : Number(n).toLocaleString('ru-RU', {maximumFractionDigits: 2});
        }
```

- [ ] **Шаг 5: Проверить в браузере**

```bash
cd Dev/CalcCRM && python app.py &
npx agent-browser open http://localhost:5000/crm
```
Открыть «Поступления», убедиться: сумма несконвертированного считается, статусы видны.

- [ ] **Шаг 6: Коммит**

```bash
git add static/crm/crm.html
git commit -m "feat(conversions): вкладки «Поступления» и «Конвертации»"
```

---

### Task 7: Форма создания пачки и карточка

**Файлы:** Изменить `static/crm/crm.html`

- [ ] **Шаг 1: Модалка создания** — форма с полями: брокер (текст), заявка (текст),
курс (число), удержание % (дефолт `0.3`) и фикс ₽ (дефолт `40`), отправлено ₽
(необязательно — факт выписки), кошелёк (select из `/api/wallets`), и список
несконвертированных приходов чекбоксами с редактируемой долей.

```javascript
        async function openConversionForm() {
            const r = await fetch('/api/sber-incomes?all=1&with_conversion=1');
            const d = await r.json();
            const free = d.incomes.filter(i => (i.free_rub || 0) > 0.01);
            const rows = free.map(i => `
                <label style="display:block">
                    <input type="checkbox" class="convSrc" value="${i.id}"
                           data-free="${i.free_rub}">
                    ${(i.operation_date || '').slice(0, 10)} · ${i.payer || '—'} ·
                    ${fmt(i.free_rub)} ₽
                    <input type="number" step="0.01" class="convSrcAmt"
                           value="${i.free_rub}" style="width:120px">
                </label>`).join('');
            document.getElementById('conversionModalBody').innerHTML = `
                <input id="convBroker" placeholder="Брокер (БРАЙТУМ/TRADEX)">
                <input id="convRequest" placeholder="Заявка (№46)">
                <input id="convRate" type="number" step="0.0001" placeholder="Курс (83.35)">
                <input id="convHeldPct" type="number" step="0.01" value="0.3">
                <input id="convHeldFix" type="number" step="1" value="40">
                <input id="convSent" type="number" step="0.01"
                       placeholder="Отправлено ₽ (факт выписки, если известен)">
                <div>${rows || 'Несконвертированных приходов нет'}</div>
                <button class="btn btn-primary" onclick="saveConversion()">Создать</button>`;
            document.getElementById('conversionModal').style.display = 'block';
        }

        async function saveConversion() {
            const sources = [...document.querySelectorAll('.convSrc:checked')].map(cb => ({
                sber_income_id: Number(cb.value),
                amount_rub: Number(cb.parentElement.querySelector('.convSrcAmt').value),
            }));
            const body = {
                broker: document.getElementById('convBroker').value,
                request_no: document.getElementById('convRequest').value,
                rate_rub_usdt: Number(document.getElementById('convRate').value) || null,
                held_percent: Number(document.getElementById('convHeldPct').value),
                held_fixed_rub: Number(document.getElementById('convHeldFix').value),
                amount_rub_sent: Number(document.getElementById('convSent').value) || null,
                sources, sent_at: true,
            };
            const r = await fetch('/api/conversions', {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(body)});
            const d = await r.json();
            if (!d.success) return alert(d.error);
            document.getElementById('conversionModal').style.display = 'none';
            loadConversions();
        }
```

- [ ] **Шаг 2: Карточка пачки `showConversion(id)`** — тянет `/api/conversions/<id>`,
рисует лестницу (поступления → удержание → отправлено → курс → получено → Δ),
состав с долями в ₽ и USDT и сделками, и поле привязки хеша прихода:

```javascript
        async function showConversion(id) {
            const d = await (await fetch(`/api/conversions/${id}`)).json();
            if (!d.success) return;
            const c = d.conversion;
            const comp = d.composition.map(x => `<tr>
                <td>${(x.operation_date || '').slice(0, 10)}</td>
                <td>${x.payer || '—'}</td><td>${fmt(x.amount_rub)} ₽</td>
                <td>${fmt(x.usdt)} USDT</td>
                <td>${x.deal_id ? '#' + x.deal_id + ' ' + (x.client_name || '') : '⏳ сделки нет'}</td>
            </tr>`).join('');
            document.getElementById('conversionModalBody').innerHTML = `
                <h3>${c.display_name} · ${c.broker || ''} ${c.request_no || ''}</h3>
                <pre>Поступления      ${fmt(c.sources_rub)} ₽
Удержано         ${fmt(c.held_rub)} ₽  (${c.held_percent}% + ${c.held_fixed_rub})
Отправлено       ${fmt(c.sent_rub)} ₽  @ ${c.rate_rub_usdt || '—'}
Ожидали          ${fmt(c.expected_usdt)} USDT
Получили         ${fmt(c.received_usdt)} USDT
Δ                ${fmt(c.delta_usdt)} USDT</pre>
                <table class="table"><tbody>${comp}</tbody></table>
                <input id="convTxHash" placeholder="Хеш прихода USDT">
                <input id="convTxAmt" type="number" step="0.0001" placeholder="Сумма USDT">
                <button class="btn" onclick="attachConvTx(${id})">Привязать приход</button>`;
            document.getElementById('conversionModal').style.display = 'block';
        }

        async function attachConvTx(id) {
            const r = await fetch(`/api/conversions/${id}/txs`, {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    tx_hash: document.getElementById('convTxHash').value.trim(),
                    amount_usdt: Number(document.getElementById('convTxAmt').value) || null})});
            const d = await r.json();
            if (!d.success) return alert(d.error);
            showConversion(id);
            loadConversions();
        }
```

- [ ] **Шаг 3: Разметка модалки** — добавить в конец `<div class="container">`:

```html
        <div id="conversionModal" class="modal" style="display:none">
            <div class="modal-content">
                <span class="modal-close"
                      onclick="document.getElementById('conversionModal').style.display='none'">&times;</span>
                <div id="conversionModalBody"></div>
            </div>
        </div>
```

- [ ] **Шаг 4: Проверить в браузере** — создать пачку из трёх приходов, привязать хеш,
убедиться что доли по сделкам проставились.

- [ ] **Шаг 5: Коммит**

```bash
git add static/crm/crm.html
git commit -m "feat(conversions): форма создания пачки и карточка с лестницей"
```

---

### Task 8: Конвертация в карточке сделки

**Файлы:** Изменить `static/crm/crm.html` — блок прихода в карточке сделки

- [ ] **Шаг 1: В рендере прихода** заменить показ голого хеша на строку с пачкой:
если у сделки есть приход из пула с конвертацией — `CNV-0042 · TRADEX · 83,35 · 330,28 USDT`
со ссылкой `showConversion(id)`; если нет — `⏳ ждёт конвертации`.

Данные брать из `/api/sber-incomes?all=1&with_conversion=1`, фильтруя по
`claimed_deal_id === dealId`.

- [ ] **Шаг 2: Проверить в браузере** на сделке из тестовой пачки

- [ ] **Шаг 3: Полный прогон** — `python -m pytest -q`

- [ ] **Шаг 4: Коммит и деплой**

```bash
git add static/crm/crm.html
git commit -m "feat(conversions): конвертация видна в карточке сделки"
git push
```

Дождаться Railway SUCCESS, проверить прод: `curl -s https://grusha.up.railway.app/api/conversions`

---

## После Фазы 1

- Обновить `.claude/docs/CLAUDE-calccrm.md` — новые модели и вкладки
- Обновить `wiki/projects/reconciliation-dashboard.md` — статус «Ф1 реализована»
- Ф2: списания из выписки (снять фильтр `CREDIT` в `Dev/SberNotifier/notifier.py:190`),
  автоподбор хеша по сумме ±1 %, алерт на перебор
