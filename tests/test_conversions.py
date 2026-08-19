"""Учёт конвертаций: пачка собирает рублёвые поступления, приход USDT разносится по ним.

Кейс 11.08 TRADEX: 144 435,47 ₽ → 1 732,8791 USDT @ 83,35 из трёх поступлений.
Доли, которые 17.08 правились руками через API (#469 → 330,28, #481 → 416,02),
должны считаться сами — ради этого всё и делается.

Запуск: cd Dev/CalcCRM && python -m pytest tests/test_conversions.py -v
"""
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('SECRET_KEY', 'test-secret-key-for-pytest')
os.environ['REESTR_SYNC_ENABLED'] = '0'

import json

import pytest

import app as appmod
from app import (app as flask_app, get_session, Conversion, ConversionSource,
                 ConversionStatus, SberIncome, Deal, DealStatus, DealType,
                 PayInMethod, PayinTx, PayinTxUse)


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
    """Три поступления пачки 11.08 — Захаров, Roman, Olya."""
    db = get_session()
    made = []
    try:
        for amount, payer in ((27786.44, 'Захаров'), (35000.0, 'Roman'), (83000.0, 'Olya')):
            inc = SberIncome(uuid=_uid(), operation_date='2026-08-11',
                             amount_rub=amount, payer=payer, purpose='тест конвертаций')
            db.add(inc)
            db.flush()
            made.append(inc.id)
        db.commit()
    finally:
        db.close()
    yield made
    db = get_session()
    try:
        db.query(ConversionSource).filter(
            ConversionSource.sber_income_id.in_(made)).delete(synchronize_session=False)
        db.query(SberIncome).filter(SberIncome.id.in_(made)).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def test_free_rub_учитывает_доли(incomes):
    """Поступление конвертируется частями — остаток считается по долям."""
    db = get_session()
    try:
        conv = Conversion(broker='TRADEX', rate_rub_usdt=83.35)
        db.add(conv)
        db.flush()
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


def test_отменённая_пачка_освобождает_приход(incomes):
    """Пачка не состоялась — рубли снова считаются несконвертированными."""
    db = get_session()
    try:
        conv = Conversion(broker='TRADEX', rate_rub_usdt=83.35,
                          status=ConversionStatus.CANCELLED)
        db.add(conv)
        db.flush()
        db.add(ConversionSource(conversion_id=conv.id, sber_income_id=incomes[0],
                                amount_rub=27786.44))
        db.commit()
        inc = db.query(SberIncome).get(incomes[0])
        assert inc.converted_rub() == 0.0
        assert inc.free_rub() == 27786.44
        db.query(ConversionSource).filter(ConversionSource.conversion_id == conv.id).delete()
        db.query(Conversion).filter(Conversion.id == conv.id).delete()
        db.commit()
    finally:
        db.close()


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
    # Наибольшая доля добирает хвост округления (986,57 + 0,0091)
    assert shares[incomes[2]] == 986.5791
    # По построению Σ долей = полученному переводу ровно — перевод не останется
    # «частично свободным» и не уйдёт второй раз в чужую сделку
    assert sum(shares.values()) == 1732.8791


def test_разнос_нулевой_базы_не_падает():
    """Пустой состав и нулевые суммы не должны ронять делением на ноль."""
    from app import _conversion_shares
    assert _conversion_shares(sources=[], received_usdt=100.0) == {}
    assert _conversion_shares(sources=[(1, 0.0)], received_usdt=100.0) == {1: 0.0}


def test_создание_пачки_с_поступлениями(cli, incomes):
    """Пачка 11.08: три прихода, дефолтное удержание 0,3 % + 40."""
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
    assert conv['held_rub'] == 477.36        # 145786.44 × 0.3 % + 40
    assert conv['display_name'].startswith('CNV-')
    cli.delete(f"/api/conversions/{conv['id']}")


def test_факт_выписки_главнее_расчёта(cli, incomes):
    """Отправка известна из выписки — удержание считается обратным счётом."""
    r = cli.post('/api/conversions', json={
        'broker': 'TRADEX', 'rate_rub_usdt': 83.35, 'amount_rub_sent': 144435.47,
        'sources': [{'sber_income_id': incomes[0], 'amount_rub': 27786.44},
                    {'sber_income_id': incomes[1], 'amount_rub': 35000.0},
                    {'sber_income_id': incomes[2], 'amount_rub': 83000.0}],
    })
    conv = r.get_json()['conversion']
    assert conv['sent_rub'] == 144435.47
    assert conv['held_rub'] == 1350.97           # факт, а не 477,36 по ставке
    assert conv['expected_usdt'] == 1732.8791    # 144435.47 / 83.35
    cli.delete(f"/api/conversions/{conv['id']}")


def test_нельзя_забрать_больше_остатка(cli, incomes):
    """Перебор над остатком прихода без force не проходит."""
    r = cli.post('/api/conversions', json={
        'broker': 'TRADEX', 'rate_rub_usdt': 83.35,
        'sources': [{'sber_income_id': incomes[0], 'amount_rub': 99999.0}],
    })
    assert r.status_code == 409
    assert 'доступно' in r.get_json()['error']


def test_перебор_проходит_с_force(cli, incomes):
    """14.08 конвертировали больше, чем пришло, добирая из буфера — осознанно."""
    r = cli.post('/api/conversions', json={
        'broker': 'K2A', 'rate_rub_usdt': 84.3, 'force': True,
        'sources': [{'sber_income_id': incomes[0], 'amount_rub': 99999.0}],
    })
    assert r.status_code == 200, r.get_data(as_text=True)
    conv = r.get_json()['conversion']
    assert conv['sources_rub'] == 99999.0
    cli.delete(f"/api/conversions/{conv['id']}")


def test_привязка_прихода_проставляет_доли_сделок(cli, incomes, monkeypatch):
    """То, ради чего всё: PayinTxUse считается сам, а не правится руками.

    Кейс 17.08: 1733 USDT записали целиком на #469 (её доля 330,28), реестр решил,
    что перевод разобран без остатка, и спрятал хеш из выбора; следом #481 съела
    остаток 1402,72 вместо своих 416,02. Обе доли чинились через API.
    """
    monkeypatch.setattr(appmod, '_tron_tx_amount', lambda h: None)
    db = get_session()
    deal_ids = []
    try:
        for inc_id, name in zip(incomes, ('Захаров', 'Roman', 'Olya')):
            d = Deal(deal_type=DealType.PAY_IN, status=DealStatus.PENDING,
                     client_name=name, payin_method=PayInMethod.SBER_WL)
            db.add(d)
            db.flush()
            deal_ids.append(d.id)
            db.query(SberIncome).filter(SberIncome.id == inc_id).update(
                {'claimed_deal_id': d.id})
        db.commit()
    finally:
        db.close()

    conv = cli.post('/api/conversions', json={
        'broker': 'БРАЙТУМ/TRADEX', 'request_no': 'заявка №46',
        'rate_rub_usdt': 83.35, 'amount_rub_sent': 144435.47, 'sent_at': True,
        'sources': [{'sber_income_id': incomes[0], 'amount_rub': 27786.44},
                    {'sber_income_id': incomes[1], 'amount_rub': 35000.0},
                    {'sber_income_id': incomes[2], 'amount_rub': 83000.0}],
    }).get_json()['conversion']

    tx_hash = _uid() + _uid()
    r = cli.post(f"/api/conversions/{conv['id']}/txs", json={
        'tx_hash': tx_hash, 'amount_usdt': 1732.8791})
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()['conversion']['status'] == 'received'

    db = get_session()
    try:
        tx = db.query(PayinTx).filter(PayinTx.tx_hash == tx_hash).first()
        uses = {u.deal_id: u.amount_usdt
                for u in db.query(PayinTxUse).filter(PayinTxUse.tx_id == tx.id).all()}
        assert uses[deal_ids[0]] == 330.28
        assert uses[deal_ids[1]] == 416.02
        assert round(uses[deal_ids[2]], 2) == 986.58
        # Остаток разобран полностью — хеш не «свободен» и не уйдёт в чужую сделку
        assert tx.free_usdt() == 0.0
    finally:
        db.close()

    cli.delete(f"/api/conversions/{conv['id']}")
    db = get_session()
    try:
        tx = db.query(PayinTx).filter(PayinTx.tx_hash == tx_hash).first()
        # Пачку удалили — доли снялись, перевод снова свободен целиком
        assert tx.free_usdt() == round(tx.amount_usdt, 2)
        db.query(PayinTx).filter(PayinTx.id == tx.id).delete()
        db.query(Deal).filter(Deal.id.in_(deal_ids)).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def test_приход_без_сделки_не_ломает_разнос(cli, incomes, monkeypatch):
    """Конвертировать приход, у которого сделки ещё нет, разрешено."""
    monkeypatch.setattr(appmod, '_tron_tx_amount', lambda h: None)
    conv = cli.post('/api/conversions', json={
        'broker': 'TRADEX', 'rate_rub_usdt': 83.35,
        'sources': [{'sber_income_id': incomes[0], 'amount_rub': 27786.44}],
    }).get_json()['conversion']
    tx_hash = _uid() + _uid()
    r = cli.post(f"/api/conversions/{conv['id']}/txs", json={
        'tx_hash': tx_hash, 'amount_usdt': 333.37})
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()['conversion']['received_usdt'] == 333.37
    cli.delete(f"/api/conversions/{conv['id']}")
    db = get_session()
    try:
        db.query(PayinTx).filter(PayinTx.tx_hash == tx_hash).delete()
        db.commit()
    finally:
        db.close()


def test_список_приходов_отдаёт_статус_конвертации(cli, incomes):
    """Главная цифра экрана: сколько рублей лежит на счёте несконвертированными."""
    r = cli.get('/api/sber-incomes?all=1&with_conversion=1')
    assert r.status_code == 200
    body = r.get_json()
    assert 'unconverted_rub' in body
    row = next(i for i in body['incomes'] if i['id'] == incomes[0])
    assert row['free_rub'] == 27786.44
    assert row['conversion'] is None

    conv = cli.post('/api/conversions', json={
        'broker': 'TRADEX', 'rate_rub_usdt': 83.35,
        'sources': [{'sber_income_id': incomes[0], 'amount_rub': 27786.44}],
    }).get_json()['conversion']

    body = cli.get('/api/sber-incomes?all=1&with_conversion=1').get_json()
    row = next(i for i in body['incomes'] if i['id'] == incomes[0])
    assert row['free_rub'] == 0.0
    assert row['conversion']['display_name'] == conv['display_name']
    assert row['conversion']['broker'] == 'TRADEX'
    cli.delete(f"/api/conversions/{conv['id']}")


# ── Фаза 2: расход из выписки тремя строками ────────────────────────────────

@pytest.fixture
def debits():
    """Расход по пачке 11.08 тремя строками: брокеру + комиссия % + фикс.

    Проверено на выписке: 144 435,47 + 290,46 + 40 = 144 765,93 — ровно
    зачисленное. Так же сходится 13.08 (232 681 + 935,79 + 40).
    """
    from app import SberDebit
    db = get_session()
    made = []
    try:
        rows = (
            (144435.47, 'ООО БРАЙТУМ', 'оплата по агентскому договору', '46'),
            (290.46, 'МФ Корп', 'комиссия за перевод 0,2%', '47'),
            (40.0, 'МФ Корп', 'комиссия фиксированная', '48'),
        )
        for amount, payee, purpose, doc in rows:
            d = SberDebit(uuid=_uid(), operation_date='2026-08-11', amount_rub=amount,
                          payee=payee, purpose=purpose, doc_number=doc)
            db.add(d)
            db.flush()
            made.append(d.id)
        db.commit()
    finally:
        db.close()
    yield made
    from app import ConversionDebit
    db = get_session()
    try:
        db.query(ConversionDebit).filter(
            ConversionDebit.sber_debit_id.in_(made)).delete(synchronize_session=False)
        db.query(SberDebit).filter(SberDebit.id.in_(made)).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def test_вид_списания_определяется_по_назначению(debits):
    """Комиссия отличается от отправки брокеру по тексту назначения."""
    from app import SberDebit
    db = get_session()
    try:
        rows = {d.id: d for d in db.query(SberDebit).filter(SberDebit.id.in_(debits)).all()}
        assert rows[debits[0]].kind == 'broker'   # оплата по агентскому договору
        assert rows[debits[1]].kind == 'fee'      # комиссия за перевод
        assert rows[debits[2]].kind == 'fee'      # комиссия фиксированная
    finally:
        db.close()


def test_расход_частями_складывается_в_пачку(cli, incomes, debits):
    """Три списания привязываются к одной пачке: отправка и удержание — факт."""
    conv = cli.post('/api/conversions', json={
        'broker': 'БРАЙТУМ/TRADEX', 'request_no': 'заявка №46', 'rate_rub_usdt': 83.35,
        'sources': [{'sber_income_id': incomes[0], 'amount_rub': 27786.44},
                    {'sber_income_id': incomes[1], 'amount_rub': 35000.0},
                    {'sber_income_id': incomes[2], 'amount_rub': 82000.0}],
        'debits': [{'sber_debit_id': debits[0]},
                   {'sber_debit_id': debits[1]},
                   {'sber_debit_id': debits[2]}],
    })
    assert r_ok(r := conv), r.get_data(as_text=True)
    c = conv.get_json()['conversion']
    assert c['sent_rub'] == 144435.47      # Σ списаний kind=broker
    assert c['held_rub'] == 330.46         # Σ списаний kind=fee (290,46 + 40)
    assert c['expected_usdt'] == 1732.8791
    cli.delete(f"/api/conversions/{c['id']}")


def r_ok(resp):
    return resp.status_code == 200


def test_списание_нельзя_привязать_дважды(cli, incomes, debits):
    """Один платёж не должен закрывать две пачки — это двойной учёт расхода."""
    first = cli.post('/api/conversions', json={
        'broker': 'TRADEX', 'rate_rub_usdt': 83.35,
        'sources': [{'sber_income_id': incomes[0], 'amount_rub': 27786.44}],
        'debits': [{'sber_debit_id': debits[0]}],
    }).get_json()['conversion']
    second = cli.post('/api/conversions', json={
        'broker': 'K2A', 'rate_rub_usdt': 84.3,
        'sources': [{'sber_income_id': incomes[1], 'amount_rub': 35000.0}],
        'debits': [{'sber_debit_id': debits[0]}],
    })
    assert second.status_code == 409
    assert 'уже' in second.get_json()['error'].lower()
    cli.delete(f"/api/conversions/{first['id']}")


def test_ingest_принимает_расходы(cli):
    """SberNotifier шлёт приходы и расходы одним POST, идемпотентно по uuid."""
    from app import SberDebit
    import os as _os
    key = 'test-sber-ingest-key'
    _os.environ['SBER_INGEST_KEY'] = key
    uid = _uid()
    payload = {'debits': [{'uuid': uid, 'operation_date': '2026-08-11',
                           'amount_rub': 144435.47, 'payee': 'ООО БРАЙТУМ',
                           'purpose': 'оплата по агентскому договору',
                           'doc_number': '46'}]}
    r = cli.post('/api/sber-incomes/ingest', json=payload, headers={'X-Api-Key': key})
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()['created_debits'] == 1
    # повтор не создаёт дубля
    r2 = cli.post('/api/sber-incomes/ingest', json=payload, headers={'X-Api-Key': key})
    assert r2.get_json()['created_debits'] == 0
    db = get_session()
    try:
        d = db.query(SberDebit).filter(SberDebit.uuid == uid).first()
        assert d.kind == 'broker'
        assert d.payee == 'ООО БРАЙТУМ'
        db.delete(d)
        db.commit()
    finally:
        db.close()


def test_пустая_пачка_не_даёт_минус(cli):
    """Пачка без состава: фикс 40 без поступлений давал «отправлено −40 ₽»."""
    r = cli.post('/api/conversions', json={'broker': 'TRADEX', 'sources': []})
    c = r.get_json()['conversion']
    assert c['held_rub'] == 0.0
    assert c['sent_rub'] == 0.0
    assert c['expected_usdt'] == 0.0
    cli.delete(f"/api/conversions/{c['id']}")


# ── Разметка приходов: что не идёт в конвертацию ────────────────────────────

def test_исключённый_приход_не_в_счётчике(cli, incomes):
    """Арбитраж и прочее «не наше» не должно раздувать «не сконвертировано».

    Кейс: приход 9,1 млн по реквизитам — обменная сделка, к конвертации
    отношения не имеет, но висела в сумме и мешала читать экран.
    """
    before = cli.get('/api/sber-incomes?all=1&with_conversion=1').get_json()['unconverted_rub']
    r = cli.put(f'/api/sber-incomes/{incomes[2]}', json={
        'excluded': True, 'note': 'арбитраж, не обменная сделка'})
    assert r.status_code == 200, r.get_data(as_text=True)
    body = cli.get('/api/sber-incomes?all=1&with_conversion=1').get_json()
    assert body['unconverted_rub'] == round(before - 83000.0, 2)
    row = next(i for i in body['incomes'] if i['id'] == incomes[2])
    assert row['excluded'] is True
    assert row['note'] == 'арбитраж, не обменная сделка'
    # Исключённый не предлагается в пачку
    r2 = cli.post('/api/conversions', json={
        'broker': 'TRADEX', 'rate_rub_usdt': 83.35,
        'sources': [{'sber_income_id': incomes[2], 'amount_rub': 83000.0}]})
    assert r2.status_code == 409
    assert 'исключ' in r2.get_json()['error'].lower()


def test_массовая_отсечка_старых_приходов(cli, incomes):
    """До запуска учёта всё уже конвертировали — иначе экран показывает 428 млн."""
    r = cli.post('/api/sber-incomes/bulk', json={
        'before_date': '2026-08-12', 'action': 'converted_earlier'})
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()['updated'] >= 3
    body = cli.get('/api/sber-incomes?all=1&with_conversion=1').get_json()
    for iid in incomes:
        row = next(i for i in body['incomes'] if i['id'] == iid)
        assert row['excluded'] is True
        assert 'до запуска' in (row['note'] or '')


def test_приход_с_usdt_в_сделке_не_считается_несконвертированным(cli, incomes, monkeypatch):
    """Если у сделки проставлен USDT прихода — конвертация была, просто без пачки.

    Замечание Карима на проде: «всё не сконвертировано, хотя ты это к сделкам
    подцепил — странно». И правда: откуда бы взялся USDT в сделке, если рубли
    не меняли. Такие приходы — не «лежат на счёте», а «учтены в сделке, пачка
    не оформлена»: долг по учёту, а не деньги.
    """
    # Приходы фикстуры от 11.08 — сдвигаем запуск учёта в прошлое, иначе они
    # уедут в историю (см. тест ниже) и предупреждения по ним не будет
    monkeypatch.setattr(appmod, 'CONVERSIONS_LAUNCH_DATE', '2026-01-01')
    db = get_session()
    deal_id = None
    try:
        d = Deal(deal_type=DealType.PAY_IN, status=DealStatus.PENDING,
                 client_name='Кирилл', payin_method=PayInMethod.SBER_WL,
                 payin_amount_rub=27786.44, payin_amount_usdt=330.28)
        db.add(d)
        db.flush()
        deal_id = d.id
        db.query(SberIncome).filter(SberIncome.id == incomes[0]).update({'claimed_deal_id': d.id})
        db.commit()
    finally:
        db.close()

    body = cli.get('/api/sber-incomes?all=1&with_conversion=1').get_json()
    row = next(i for i in body['incomes'] if i['id'] == incomes[0])
    assert row['conv_state'] == 'in_deal'
    assert row['deal']['payin_amount_usdt'] == 330.28
    # В «не сконвертировано» такой приход не попадает — он уже обменян,
    # зато виден отдельной цифрой: пачку по нему ещё предстоит оформить.
    # Считаем по своим строкам: база общая на прогон, чужие приходы в сумме тоже
    mine = {i['id']: i for i in body['incomes'] if i['id'] in incomes}
    assert sum(i['free_rub'] for i in mine.values() if i['conv_state'] == 'pending') == 118000.0
    assert sum(i['free_rub'] for i in mine.values() if i['conv_state'] == 'in_deal') == 27786.44
    assert body['in_deal_rub'] >= 27786.44

    other = next(i for i in body['incomes'] if i['id'] == incomes[1])
    assert other['conv_state'] == 'pending'

    db = get_session()
    try:
        db.query(Deal).filter(Deal.id == deal_id).delete()
        db.commit()
    finally:
        db.close()


def test_приход_до_запуска_учёта_уходит_в_историю(cli, incomes, monkeypatch):
    """Сделка закрыта до запуска учёта — это история, а не долг по учёту.

    Рубли по ней меняли вне системы: пачки нет и не будет. Пока такие приходы
    висели как «учтено в сделке, пачка не оформлена», предупреждение занимало
    весь экран и настоящие пропуски после запуска в нём терялись.
    """
    monkeypatch.setattr(appmod, 'CONVERSIONS_LAUNCH_DATE', '2026-08-19')
    db = get_session()
    deal_id = None
    try:
        d = Deal(deal_type=DealType.PAY_IN, status=DealStatus.PENDING,
                 client_name='Roman', payin_method=PayInMethod.SBER_WL,
                 payin_amount_rub=35000.0, payin_amount_usdt=416.02)
        db.add(d)
        db.flush()
        deal_id = d.id
        db.query(SberIncome).filter(SberIncome.id == incomes[1]).update({'claimed_deal_id': d.id})
        db.commit()
    finally:
        db.close()

    body = cli.get('/api/sber-incomes?all=1&with_conversion=1').get_json()
    row = next(i for i in body['incomes'] if i['id'] == incomes[1])
    assert row['conv_state'] == 'legacy'          # 11.08 — раньше запуска 19.08
    assert body['launch_date'] == '2026-08-19'    # фронт подписывает дату в подсказке
    # Ни в остаток на счёте, ни в «пачка не оформлена» такой приход не идёт
    mine = {i['id']: i for i in body['incomes'] if i['id'] in incomes}
    assert sum(i['free_rub'] for i in mine.values() if i['conv_state'] == 'pending') == 110786.44
    assert not [i for i in mine.values() if i['conv_state'] == 'in_deal']

    db = get_session()
    try:
        db.query(Deal).filter(Deal.id == deal_id).delete()
        db.commit()
    finally:
        db.close()


def test_статусная_модель_прихода(cli, incomes, monkeypatch):
    """Приход проходит стадии: лежит → на конвертации → сконвертирован.

    Смысл среднего статуса — фиксировать связь В МОМЕНТ отправки брокеру.
    Если ждать подтверждения USDT, то к вечеру опять придётся вспоминать,
    какие сделки уходили в эту пачку.
    """
    monkeypatch.setattr(appmod, '_tron_tx_amount', lambda h: None)

    def state(iid):
        body = cli.get('/api/sber-incomes?all=1&with_conversion=1').get_json()
        return next(i for i in body['incomes'] if i['id'] == iid)

    assert state(incomes[0])['conv_state'] == 'pending'

    conv = cli.post('/api/conversions', json={
        'broker': 'TRADEX', 'request_no': '№46', 'rate_rub_usdt': 83.35, 'sent_at': True,
        'sources': [{'sber_income_id': incomes[0], 'amount_rub': 27786.44}],
    }).get_json()['conversion']
    assert conv['status'] == 'sent'

    row = state(incomes[0])
    assert row['conv_state'] == 'in_progress'      # рубли ушли, USDT ещё не подтверждён
    assert row['conversion']['status'] == 'sent'
    assert row['usdt'] is None

    tx_hash = _uid() + _uid()
    cli.post(f"/api/conversions/{conv['id']}/txs",
             json={'tx_hash': tx_hash, 'amount_usdt': 333.37})

    row = state(incomes[0])
    assert row['conv_state'] == 'converted'
    assert row['usdt'] == 333.37                   # сколько USDT пришлось на этот приход

    cli.delete(f"/api/conversions/{conv['id']}")
    assert state(incomes[0])['conv_state'] == 'pending'   # отмена вернула в свободные
    db = get_session()
    try:
        db.query(PayinTx).filter(PayinTx.tx_hash == tx_hash).delete()
        db.commit()
    finally:
        db.close()


# ── Связка прихода с WL-сделкой обменника ───────────────────────────────────

def test_приход_сопоставляется_с_wl_сделкой():
    """Приход по СБП — это оплата клиента мерчанта через WL-бот.

    Кейс: 111 811,80 ₽ на счёте от 17.08 = WL-0393 (Four exchange), клиент
    заплатил 112 600, эквайринг съел 0,7 %. Сумма в реестре бота хранится как
    gross, поэтому совпадает копейка в копейку.
    """
    from app import _match_wl_deal
    wl = [
        {'wl': 'WL-0393', 'dt': '17.08 14:20', 'merchant': 'Four exchange',
         'rub': 112600, 'usdt': 1255.45, 'status': 'paid'},
        {'wl': 'WL-0392', 'dt': '10.08 09:00', 'merchant': 'RUBLEV',
         'rub': 27786.44, 'usdt': 330.28, 'status': 'closed'},
    ]
    inc = {'operation_date': '2026-08-17T12:00:00', 'gross_rub': 112600.0, 'kind': 'acquiring'}
    m = _match_wl_deal(inc, wl)
    assert m['wl'] == 'WL-0393'
    assert m['merchant'] == 'Four exchange'

    # Другая дата — не матчим, даже если сумма совпала
    assert _match_wl_deal({'operation_date': '2026-08-01T00:00:00',
                           'gross_rub': 112600.0, 'kind': 'acquiring'}, wl) is None
    # Нет совпадения по сумме
    assert _match_wl_deal({'operation_date': '2026-08-17T12:00:00',
                           'gross_rub': 999.0, 'kind': 'acquiring'}, wl) is None


def test_неоднозначный_матч_не_привязывается():
    """Две сделки на одну сумму в один день — гадать нельзя, иначе припишем чужое."""
    from app import _match_wl_deal
    wl = [
        {'wl': 'WL-0400', 'dt': '17.08 10:00', 'merchant': 'A', 'rub': 35000, 'usdt': 1, 'status': 'paid'},
        {'wl': 'WL-0401', 'dt': '17.08 18:00', 'merchant': 'B', 'rub': 35000, 'usdt': 1, 'status': 'paid'},
    ]
    inc = {'operation_date': '2026-08-17T12:00:00', 'gross_rub': 35000.0, 'kind': 'acquiring'}
    assert _match_wl_deal(inc, wl) is None


def test_приход_отдаёт_ожидаемый_usdt_до_подтверждения(cli, incomes, monkeypatch):
    """Пока USDT не подтверждён, у прихода уже есть ожидаемая доля.

    Менеджер заводит сделку раньше, чем брокер пришлёт USDT, и вбивает сумму
    руками — так в #501 появился курс 126,70 ₽/USDT при рынке 87,93.
    Если пачка собрана, доля считается из неё, и вводить нечего.
    """
    monkeypatch.setattr(appmod, '_tron_tx_amount', lambda h: None)
    rate, sent = 86.15, 145186.00
    conv = cli.post('/api/conversions', json={
        'broker': 'tradex', 'rate_rub_usdt': rate, 'sent_at': True,
        'amount_rub_sent': sent,
        'sources': [{'sber_income_id': incomes[0], 'amount_rub': 27786.44},
                    {'sber_income_id': incomes[1], 'amount_rub': 35000.0},
                    {'sber_income_id': incomes[2], 'amount_rub': 83000.0}],
    }).get_json()['conversion']
    expected = round(sent / rate, 4)
    assert conv['expected_usdt'] == expected

    body = cli.get('/api/sber-incomes?all=1&with_conversion=1').get_json()
    row = next(i for i in body['incomes'] if i['id'] == incomes[1])
    assert row['conv_state'] == 'in_progress'
    assert row['usdt'] is None                        # фактического ещё нет
    assert row['usdt_expected'] == round(expected * 35000.0 / 145786.44, 2)

    # Пришёл USDT — ожидание сменяется фактом
    tx_hash = _uid() + _uid()
    got = 1680.0
    cli.post(f"/api/conversions/{conv['id']}/txs",
             json={'tx_hash': tx_hash, 'amount_usdt': got})
    body = cli.get('/api/sber-incomes?all=1&with_conversion=1').get_json()
    row = next(i for i in body['incomes'] if i['id'] == incomes[1])
    assert row['conv_state'] == 'converted'
    assert row['usdt'] == round(got * 35000.0 / 145786.44, 2)

    cli.delete(f"/api/conversions/{conv['id']}")
    db = get_session()
    try:
        db.query(PayinTx).filter(PayinTx.tx_hash == tx_hash).delete()
        db.commit()
    finally:
        db.close()


def test_кошелёк_получателя_сохраняется_по_хешу(cli, incomes, monkeypatch):
    """В сводке по пачке нужен кошелёк: «сколько пришло, хеш, какого кошелька».

    Адрес берём из сети вместе с суммой — с рук его не вводят.
    """
    monkeypatch.setattr(appmod, '_tron_tx_amount', lambda h: 401.19)
    monkeypatch.setattr(appmod, '_tron_tx_to_address',
                        lambda h: 'TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn')
    conv = cli.post('/api/conversions', json={
        'broker': 'tradex', 'rate_rub_usdt': 86.15, 'sent_at': True,
        'sources': [{'sber_income_id': incomes[0], 'amount_rub': 27786.44}],
    }).get_json()['conversion']
    tx_hash = _uid() + _uid()
    cli.post(f"/api/conversions/{conv['id']}/txs", json={'tx_hash': tx_hash})

    card = cli.get(f"/api/conversions/{conv['id']}").get_json()
    tx = card['txs'][0]
    assert tx['amount_usdt'] == 401.19          # сумма из сети
    assert tx['to_address'] == 'TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn'

    cli.delete(f"/api/conversions/{conv['id']}")
    db = get_session()
    try:
        db.query(PayinTx).filter(PayinTx.tx_hash == tx_hash).delete()
        db.commit()
    finally:
        db.close()


def test_кошелёк_дозаполняется_для_старых_хешей(cli, incomes, monkeypatch):
    """Хеши, привязанные до появления поля, адреса не имеют — подтягиваем при открытии.

    Иначе в сводке навсегда пустая строка «кошелёк», а перепривязывать хеш
    руками ради этого нельзя: сумма уже разнесена по сделкам.
    """
    monkeypatch.setattr(appmod, '_tron_tx_amount', lambda h: 2265.0)
    monkeypatch.setattr(appmod, '_tron_tx_to_address', lambda h: None)   # старое поведение
    conv = cli.post('/api/conversions', json={
        'broker': 'tradex', 'rate_rub_usdt': 86.15, 'sent_at': True,
        'sources': [{'sber_income_id': incomes[0], 'amount_rub': 27786.44}],
    }).get_json()['conversion']
    tx_hash = _uid() + _uid()
    cli.post(f"/api/conversions/{conv['id']}/txs", json={'tx_hash': tx_hash})
    assert cli.get(f"/api/conversions/{conv['id']}").get_json()['txs'][0]['to_address'] is None

    # Сеть снова отвечает — адрес добирается ФОНОМ, а не внутри чтения:
    # карточка не должна зависеть от доступности TronScan
    monkeypatch.setattr(appmod, '_tron_tx_to_address',
                        lambda h: 'TKkeEVf2zySaWTLyX2qPwvi6kcdHRuPxkJ')
    assert appmod.payin_address_backfill_once() >= 1
    card = cli.get(f"/api/conversions/{conv['id']}").get_json()
    assert card['txs'][0]['to_address'] == 'TKkeEVf2zySaWTLyX2qPwvi6kcdHRuPxkJ'

    db = get_session()
    try:
        tx = db.query(PayinTx).filter(PayinTx.tx_hash == tx_hash).first()
        assert tx.to_address == 'TKkeEVf2zySaWTLyX2qPwvi6kcdHRuPxkJ'   # сохранился, не разово
    finally:
        db.close()
    cli.delete(f"/api/conversions/{conv['id']}")
    db = get_session()
    try:
        db.query(PayinTx).filter(PayinTx.tx_hash == tx_hash).delete()
        db.commit()
    finally:
        db.close()


def test_дата_отправки_задаётся_явно(cli, incomes):
    """Пачку заводят задним числом — дата платежа не равна дате создания.

    В сводке «CNV-0001 · tradex · 93 · 2026-08-19» стояла дата создания,
    хотя деньги ушли 17-го: по такой сводке задачу не поставишь.
    """
    conv = cli.post('/api/conversions', json={
        'broker': 'tradex', 'rate_rub_usdt': 86.15, 'sent_at': '2026-08-17',
        'sources': [{'sber_income_id': incomes[0], 'amount_rub': 27786.44}],
    }).get_json()['conversion']
    assert conv['sent_at'][:10] == '2026-08-17'
    assert conv['status'] == 'sent'
    cli.delete(f"/api/conversions/{conv['id']}")


def test_дата_отправки_берётся_из_списания(cli, incomes, debits):
    """Если списание из выписки привязано — дату берём из него, а не с рук."""
    conv = cli.post('/api/conversions', json={
        'broker': 'tradex', 'rate_rub_usdt': 86.15, 'sent_at': True,
        'sources': [{'sber_income_id': incomes[0], 'amount_rub': 27786.44}],
        'debits': [{'sber_debit_id': debits[0]}],
    }).get_json()['conversion']
    assert conv['sent_at'][:10] == '2026-08-11'   # operation_date списания
    cli.delete(f"/api/conversions/{conv['id']}")


def test_пачку_можно_поправить_не_пересоздавая(cli, incomes, monkeypatch):
    """Опечатка в курсе или дате не должна стоить пересоздания пачки.

    Пересоздание снимает доли USDT со сделок и обнуляет привязку прихода —
    цена опечатки несоразмерна.
    """
    monkeypatch.setattr(appmod, '_tron_tx_amount', lambda h: 2265.0)
    monkeypatch.setattr(appmod, '_tron_tx_to_address', lambda h: None)
    conv = cli.post('/api/conversions', json={
        'broker': 'tradex', 'rate_rub_usdt': 86.15, 'sent_at': True,
        'sources': [{'sber_income_id': incomes[0], 'amount_rub': 27786.44}],
    }).get_json()['conversion']
    tx_hash = _uid() + _uid()
    cli.post(f"/api/conversions/{conv['id']}/txs", json={'tx_hash': tx_hash})

    r = cli.put(f"/api/conversions/{conv['id']}", json={
        'sent_at': '2026-08-17', 'rate_rub_usdt': 86.20, 'request_no': '93'})
    assert r.status_code == 200, r.get_data(as_text=True)
    upd = r.get_json()['conversion']
    assert upd['sent_at'][:10] == '2026-08-17'
    assert upd['rate_rub_usdt'] == 86.20
    assert upd['request_no'] == '93'
    # Привязка прихода и статус не пострадали
    assert upd['received_usdt'] == 2265.0
    assert upd['status'] == 'received'

    # Приход остался привязан именно к этой пачке
    card = cli.get(f"/api/conversions/{conv['id']}").get_json()
    assert card['txs'][0]['tx_hash'] == tx_hash
    assert card['txs'][0]['amount_usdt'] == 2265.0
    cli.delete(f"/api/conversions/{conv['id']}")
    db = get_session()
    try:
        db.query(PayinTx).filter(PayinTx.tx_hash == tx_hash).delete()
        db.commit()
    finally:
        db.close()


def test_реестр_обменников_видит_конвертацию(cli, monkeypatch):
    """WL-сделка вошла в пачку — реестр должен это показывать.

    Иначе в «Обменниках» и в заявке на вывод сделка выглядит необеспеченной,
    хотя рубли по ней уже конвертированы и USDT получен.
    """
    from app import ReestrSnapshot
    monkeypatch.setattr(appmod, '_tron_tx_amount', lambda h: 1290.68)
    monkeypatch.setattr(appmod, '_tron_tx_to_address', lambda h: None)
    db = get_session()
    inc_id = None
    try:
        db.query(ReestrSnapshot).filter(ReestrSnapshot.view.in_(('deals', 'requests'))).delete(
            synchronize_session=False)
        db.add(ReestrSnapshot(view='deals', payload=json.dumps([
            {'wl': 'WL-0393', 'dt': '17.08 16:00', 'merchant': 'Four exchange',
             'author': 'Artyom', 'rub': 112600, 'usdt': 1255.45, 'margin': 25.11,
             'status': 'requested'}])))
        db.add(ReestrSnapshot(view='requests', payload=json.dumps([
            {'id': '56', 'merchant': 'Four exchange', 'usdt': 1255.45, 'status': 'requested',
             'txs': [{'wl': 'WL-0393', 'rub': 112600, 'usdt': 1255.45}]}])))
        inc = SberIncome(uuid=_uid(), operation_date='2026-08-17', amount_rub=111811.80,
                         payer='Московский банк Сбербанка России',
                         purpose='Зачисление средств по операциям эквайринга. '
                                 'Мерчант №781003872118. Комиссия 788.20.')
        db.add(inc)
        db.flush()
        inc_id = inc.id
        db.commit()
    finally:
        db.close()

    conv = cli.post('/api/conversions', json={
        'broker': 'tradex', 'request_no': '93', 'rate_rub_usdt': 86.15,
        'sent_at': '2026-08-17',
        'sources': [{'sber_income_id': inc_id, 'amount_rub': 111811.80}],
    }).get_json()['conversion']
    tx_hash = _uid() + _uid()
    cli.post(f"/api/conversions/{conv['id']}/txs", json={'tx_hash': tx_hash})

    r = cli.get('/api/reestr/all').get_json()
    deal = next(d for d in r['deals'] if d['wl'] == 'WL-0393')
    assert deal['conversion']['display_name'] == conv['display_name']
    assert deal['conversion']['broker'] == 'tradex'
    assert deal['conversion']['usdt'] == 1290.68     # доля этой сделки в пачке
    assert deal['covered'] is True                   # рубли обменяны — сделка обеспечена

    req = next(x for x in r['requests'] if x['id'] == '56')
    assert req['txs'][0]['conversion']['display_name'] == conv['display_name']

    cli.delete(f"/api/conversions/{conv['id']}")
    db = get_session()
    try:
        db.query(PayinTx).filter(PayinTx.tx_hash == tx_hash).delete()
        db.query(SberIncome).filter(SberIncome.id == inc_id).delete()
        db.query(ReestrSnapshot).filter(ReestrSnapshot.view.in_(('deals', 'requests'))).delete(
            synchronize_session=False)
        db.commit()
    finally:
        db.close()


def test_доля_считается_одинаково_во_всех_экранах(cli, incomes, monkeypatch):
    """Одна и та же доля не должна расходиться между экранами.

    Раньше расчёт был скопирован в четыре места: список приходов, карточка пачки,
    разнос по сделкам и реестр обменников. Любая правка формулы в одном месте
    расходилась с остальными — и заметить это можно было только глазами.
    """
    from app import ReestrSnapshot
    monkeypatch.setattr(appmod, '_tron_tx_amount', lambda h: 1732.8791)
    monkeypatch.setattr(appmod, '_tron_tx_to_address', lambda h: None)
    db = get_session()
    try:
        db.query(ReestrSnapshot).filter(ReestrSnapshot.view == 'deals').delete(
            synchronize_session=False)
        db.add(ReestrSnapshot(view='deals', payload=json.dumps([
            {'wl': 'WL-TEST', 'dt': '11.08 10:00', 'merchant': 'M', 'rub': 35000,
             'usdt': 400, 'status': 'paid'}])))
        db.query(SberIncome).filter(SberIncome.id == incomes[1]).update(
            {'operation_date': '2026-08-11',
             'purpose': 'Зачисление средств по операциям эквайринга. '
                        'Мерчант №781003872118. Комиссия 0.00.'})
        db.commit()
    finally:
        db.close()

    conv = cli.post('/api/conversions', json={
        'broker': 'tradex', 'rate_rub_usdt': 83.35, 'sent_at': '2026-08-11',
        'sources': [{'sber_income_id': i, 'amount_rub': a} for i, a in
                    zip(incomes, (27786.44, 35000.0, 83000.0))],
    }).get_json()['conversion']
    tx_hash = _uid() + _uid()
    cli.post(f"/api/conversions/{conv['id']}/txs", json={'tx_hash': tx_hash})

    # 1. Карточка пачки
    card = cli.get(f"/api/conversions/{conv['id']}").get_json()
    from_card = {x['sber_income_id']: x['usdt'] for x in card['composition']}
    # 2. Список приходов
    body = cli.get('/api/sber-incomes?all=1&with_conversion=1').get_json()
    from_list = {i['id']: i['usdt'] for i in body['incomes'] if i['id'] in incomes}
    # 3. Реестр обменников
    reestr = cli.get('/api/reestr/all').get_json()
    wl = next((d for d in reestr['deals'] if d['wl'] == 'WL-TEST'), None)

    assert from_card[incomes[1]] == from_list[incomes[1]]
    assert wl and wl['conversion']['usdt'] == from_card[incomes[1]]

    cli.delete(f"/api/conversions/{conv['id']}")
    db = get_session()
    try:
        db.query(PayinTx).filter(PayinTx.tx_hash == tx_hash).delete()
        db.query(ReestrSnapshot).filter(ReestrSnapshot.view == 'deals').delete(
            synchronize_session=False)
        db.commit()
    finally:
        db.close()
