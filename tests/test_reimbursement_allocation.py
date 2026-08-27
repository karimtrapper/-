"""Учёт возмещений по переводам: остаток, явные доли, защита от двойного списания.

Кейс Карима: одним переводом закрываем несколько сделок, а в карточке сделки
видно только «Возмещение #232». Не понять ни сколько всего перевели, ни что ещё
вошло в тот же хэш, ни осталось ли нераспределённое. Хуже — тот же перевод можно
было провести второй раз, и обе сделки выглядели бы возмещёнными.

Теперь перевод — сущность с суммой (берём из TronScan), возмещения берут из него
доли, и больше остатка взять нельзя.

Запуск: cd Dev/CalcCRM && python -m pytest tests/test_reimbursement_allocation.py -v
"""
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('SECRET_KEY', 'test-secret-key-for-pytest')
os.environ['REESTR_SYNC_ENABLED'] = '0'

import pytest

import app as appmod
from app import (app as flask_app, get_session, Deal, DealStatus, DealType, PayInMethod,
                 PayOutMethod, PayOutSource, Reimbursement, ReimbursementTx, ReimbursementTxUse)

# Тесты делят одну локальную БД, и она переживает прогоны: переводы копят
# использование, поэтому хэш должен быть уникален не только между тестами,
# но и между запусками — иначе остаток «протекает» и тесты падают со второго раза.
def _fresh_hash():
    return uuid.uuid4().hex + uuid.uuid4().hex


@pytest.fixture
def tx_hash():
    return _fresh_hash()


@pytest.fixture
def tx_hash2():
    return _fresh_hash()


@pytest.fixture
def cli(monkeypatch):
    flask_app.config['TESTING'] = True
    monkeypatch.setenv('LOCAL_NO_AUTH', '1')
    # Сумма перевода в тестах фиксирована: сеть не дёргаем
    monkeypatch.setattr(appmod, '_tron_tx_amount', lambda h: 700.0)
    # Побочка возмещения — выгрузка и телеграм — к учёту отношения не имеет
    monkeypatch.setattr(appmod, 'sync_deals_to_gsheet', lambda *a, **kw: None)
    monkeypatch.setattr(appmod, '_send_deal_telegram', lambda *a, **kw: None)
    with flask_app.test_client() as c:
        yield c


@pytest.fixture(autouse=True)
def cleanup_rows():
    """Убираем за собой: локальная БД общая на весь прогон.

    Без этого созданные тут сделки и возмещения утекают в чужие тесты
    (`test_referral`, `test_mf_realty` считают строки) и валят их.
    """
    s = get_session()
    try:
        marks = {m: (s.query(m.id).order_by(m.id.desc()).first() or [0])[0]
                 for m in (Deal, Reimbursement, ReimbursementTx)}
    finally:
        s.close()
    yield
    s = get_session()
    try:
        s.query(ReimbursementTxUse).filter(
            ReimbursementTxUse.reimbursement_id > marks[Reimbursement]).delete(synchronize_session=False)
        s.query(Deal).filter(Deal.id > marks[Deal]).delete(synchronize_session=False)
        s.query(Reimbursement).filter(Reimbursement.id > marks[Reimbursement]).delete(synchronize_session=False)
        s.query(ReimbursementTx).filter(ReimbursementTx.id > marks[ReimbursementTx]).delete(synchronize_session=False)
        s.commit()
    finally:
        s.close()


def _make_deal(payout_thb, payin_usdt=200.0, founder='Андрей'):
    """Сделка, ждущая возмещения: выплата из личных фаундера."""
    s = get_session()
    try:
        d = Deal(client_name='Тест', deal_type=DealType.PAY_IN,
                 payin_method=PayInMethod.CRYPTO_DIRECT,
                 payin_amount_usdt=payin_usdt, payout_method=PayOutMethod.TRANSFER,
                 payout_source=PayOutSource.FOUNDER_PERSONAL, payout_founder_name=founder,
                 payout_amount_thb=payout_thb, status=DealStatus.PENDING)
        s.add(d)
        s.commit()
        return d.id
    finally:
        s.close()


def _tx_free(tx_hash):
    s = get_session()
    try:
        tx = s.query(ReimbursementTx).filter(ReimbursementTx.tx_hash == tx_hash).first()
        return tx.free_usdt() if tx else None
    finally:
        s.close()


class TestRemainder:
    def test_partial_use_leaves_free_amount(self, cli, tx_hash, tx_hash2):
        """Перевод 700, взяли 500 → 200 остаются запасом."""
        d1 = _make_deal(10000)
        resp = cli.post('/api/reimbursements', json={
            'founder_name': 'Андрей', 'deal_ids': [d1], 'amount_usdt': 500,
            'tx_uses': [{'tx_hash': tx_hash, 'amount_usdt': 500}],
        })
        assert resp.status_code == 200, resp.get_json()
        assert _tx_free(tx_hash) == pytest.approx(200.0)

    def test_second_use_within_remainder_ok(self, cli, tx_hash, tx_hash2):
        """Тот же перевод завтра — можно, но только на остаток."""
        d1, d2 = _make_deal(10000), _make_deal(4000)
        cli.post('/api/reimbursements', json={
            'founder_name': 'Андрей', 'deal_ids': [d1], 'amount_usdt': 500,
            'tx_uses': [{'tx_hash': tx_hash, 'amount_usdt': 500}]})
        resp = cli.post('/api/reimbursements', json={
            'founder_name': 'Андрей', 'deal_ids': [d2], 'amount_usdt': 150,
            'tx_uses': [{'tx_hash': tx_hash, 'amount_usdt': 150}]})
        assert resp.status_code == 200, resp.get_json()
        assert _tx_free(tx_hash) == pytest.approx(50.0)

    def test_over_remainder_rejected_with_amount(self, cli, tx_hash, tx_hash2):
        """Сверх остатка — 409 и в тексте видно, сколько реально доступно."""
        d1, d2 = _make_deal(10000), _make_deal(4000)
        cli.post('/api/reimbursements', json={
            'founder_name': 'Андрей', 'deal_ids': [d1], 'amount_usdt': 650,
            'tx_uses': [{'tx_hash': tx_hash, 'amount_usdt': 650}]})
        resp = cli.post('/api/reimbursements', json={
            'founder_name': 'Андрей', 'deal_ids': [d2], 'amount_usdt': 300,
            'tx_uses': [{'tx_hash': tx_hash, 'amount_usdt': 300}]})
        assert resp.status_code == 409
        body = resp.get_json()
        assert '50.00' in body['error'] and '300.00' in body['error']
        assert body['tx_free_usdt'] == pytest.approx(50.0)

    def test_delete_returns_remainder(self, cli, tx_hash, tx_hash2):
        """Удалили возмещение — деньги вернулись в остаток перевода."""
        d1 = _make_deal(10000)
        r = cli.post('/api/reimbursements', json={
            'founder_name': 'Андрей', 'deal_ids': [d1], 'amount_usdt': 500,
            'tx_uses': [{'tx_hash': tx_hash2, 'amount_usdt': 500}]}).get_json()
        assert _tx_free(tx_hash2) == pytest.approx(200.0)
        cli.delete(f"/api/reimbursements/{r['reimbursement']['id']}")
        assert _tx_free(tx_hash2) == pytest.approx(700.0)


class TestAllocation:
    def test_explicit_shares_respected(self, cli, tx_hash, tx_hash2):
        """Явные доли важнее пропорции: 300 и 200 при разных суммах бат."""
        d1, d2 = _make_deal(10000), _make_deal(4000)
        cli.post('/api/reimbursements', json={
            'founder_name': 'Андрей', 'deal_ids': [d1, d2], 'amount_usdt': 500,
            'tx_uses': [{'tx_hash': tx_hash, 'amount_usdt': 500}],
            'deal_allocations': [{'deal_id': d1, 'amount_usdt': 300},
                                 {'deal_id': d2, 'amount_usdt': 200}],
        })
        s = get_session()
        try:
            assert s.query(Deal).get(d1).payout_amount_usdt == pytest.approx(300)
            assert s.query(Deal).get(d2).payout_amount_usdt == pytest.approx(200)
        finally:
            s.close()

    def test_proportional_fallback_unchanged(self, cli, tx_hash, tx_hash2):
        """Без явных долей — прежнее пропорциональное распределение (регресс)."""
        d1, d2 = _make_deal(10000), _make_deal(10000)
        cli.post('/api/reimbursements', json={
            'founder_name': 'Андрей', 'deal_ids': [d1, d2], 'amount_usdt': 400,
            'tx_uses': [{'tx_hash': tx_hash, 'amount_usdt': 400}]})
        s = get_session()
        try:
            assert s.query(Deal).get(d1).payout_amount_usdt == pytest.approx(200)
            assert s.query(Deal).get(d2).payout_amount_usdt == pytest.approx(200)
        finally:
            s.close()

    def test_allocation_over_taken_rejected(self, cli, tx_hash, tx_hash2):
        """Раздать больше, чем взяли из переводов, нельзя."""
        d1 = _make_deal(10000)
        resp = cli.post('/api/reimbursements', json={
            'founder_name': 'Андрей', 'deal_ids': [d1], 'amount_usdt': 300,
            'tx_uses': [{'tx_hash': tx_hash, 'amount_usdt': 300}],
            'deal_allocations': [{'deal_id': d1, 'amount_usdt': 500}]})
        assert resp.status_code == 400
        assert 'взято' in resp.get_json()['error']


class TestBreakdownOutput:
    def test_deal_card_sees_composition(self, cli, tx_hash, tx_hash2):
        """В сделке видно: сколько всего перевели, чья доля, что ещё покрыто."""
        d1, d2 = _make_deal(10000), _make_deal(4000)
        cli.post('/api/reimbursements', json={
            'founder_name': 'Андрей', 'deal_ids': [d1, d2], 'amount_usdt': 500,
            'tx_uses': [{'tx_hash': tx_hash, 'amount_usdt': 500}],
            'deal_allocations': [{'deal_id': d1, 'amount_usdt': 300},
                                 {'deal_id': d2, 'amount_usdt': 200}]})
        deal = cli.get(f'/api/deals/{d1}').get_json()['deal']
        r = deal['reimbursement']
        assert r['deals_count'] == 2
        assert {x['deal_id'] for x in r['deals_breakdown']} == {d1, d2}
        assert r['tx_uses'][0]['tx_amount_usdt'] == pytest.approx(700)
        assert r['tx_uses'][0]['taken_usdt'] == pytest.approx(500)
        assert r['tx_free_total'] == pytest.approx(200)   # тот самый «запас»

    def test_tx_endpoint_lists_free(self, cli, tx_hash, tx_hash2):
        d1 = _make_deal(10000)
        cli.post('/api/reimbursements', json={
            'founder_name': 'Андрей', 'deal_ids': [d1], 'amount_usdt': 500,
            'tx_uses': [{'tx_hash': tx_hash, 'amount_usdt': 500}]})
        txs = cli.get('/api/reimbursements/tx?founder=Андрей&only_free=1').get_json()['txs']
        mine = [t for t in txs if t['tx_hash'] == tx_hash]
        assert mine and mine[0]['free_usdt'] == pytest.approx(200)


class TestAmountIsTheCeiling:
    """Кейс сделки #548: перевод больше, чем возмещаем.

    Перевод Андрею был на 1952 USDT, а себестоимость выданных 45 000 ฿ —
    1375.46. Форма отправляла перевод целиком, сделке записывалась доля 1952,
    и карточка ругалась «распределено больше, чем перевели», а прибыль сделки
    уходила в фиктивный минус. Сумма возмещения — потолок для всего.
    """

    def test_transfer_taken_only_up_to_amount(self, cli, tx_hash, tx_hash2):
        """Сумму по переводу не сказали → берём столько, сколько возмещаем."""
        d1 = _make_deal(10000)
        resp = cli.post('/api/reimbursements', json={
            'founder_name': 'Андрей', 'deal_ids': [d1], 'amount_usdt': 500,
            'tx_uses': [{'tx_hash': tx_hash}]})
        assert resp.status_code == 200, resp.get_json()
        assert _tx_free(tx_hash) == pytest.approx(200.0)

    def test_taking_more_than_amount_rejected(self, cli, tx_hash, tx_hash2):
        """Взять из перевода больше суммы возмещения нельзя."""
        d1 = _make_deal(10000)
        resp = cli.post('/api/reimbursements', json={
            'founder_name': 'Андрей', 'deal_ids': [d1], 'amount_usdt': 500,
            'tx_uses': [{'tx_hash': tx_hash, 'amount_usdt': 700}]})
        assert resp.status_code == 400
        assert 'возмещение' in resp.get_json()['error']

    def test_deal_share_over_amount_rejected(self, cli, tx_hash, tx_hash2):
        """Ровно кейс #548: доля сделки = весь перевод при меньшем возмещении."""
        d1 = _make_deal(45000)
        resp = cli.post('/api/reimbursements', json={
            'founder_name': 'Андрей', 'deal_ids': [d1], 'amount_usdt': 500,
            'tx_uses': [{'tx_hash': tx_hash, 'amount_usdt': 500}],
            'deal_allocations': [{'deal_id': d1, 'amount_usdt': 700}]})
        assert resp.status_code == 400

    def test_two_transfers_cover_amount_without_overtaking(self, cli, tx_hash, tx_hash2):
        """Два перевода по 700 на возмещение 900: второй отдаёт только 200."""
        d1, d2 = _make_deal(10000), _make_deal(8000)
        resp = cli.post('/api/reimbursements', json={
            'founder_name': 'Андрей', 'deal_ids': [d1, d2], 'amount_usdt': 900,
            'tx_uses': [{'tx_hash': tx_hash}, {'tx_hash': tx_hash2}]})
        assert resp.status_code == 200, resp.get_json()
        assert _tx_free(tx_hash) == pytest.approx(0.0)
        assert _tx_free(tx_hash2) == pytest.approx(500.0)

    def test_multi_deal_shares_sum_to_amount(self, cli, tx_hash, tx_hash2):
        """Несколько сделок в одном возмещении: доли складываются в сумму возмещения."""
        d1, d2 = _make_deal(30000), _make_deal(10000)
        cli.post('/api/reimbursements', json={
            'founder_name': 'Андрей', 'deal_ids': [d1, d2], 'amount_usdt': 400,
            'tx_uses': [{'tx_hash': tx_hash, 'amount_usdt': 400}]})
        s = get_session()
        try:
            shares = [s.query(Deal).get(x).payout_amount_usdt for x in (d1, d2)]
        finally:
            s.close()
        assert sum(shares) == pytest.approx(400)
        assert shares[0] == pytest.approx(300)   # пропорция по батам 30k:10k


class TestOneHashTwoKinds:
    """Один перевод — несколько возмещений разного типа.

    Андрей прислал 2000 USDT одним хэшем: часть закрыла рублёвые сделки, где
    USDT ещё не пришли (возмещение наперёд), часть — сделку, где клиент уже
    прислал USDT. Система должна показывать по хэшу весь расклад: какое
    возмещение за что и сколько осталось свободным.
    """

    def test_kind_advance_stored_and_returned(self, cli, tx_hash, tx_hash2):
        d1 = _make_deal(10000)
        r = cli.post('/api/reimbursements', json={
            'founder_name': 'Андрей', 'deal_ids': [d1], 'amount_usdt': 300,
            'kind': 'advance',
            'tx_uses': [{'tx_hash': tx_hash, 'amount_usdt': 300}]}).get_json()
        assert r['reimbursement']['kind'] == 'advance'
        deal = cli.get(f'/api/deals/{d1}').get_json()['deal']
        assert deal['reimbursement']['kind'] == 'advance'

    def test_auto_kind_cannot_be_forged(self, cli, tx_hash, tx_hash2):
        """'auto' ставит только автозачёт: руками такой тип не подсунуть."""
        d1 = _make_deal(10000)
        r = cli.post('/api/reimbursements', json={
            'founder_name': 'Андрей', 'deal_ids': [d1], 'amount_usdt': 300,
            'kind': 'auto', 'tx_uses': [{'tx_hash': tx_hash, 'amount_usdt': 300}]}).get_json()
        assert r['reimbursement']['kind'] == 'manual'

    def test_deal_card_shows_other_uses_of_same_hash(self, cli, tx_hash, tx_hash2):
        """В карточке первой сделки видно второе возмещение по тому же хэшу."""
        d1, d2 = _make_deal(10000), _make_deal(6000)
        first = cli.post('/api/reimbursements', json={
            'founder_name': 'Андрей', 'deal_ids': [d1], 'amount_usdt': 300,
            'kind': 'advance',
            'tx_uses': [{'tx_hash': tx_hash, 'amount_usdt': 300}]}).get_json()
        second = cli.post('/api/reimbursements', json={
            'founder_name': 'Андрей', 'deal_ids': [d2], 'amount_usdt': 200,
            'tx_uses': [{'tx_hash': tx_hash, 'amount_usdt': 200}]}).get_json()

        use = cli.get(f'/api/deals/{d1}').get_json()['deal']['reimbursement']['tx_uses'][0]
        assert use['tx_amount_usdt'] == pytest.approx(700)
        assert use['free_usdt'] == pytest.approx(200)      # 700 − 300 − 200
        assert len(use['uses_breakdown']) == 2
        others = use['other_uses']
        assert [o['reimbursement_id'] for o in others] == [second['reimbursement']['id']]
        assert others[0]['taken_usdt'] == pytest.approx(200)
        assert others[0]['kind'] == 'manual'
        assert others[0]['deals'][0]['deal_id'] == d2
        # А в карточке второй сделки — наоборот, видно первое (наперёд)
        use2 = cli.get(f'/api/deals/{d2}').get_json()['deal']['reimbursement']['tx_uses'][0]
        assert use2['other_uses'][0]['reimbursement_id'] == first['reimbursement']['id']
        assert use2['other_uses'][0]['kind'] == 'advance'

    def test_tx_endpoint_returns_full_breakdown(self, cli, tx_hash, tx_hash2):
        """Справочник переводов отдаёт расклад — форма показывает его до отправки."""
        d1, d2 = _make_deal(10000), _make_deal(6000)
        cli.post('/api/reimbursements', json={
            'founder_name': 'Андрей', 'deal_ids': [d1], 'amount_usdt': 300,
            'kind': 'advance', 'tx_uses': [{'tx_hash': tx_hash, 'amount_usdt': 300}]})
        cli.post('/api/reimbursements', json={
            'founder_name': 'Андрей', 'deal_ids': [d2], 'amount_usdt': 200,
            'tx_uses': [{'tx_hash': tx_hash, 'amount_usdt': 200}]})
        txs = cli.get('/api/reimbursements/tx?founder=Андрей').get_json()['txs']
        mine = [t for t in txs if t['tx_hash'] == tx_hash][0]
        assert mine['free_usdt'] == pytest.approx(200)
        assert {u['kind'] for u in mine['uses_breakdown']} == {'advance', 'manual'}
        assert sum(u['taken_usdt'] for u in mine['uses_breakdown']) == pytest.approx(500)
