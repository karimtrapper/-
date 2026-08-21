"""
Реестр входящих переводов: один хэш обслуживает несколько сделок.
Спека: docs/specs/2026-08-13-payin-tx-allocations.md

Клиент платит рублями в несколько заходов, обмениваем один раз и получаем
ОДИН перевод. Раньше хэш считался занятым целиком: во второй сделке он не
показывался, а вбитый руками давал двойной приход.

Запуск: cd Dev/CalcCRM && python -m pytest tests/test_payin_tx_ledger.py -v
"""
import pytest
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ['SECRET_KEY'] = 'test-secret-key-for-pytest'

import app as A
from app import (app, get_session, Deal, Client, PayInMethod, DealType, DealStatus,
                 PayinTx, PayinTxUse, _sync_payin_tx_uses, _payin_tx_parts,
                 get_used_transaction_hashes)

H = '9f7f2c28cdc33f9e954e94787e0ce18e5b099e506e05069a68546bf53afd0d51'
H2 = 'aa11bb22cc33dd44ee55ff66aa77bb88cc99dd00ee11ff22aa33bb44cc55dd66'


@pytest.fixture(autouse=True)
def clean_db(monkeypatch):
    # Сеть в тестах не дёргаем: сумма перевода задаётся явно
    monkeypatch.setattr(A, '_tron_tx_usdt_amount', lambda h: None)
    s = get_session()
    try:
        s.query(PayinTxUse).delete()
        s.query(PayinTx).delete()
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


def make_deal(db, usdt, hashes):
    d = Deal(client_name='T', deal_type=DealType.PAY_IN, status=DealStatus.PENDING,
             payin_method=PayInMethod.SBER_REQS, payin_amount_usdt=usdt,
             payin_tx_hashes=json.dumps(hashes, ensure_ascii=False),
             payin_tx_hash=hashes[0]['hash'] if hashes else None)
    db.add(d)
    db.commit()
    return d


def test_one_transfer_serves_two_deals(db):
    """Главный сценарий: $2760 пришло одним переводом за две оплаты."""
    d1 = make_deal(db, 2353.0, [{'hash': H, 'amount_usdt': 2353.0}])
    tx = PayinTx(tx_hash=H, amount_usdt=2760.0, source='tronscan')
    db.add(tx)
    db.commit()

    _sync_payin_tx_uses(db, d1, _payin_tx_parts(d1))
    db.commit()
    assert tx.used_usdt() == 2353.0
    assert tx.free_usdt() == pytest.approx(407.0, abs=0.01)

    d2 = make_deal(db, 407.0, [{'hash': H, 'amount_usdt': 407.0}])
    _sync_payin_tx_uses(db, d2, _payin_tx_parts(d2))
    db.commit()
    assert tx.used_usdt() == pytest.approx(2760.0, abs=0.01)
    assert tx.free_usdt() == pytest.approx(0.0, abs=0.01)
    assert sorted(u.deal_id for u in tx.uses) == sorted([d1.id, d2.id])


def test_over_allocation_is_rejected(db):
    """Больше пришедшего отнести нельзя — это и есть двойной учёт."""
    tx = PayinTx(tx_hash=H, amount_usdt=2760.0, source='tronscan')
    db.add(tx)
    db.commit()
    d1 = make_deal(db, 2353.0, [{'hash': H, 'amount_usdt': 2353.0}])
    _sync_payin_tx_uses(db, d1, _payin_tx_parts(d1))
    db.commit()

    d2 = make_deal(db, 900.0, [{'hash': H, 'amount_usdt': 900.0}])
    with pytest.raises(ValueError) as e:
        _sync_payin_tx_uses(db, d2, _payin_tx_parts(d2))
    assert '407' in str(e.value)
    assert '900' in str(e.value)


def test_hash_with_remainder_stays_available(db):
    """Пока в переводе есть остаток, он остаётся в списке доступных."""
    tx = PayinTx(tx_hash=H, amount_usdt=2760.0, source='tronscan')
    db.add(tx)
    db.commit()
    d1 = make_deal(db, 2353.0, [{'hash': H, 'amount_usdt': 2353.0}])
    _sync_payin_tx_uses(db, d1, _payin_tx_parts(d1))
    db.commit()
    assert H not in get_used_transaction_hashes(db)


def test_fully_allocated_hash_disappears(db):
    tx = PayinTx(tx_hash=H, amount_usdt=2760.0, source='tronscan')
    db.add(tx)
    db.commit()
    d1 = make_deal(db, 2760.0, [{'hash': H, 'amount_usdt': 2760.0}])
    _sync_payin_tx_uses(db, d1, _payin_tx_parts(d1))
    db.commit()
    assert H in get_used_transaction_hashes(db)


def test_hash_outside_ledger_counts_as_used(db):
    """Легаси-хэш без записи в реестре занят целиком — поведение как до реестра."""
    make_deal(db, 1000.0, [{'hash': H2, 'amount_usdt': 1000.0}])
    assert H2 in get_used_transaction_hashes(db)


def test_removing_hash_frees_the_share(db):
    """Убрали хэш из сделки — доля возвращается в остаток."""
    tx = PayinTx(tx_hash=H, amount_usdt=2760.0, source='tronscan')
    db.add(tx)
    db.commit()
    d1 = make_deal(db, 2353.0, [{'hash': H, 'amount_usdt': 2353.0}])
    _sync_payin_tx_uses(db, d1, _payin_tx_parts(d1))
    db.commit()
    assert tx.free_usdt() == pytest.approx(407.0, abs=0.01)

    d1.payin_tx_hashes = json.dumps([])
    d1.payin_tx_hash = None
    _sync_payin_tx_uses(db, d1, _payin_tx_parts(d1))
    db.commit()
    assert tx.free_usdt() == pytest.approx(2760.0, abs=0.01)


def test_reallocating_same_deal_does_not_double(db):
    """Повторное сохранение сделки не удваивает её долю."""
    tx = PayinTx(tx_hash=H, amount_usdt=2760.0, source='tronscan')
    db.add(tx)
    db.commit()
    d1 = make_deal(db, 2353.0, [{'hash': H, 'amount_usdt': 2353.0}])
    for _ in range(3):
        _sync_payin_tx_uses(db, d1, _payin_tx_parts(d1))
        db.commit()
    assert tx.used_usdt() == 2353.0


def test_unknown_hash_creates_manual_tx(db):
    """Перевода нет в реестре и сеть молчит — заводим по заявленной сумме,
    пометив «не сверено», иначе сделка не сохранилась бы из-за TronScan."""
    d1 = make_deal(db, 500.0, [{'hash': H2, 'amount_usdt': 500.0}])
    _sync_payin_tx_uses(db, d1, _payin_tx_parts(d1))
    db.commit()
    tx = db.query(PayinTx).filter(PayinTx.tx_hash == H2).first()
    assert tx is not None
    assert tx.source == 'manual'
    assert tx.amount_usdt == 500.0
    assert tx.free_usdt() == pytest.approx(0.0, abs=0.01)


def test_unverified_amount_does_not_block(db):
    """Сеть молчала — сумма перевода это первая заявленная доля, то есть
    выдуманный потолок. Отказывать по нему нельзя: вторая сделка поднимает
    сумму до разобранного и перевод помечается «не сверен»."""
    d1 = make_deal(db, 500.0, [{'hash': H2, 'amount_usdt': 500.0}])
    _sync_payin_tx_uses(db, d1, _payin_tx_parts(d1))
    db.commit()
    d2 = make_deal(db, 300.0, [{'hash': H2, 'amount_usdt': 300.0}])
    _sync_payin_tx_uses(db, d2, _payin_tx_parts(d2))   # не должно бросить
    db.commit()

    tx = db.query(PayinTx).filter(PayinTx.tx_hash == H2).first()
    assert tx.amount_usdt == pytest.approx(800.0, abs=0.01)
    assert tx.source == 'manual'
    assert 'не сверена' in (tx.notes or '')


def test_verified_amount_still_blocks(db):
    """А вот при сверенной с сетью сумме потолок настоящий и держится."""
    tx = PayinTx(tx_hash=H, amount_usdt=1000.0, source='tronscan')
    db.add(tx); db.commit()
    d1 = make_deal(db, 900.0, [{'hash': H, 'amount_usdt': 900.0}])
    _sync_payin_tx_uses(db, d1, _payin_tx_parts(d1))
    db.commit()
    d2 = make_deal(db, 300.0, [{'hash': H, 'amount_usdt': 300.0}])
    with pytest.raises(ValueError):
        _sync_payin_tx_uses(db, d2, _payin_tx_parts(d2))


def test_deal_deletion_frees_its_share(tc, db):
    """Удаление сделки не должно блокироваться реестром и обязано вернуть
    её долю в остаток. FK payin_tx_uses_deal_id_fkey ловил это 400-й."""
    tx = PayinTx(tx_hash=H, amount_usdt=2760.0, source='tronscan')
    db.add(tx); db.commit()
    d1 = make_deal(db, 2353.0, [{'hash': H, 'amount_usdt': 2353.0}])
    _sync_payin_tx_uses(db, d1, _payin_tx_parts(d1))
    db.commit()
    deal_id = d1.id
    assert tx.free_usdt() == pytest.approx(407.0, abs=0.01)

    r = tc.delete(f'/api/deals/{deal_id}')
    assert r.status_code == 200, r.get_data(as_text=True)
    db.expire_all()
    tx = db.query(PayinTx).filter(PayinTx.tx_hash == H).first()
    assert tx.free_usdt() == pytest.approx(2760.0, abs=0.01)
    assert db.query(PayinTxUse).filter(PayinTxUse.deal_id == deal_id).count() == 0


@pytest.fixture
def tc():
    app.config['TESTING'] = True
    from app import AdminUser
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


def test_deal_without_own_usdt_shows_conversion_share(tc, db):
    """Сделка по СБП: своего USDT нет, но доля из пачки уже разнесена.

    В таблице и карточке раньше стоял прочерк — оператор читал это как
    «деньги не пришли», хотя сумма известна.
    """
    d = Deal(client_name='Екатерина', deal_type=DealType.PAY_IN, status=DealStatus.PENDING,
             payin_method=PayInMethod.SBER_WL, payin_amount_rub=63767.0)
    db.add(d); db.commit()
    tx = PayinTx(tx_hash=H2, amount_usdt=743.42, source='manual')
    db.add(tx); db.commit()
    db.add(PayinTxUse(tx_id=tx.id, deal_id=d.id, amount_usdt=743.42))
    db.commit()

    one = tc.get(f'/api/deals/{d.id}').json['deal']
    assert one['payin_amount_usdt'] is None
    assert one['payin_usdt_converted'] == 743.42

    row = [x for x in tc.get('/api/deals').json['deals'] if x['id'] == d.id][0]
    assert row['payin_usdt_converted'] == 743.42


def test_deal_with_own_usdt_has_no_conversion_field(tc, db):
    """Свой USDT приоритетнее: подмешивать долю пачки не надо."""
    d = make_deal(db, 2353.0, [{'hash': H, 'amount_usdt': 2353.0}])
    row = tc.get(f'/api/deals/{d.id}').json['deal']
    assert row['payin_amount_usdt'] == 2353.0
    assert 'payin_usdt_converted' not in row
