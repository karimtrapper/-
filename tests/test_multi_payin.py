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

from app import (app, get_session, Deal, Client, AdminUser,
                 PayInMethod, DealType, DealStatus,
                 _normalize_payin_extra, _payin_extra_list, _payin_all_parts,
                 _apply_payin_extra, _payin_hash_list)

H_EXTRA = 'cc11dd22ee33ff44aa55bb66cc77dd88ee99ff00aa11bb22cc33dd44ee55ff66'


def make_deal(**over):
    """Сделка с обязательными полями. deal_type и status NOT NULL в схеме."""
    kw = dict(client_name='T', deal_type=DealType.PAY_IN,
              status=DealStatus.PENDING, payin_method=PayInMethod.PARTNERS_CASH)
    kw.update(over)
    return Deal(**kw)


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
    d = make_deal(payin_extra=json.dumps(extra, ensure_ascii=False))
    db.add(d)
    db.commit()

    got = db.query(Deal).filter(Deal.id == d.id).first()
    assert json.loads(got.payin_extra)[0]['amount_usdt'] == 2365.362
    assert got.to_dict()['payin_extra'][0]['method'] == 'sber_reqs'


def test_payin_extra_defaults_to_none(db):
    """Сделка с одним каналом: колонка пустая, to_dict отдаёт None."""
    d = make_deal()
    db.add(d)
    db.commit()
    assert d.payin_extra is None
    assert d.to_dict()['payin_extra'] is None


# ==================== Task 2: нормализация и чтение частей ====================

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
    """Метода нет в PayInMethod — часть не сохраняем, иначе упадёт лейбл в выгрузке."""
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
    d = make_deal(payin_partner_name='FOEX',
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
    d = make_deal(payin_amount_rub=600000, payin_amount_usdt=6920.0)
    db.add(d)
    db.commit()
    parts = _payin_all_parts(d)
    assert len(parts) == 1
    assert parts[0]['amount_usdt'] == 6920.0


def test_extra_list_survives_broken_json(db):
    """Битый JSON не должен ронять карточку и выгрузку."""
    d = make_deal(payin_extra='{не json')
    db.add(d)
    db.commit()
    assert _payin_extra_list(d) == []


# ============ Task 3: пересчёт агрегатов и защита от двойного учёта ============

def test_apply_aggregates_totals(db):
    """Итог = основная часть + дополнительные. Эталон спеки §4."""
    d = make_deal()
    db.add(d)
    db.commit()
    _apply_payin_extra(db, d, [
        {'method': 'sber_reqs', 'amount_rub': 200000, 'amount_usdt': 2365.362}],
        main_usdt=6920.0, main_rub=600000)
    assert d.payin_amount_usdt == pytest.approx(9285.362, abs=0.001)
    assert d.payin_amount_rub == pytest.approx(800000, abs=0.01)


def test_apply_weighted_rate_reconciles(db):
    """Средневзвешенный курс сходится делением — в этом весь его смысл.
    Курс первой части (86.7052) дал бы 9226.67 вместо 9285.36."""
    d = make_deal()
    db.add(d); db.commit()
    _apply_payin_extra(db, d, [
        {'method': 'sber_reqs', 'amount_rub': 200000, 'amount_usdt': 2365.362}],
        main_usdt=6920.0, main_rub=600000)
    assert d.payin_rate_rub_usdt == pytest.approx(86.1571, abs=1e-4)
    assert d.payin_amount_rub / d.payin_rate_rub_usdt == pytest.approx(
        d.payin_amount_usdt, abs=0.01)


def test_apply_rate_ignores_crypto_part(db):
    """У крипты рублей нет — в знаменатель средневзвешенного она не идёт."""
    d = make_deal(payin_method=PayInMethod.SBER_REQS)
    db.add(d); db.commit()
    _apply_payin_extra(db, d, [{'method': 'crypto_direct', 'amount_usdt': 500}],
                       main_usdt=2365.362, main_rub=200000)
    assert d.payin_amount_usdt == pytest.approx(2865.362, abs=0.001)
    assert d.payin_rate_rub_usdt == pytest.approx(84.5537, abs=1e-4)


def test_apply_method_is_largest_part(db):
    """payin_method читают Битрикс, фильтры и DealCloser — ставим метод
    крупнейшей части, а не первой введённой."""
    d = make_deal(payin_method=PayInMethod.SBER_REQS)
    db.add(d); db.commit()
    _apply_payin_extra(db, d, [
        {'method': 'partners_cash', 'amount_rub': 600000, 'amount_usdt': 6920.0}],
        main_usdt=2365.362, main_rub=200000)
    assert d.payin_method == PayInMethod.PARTNERS_CASH


def test_apply_method_kept_when_main_is_largest(db):
    d = make_deal(payin_method=PayInMethod.PARTNERS_CASH)
    db.add(d); db.commit()
    _apply_payin_extra(db, d, [
        {'method': 'sber_reqs', 'amount_rub': 200000, 'amount_usdt': 2365.362}],
        main_usdt=6920.0, main_rub=600000)
    assert d.payin_method == PayInMethod.PARTNERS_CASH


def test_apply_merges_hashes_for_double_spend_guard(db):
    """Хэш дополнительной части обязан попасть в payin_tx_hashes — иначе
    get_used_transaction_hashes его не увидит и приход спишут дважды."""
    d = make_deal(payin_tx_hashes=json.dumps([{'hash': 'a' * 64, 'amount_usdt': 6920.0}]))
    db.add(d); db.commit()
    _apply_payin_extra(db, d, [{
        'method': 'crypto_direct', 'amount_usdt': 500,
        'tx_hashes': [{'hash': 'b' * 64, 'amount_usdt': 500}]}],
        main_usdt=6920.0, main_rub=None)
    assert set(_payin_hash_list(d)) == {'a' * 64, 'b' * 64}


def test_apply_is_idempotent(db):
    """Повторный вызов с теми же аргументами не удваивает приход."""
    d = make_deal()
    db.add(d); db.commit()
    extra = [{'method': 'sber_reqs', 'amount_rub': 200000, 'amount_usdt': 2365.362}]
    _apply_payin_extra(db, d, extra, main_usdt=6920.0, main_rub=600000)
    _apply_payin_extra(db, d, extra, main_usdt=6920.0, main_rub=600000)
    assert d.payin_amount_usdt == pytest.approx(9285.362, abs=0.001)


def test_apply_empty_extra_clears_column(db):
    """Убрали все дополнительные части — колонка пустеет, агрегаты = основная часть."""
    d = make_deal(payin_extra=json.dumps([{'method': 'sber_reqs', 'amount_usdt': 100}]))
    db.add(d); db.commit()
    _apply_payin_extra(db, d, [], main_usdt=6920.0, main_rub=600000)
    assert d.payin_extra is None
    assert d.payin_amount_usdt == 6920.0


# ==================== Task 4: API принимает payin_extra ====================

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
    deal_id = d.id

    r = tc.put(f'/api/deals/{deal_id}', json={
        'payin_amount_rub': 600000, 'payin_amount_usdt': 6920.0,
        'payin_extra': [{'method': 'sber_reqs', 'amount_rub': 200000,
                         'amount_usdt': 2365.362}]})
    assert r.status_code == 200, r.get_data(as_text=True)
    db.expire_all()
    d = db.query(Deal).filter(Deal.id == deal_id).first()
    assert d.payin_amount_usdt == pytest.approx(9285.362, abs=0.001)


def test_put_without_payin_extra_does_not_drift(tc, db):
    """Интеграция шлёт PUT без payin_extra — приход не должен вырасти."""
    tc.post('/api/deals', json=_payload())
    d = db.query(Deal).order_by(Deal.id.desc()).first()
    deal_id, before = d.id, d.payin_amount_usdt

    tc.put(f'/api/deals/{deal_id}', json={'notes': 'просто заметка'})
    tc.put(f'/api/deals/{deal_id}', json={'notes': 'и ещё раз'})
    db.expire_all()
    d = db.query(Deal).filter(Deal.id == deal_id).first()
    assert d.payin_amount_usdt == pytest.approx(before, abs=0.001)


def test_put_removing_extra_returns_to_single(tc, db):
    tc.post('/api/deals', json=_payload())
    d = db.query(Deal).order_by(Deal.id.desc()).first()
    deal_id = d.id
    tc.put(f'/api/deals/{deal_id}', json={
        'payin_amount_rub': 600000, 'payin_amount_usdt': 6920.0, 'payin_extra': []})
    db.expire_all()
    d = db.query(Deal).filter(Deal.id == deal_id).first()
    assert d.payin_extra is None
    assert d.payin_amount_usdt == 6920.0
    assert d.payin_amount_rub == 600000
