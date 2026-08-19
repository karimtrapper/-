"""Бюджет запросов к БД на списочных эндпоинтах конвертаций.

Замер до рефакторинга: список из 300 приходов делал 601 SQL-запрос — по два
на строку (converted_rub + free_rub из to_dict). На SQLite это 66 мс, на
Postgres в Railway каждый round-trip ~4 мс, отсюда 2,7 с на живом экране.

Тест держит бюджет: логика может меняться, но не ценой запроса на строку.

Запуск: cd Dev/CalcCRM && python -m pytest tests/test_conversions_perf.py -v
"""
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('SECRET_KEY', 'test-secret-key-for-pytest')
os.environ['REESTR_SYNC_ENABLED'] = '0'

import pytest
from sqlalchemy import event

import app as appmod
from app import (app as flask_app, get_session, Conversion, ConversionSource,
                 ConversionStatus, ConversionTx, PayinTx, SberIncome)

ROWS = 300          # порядок приходов за пару месяцев работы счёта
PACKS = 30


@pytest.fixture
def cli(monkeypatch):
    flask_app.config['TESTING'] = True
    monkeypatch.setenv('LOCAL_NO_AUTH', '1')
    with flask_app.test_client() as c:
        yield c


@pytest.fixture
def bulk():
    """300 приходов и 30 пачек — снести за собой обязательно, БД общая."""
    db = get_session()
    made = {'incomes': [], 'convs': [], 'txs': []}
    try:
        incs = []
        for i in range(ROWS):
            inc = SberIncome(
                uuid=uuid.uuid4().hex, operation_date=f'2026-06-{(i % 28) + 1:02d}',
                amount_rub=30000 + i, payer='Московский банк Сбербанка России',
                purpose='Зачисление средств по операциям эквайринга. '
                        'Мерчант №781003872118. Комиссия 210.00.')
            db.add(inc)
            incs.append(inc)
        db.flush()
        made['incomes'] = [i.id for i in incs]
        for k in range(PACKS):
            cv = Conversion(broker='tradex', rate_rub_usdt=86.15,
                            status=ConversionStatus.RECEIVED)
            db.add(cv)
            db.flush()
            made['convs'].append(cv.id)
            for inc in incs[k * 10:(k + 1) * 10]:
                db.add(ConversionSource(conversion_id=cv.id, sber_income_id=inc.id,
                                        amount_rub=inc.amount_rub))
            tx = PayinTx(tx_hash=uuid.uuid4().hex * 2, amount_usdt=3500, source='manual',
                         to_address='T' + 'x' * 33)
            db.add(tx)
            db.flush()
            made['txs'].append(tx.id)
            db.add(ConversionTx(conversion_id=cv.id, payin_tx_id=tx.id, amount_usdt=3500))
        db.commit()
    finally:
        db.close()
    yield made
    db = get_session()
    try:
        db.query(ConversionTx).filter(ConversionTx.conversion_id.in_(made['convs'])).delete(
            synchronize_session=False)
        db.query(ConversionSource).filter(ConversionSource.conversion_id.in_(made['convs'])).delete(
            synchronize_session=False)
        db.query(Conversion).filter(Conversion.id.in_(made['convs'])).delete(
            synchronize_session=False)
        db.query(PayinTx).filter(PayinTx.id.in_(made['txs'])).delete(synchronize_session=False)
        db.query(SberIncome).filter(SberIncome.id.in_(made['incomes'])).delete(
            synchronize_session=False)
        db.commit()
    finally:
        db.close()


class _Counter:
    """Считает запросы к БД за время вызова."""

    def __enter__(self):
        self.n = 0
        event.listen(appmod.engine, 'before_cursor_execute', self._hit)
        return self

    def _hit(self, *a, **kw):
        self.n += 1

    def __exit__(self, *exc):
        event.remove(appmod.engine, 'before_cursor_execute', self._hit)


def test_список_приходов_не_делает_запрос_на_строку(cli, bulk):
    """Было 601 запрос на 300 строк. Бюджет — единицы, независимо от объёма."""
    with _Counter() as c:
        r = cli.get('/api/sber-incomes?all=1')
    assert r.status_code == 200
    assert len(r.get_json()['incomes']) >= 300
    assert c.n <= 5, f'запросов {c.n} — вернулся N+1'


def test_список_приходов_с_конвертациями_в_бюджете(cli, bulk):
    """Тот же список со статусами конвертации. Было 663."""
    with _Counter() as c:
        r = cli.get('/api/sber-incomes?all=1&with_conversion=1')
    assert r.status_code == 200
    assert c.n <= 10, f'запросов {c.n} — вернулся N+1'


def test_реестр_обменников_в_бюджете(cli, bulk):
    """Реестр матчит WL-сделки с приходами. Было 605."""
    with _Counter() as c:
        r = cli.get('/api/reestr/all')
    assert r.status_code == 200
    assert c.n <= 15, f'запросов {c.n} — вернулся N+1'


def test_карточка_пачки_не_ходит_в_сеть(cli, monkeypatch):
    """Чтение не должно зависеть от доступности TronScan.

    Карточка дотягивала адрес кошелька прямо в GET: при недоступном TronScan
    экран висел на таймауте запроса к чужому сервису.
    """
    import uuid as _u
    from app import Conversion, ConversionTx, PayinTx, ConversionStatus

    calls = {'n': 0}

    def _boom(h):
        calls['n'] += 1
        raise AssertionError('сетевой вызов внутри чтения')

    monkeypatch.setattr(appmod, '_tron_tx_to_address', _boom)

    db = get_session()
    try:
        conv = Conversion(broker='tradex', rate_rub_usdt=86.15,
                          status=ConversionStatus.RECEIVED)
        db.add(conv)
        db.flush()
        tx = PayinTx(tx_hash=_u.uuid4().hex * 2, amount_usdt=100, source='manual')
        db.add(tx)
        db.flush()
        db.add(ConversionTx(conversion_id=conv.id, payin_tx_id=tx.id, amount_usdt=100))
        db.commit()
        cid, tid = conv.id, tx.id
    finally:
        db.close()

    r = cli.get(f'/api/conversions/{cid}')
    assert r.status_code == 200
    assert calls['n'] == 0, 'GET карточки ходил в сеть'
    assert r.get_json()['txs'][0]['to_address'] is None

    db = get_session()
    try:
        db.query(ConversionTx).filter(ConversionTx.conversion_id == cid).delete()
        db.query(Conversion).filter(Conversion.id == cid).delete()
        db.query(PayinTx).filter(PayinTx.id == tid).delete()
        db.commit()
    finally:
        db.close()
