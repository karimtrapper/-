"""
Реестр переводов выдачи: один хэш оплачивает выдачи нескольким клиентам.

Кейс 27.08: Андрей отправил 1952 USDT одним переводом на обменник, из этих
батов выдали 16 600 ฿ одному клиенту и 45 000 ฿ другому. Пока переводы жили
JSON-полем внутри сделки, остаток по хэшу никто не считал — тот же перевод
можно было указать в пяти сделках на полную сумму, и себестоимость задваивалась
молча (у приходов и возмещений такая защита давно есть).

Запуск: cd Dev/CalcCRM && python -m pytest tests/test_payout_tx_ledger.py -v
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
                 PayOutMethod, PayOutSource, PayoutTx, PayoutTxUse)

WALLET = 'TWyLcjJzyQmiT1nt7gEn8BVoNSN94RGcHb'
EXCHANGE = 'TRgnccUBQo8yZXtra8gqBngBqeTV5aQz74'


def _fresh_hash():
    """Хэш уникален между прогонами: локальная БД переживает запуски."""
    return uuid.uuid4().hex + uuid.uuid4().hex


@pytest.fixture
def tx_hash():
    return _fresh_hash()


@pytest.fixture
def cli(monkeypatch):
    flask_app.config['TESTING'] = True
    monkeypatch.setenv('LOCAL_NO_AUTH', '1')
    # Перевод на 1952 — как настоящий у Андрея. В сеть не ходим.
    monkeypatch.setattr(appmod, '_tron_tx_info', lambda h: {
        'amount_usdt': 1952.0, 'from_address': WALLET, 'to_address': EXCHANGE})
    monkeypatch.setattr(appmod, 'sync_deals_to_gsheet', lambda *a, **kw: None)
    monkeypatch.setattr(appmod, '_send_deal_telegram', lambda *a, **kw: None)
    monkeypatch.setattr(appmod, 'send_deal_completed_webhook', lambda *a, **kw: None)
    with flask_app.test_client() as c:
        yield c


@pytest.fixture(autouse=True)
def cleanup_rows():
    """Локальная БД общая на весь прогон — убираем за собой."""
    s = get_session()
    try:
        marks = {m: (s.query(m.id).order_by(m.id.desc()).first() or [0])[0]
                 for m in (Deal, PayoutTx)}
    finally:
        s.close()
    yield
    s = get_session()
    try:
        s.query(PayoutTxUse).filter(PayoutTxUse.tx_id > marks[PayoutTx]).delete(
            synchronize_session=False)
        s.query(PayoutTxUse).filter(PayoutTxUse.deal_id > marks[Deal]).delete(
            synchronize_session=False)
        s.query(Deal).filter(Deal.id > marks[Deal]).delete(synchronize_session=False)
        s.query(PayoutTx).filter(PayoutTx.id > marks[PayoutTx]).delete(
            synchronize_session=False)
        s.commit()
    finally:
        s.close()


def _create_deal(cli, payout_thb, tx_hash, share_usdt):
    """Сделка с выдачей из личных фаундера, оплаченной долей перевода."""
    return cli.post('/api/deals', json={
        'client_name': 'Тест выдачи', 'deal_type': 'pay_in',
        'payin_method': 'crypto_direct', 'payin_amount_usdt': 600,
        'payout_method': 'transfer', 'payout_source': 'founder_personal',
        'payout_founder_name': 'Андрей', 'payout_amount_thb': payout_thb,
        'payout_tx_hashes': [{'hash': tx_hash, 'amount_usdt': share_usdt}],
    })


class _TxSnapshot:
    """Слепок перевода: остаток считаем внутри сессии, наружу отдаём числа."""

    def __init__(self, tx):
        self.amount_usdt = tx.amount_usdt
        self.source = tx.source
        self.notes = tx.notes
        self._free = tx.free_usdt()

    def free_usdt(self):
        return self._free


def _tx(tx_hash):
    s = get_session()
    try:
        tx = s.query(PayoutTx).filter(PayoutTx.tx_hash == tx_hash).first()
        return _TxSnapshot(tx) if tx else None
    finally:
        s.close()


class TestRemainder:
    def test_first_deal_takes_share_rest_stays_free(self, cli, tx_hash):
        """16 600 ฿ = 509.42 из перевода 1952 → свободно 1442.58."""
        r = _create_deal(cli, 16600, tx_hash, 509.42)
        assert r.status_code in (200, 201), r.get_json()
        tx = _tx(tx_hash)
        assert tx.amount_usdt == pytest.approx(1952.0)
        assert tx.source == 'tronscan'          # сумма из сети, а не с рук
        assert tx.free_usdt() == pytest.approx(1442.58)

    def test_second_deal_takes_from_remainder(self, cli, tx_hash):
        """Второй сделке — её доля из того же перевода."""
        _create_deal(cli, 16600, tx_hash, 509.42)
        r = _create_deal(cli, 45000, tx_hash, 1375.46)
        assert r.status_code in (200, 201), r.get_json()
        assert _tx(tx_hash).free_usdt() == pytest.approx(67.12)

    def test_over_remainder_rejected(self, cli, tx_hash):
        """Больше остатка выдать нельзя — иначе себестоимость задваивается."""
        _create_deal(cli, 16600, tx_hash, 509.42)
        r = _create_deal(cli, 45000, tx_hash, 1952.0)
        assert r.status_code == 409, r.get_json()
        body = r.get_json()
        assert 'свободно' in body['error']
        assert '1,442.58' in body['error'] or '1442.58' in body['error']

    def test_same_hash_full_amount_twice_rejected(self, cli, tx_hash):
        """Ровно та дыра, из-за которой всё затевалось."""
        assert _create_deal(cli, 45000, tx_hash, 1952.0).status_code in (200, 201)
        assert _create_deal(cli, 45000, tx_hash, 1952.0).status_code == 409

    def test_share_lowered_returns_remainder(self, cli, tx_hash):
        """Уменьшили долю в сделке — остаток вернулся в перевод."""
        deal_id = _create_deal(cli, 45000, tx_hash, 1375.46).get_json()['deal']['id']
        assert _tx(tx_hash).free_usdt() == pytest.approx(576.54)
        cli.put(f'/api/deals/{deal_id}', json={
            'payout_amount_thb': 16600,
            'payout_tx_hashes': [{'hash': tx_hash, 'amount_usdt': 509.42}]})
        assert _tx(tx_hash).free_usdt() == pytest.approx(1442.58)

    def test_deal_deleted_frees_share(self, cli, tx_hash):
        """Удалили сделку — её доля больше не держит перевод занятым."""
        deal_id = _create_deal(cli, 16600, tx_hash, 509.42).get_json()['deal']['id']
        cli.delete(f'/api/deals/{deal_id}')
        assert _tx(tx_hash).free_usdt() == pytest.approx(1952.0)

    def test_hash_removed_from_deal_frees_share(self, cli, tx_hash):
        """Отвязали хэш от сделки — доля снята."""
        deal_id = _create_deal(cli, 16600, tx_hash, 509.42).get_json()['deal']['id']
        cli.put(f'/api/deals/{deal_id}', json={'payout_tx_hashes': []})
        assert _tx(tx_hash).free_usdt() == pytest.approx(1952.0)


class TestUnknownAmount:
    def test_network_silent_amount_from_hand(self, cli, tx_hash, monkeypatch):
        """TronScan промолчал — верим руке, но помечаем «не сверено»."""
        monkeypatch.setattr(appmod, '_tron_tx_info', lambda h: {})
        _create_deal(cli, 16600, tx_hash, 509.42)
        tx = _tx(tx_hash)
        assert tx.source == 'manual'
        assert tx.amount_usdt == pytest.approx(509.42)

    def test_manual_tx_grows_instead_of_blocking(self, cli, tx_hash, monkeypatch):
        """Потолок выдуман (сети не было) — вторая сделка не блокируется."""
        monkeypatch.setattr(appmod, '_tron_tx_info', lambda h: {})
        _create_deal(cli, 16600, tx_hash, 509.42)
        r = _create_deal(cli, 45000, tx_hash, 1375.46)
        assert r.status_code in (200, 201), r.get_json()
        tx = _tx(tx_hash)
        assert tx.amount_usdt == pytest.approx(1884.88)
        assert 'не сверена' in (tx.notes or '')


class TestApi:
    def test_endpoint_lists_free(self, cli, tx_hash):
        _create_deal(cli, 16600, tx_hash, 509.42)
        txs = cli.get('/api/payout-tx?only_free=1').get_json()['txs']
        mine = [t for t in txs if t['tx_hash'] == tx_hash]
        assert mine and mine[0]['free_usdt'] == pytest.approx(1442.58)
        assert mine[0]['amount_usdt'] == pytest.approx(1952.0)
        assert mine[0]['from_address'] == WALLET
        assert len(mine[0]['deal_ids']) == 1


class TestCryptoIsNotReimbursement:
    """USDT клиента уже получены — это конвертация, а не долг фаундеру.

    Формулировка Карима (27.08): «если мы всё-таки получаем USDT, то это уже
    не возмещение, а просто конвертация — получили деньги и отправили, имея
    разницу». Рублёвая сделка устроена иначе: фаундер финансирует выдачу, а
    USDT появляются после конвертации — там долг настоящий.
    """

    def test_crypto_deal_closes_without_queue(self, cli, tx_hash):
        """Крипто-приход + известная себестоимость → сделка сразу завершена."""
        r = _create_deal(cli, 16600, tx_hash, 509.42)
        deal = r.get_json()['deal']
        assert deal['needs_reimbursement'] is False
        assert deal['status'] == 'completed'
        assert deal['profit_usdt'] == pytest.approx(600 - 509.42, abs=0.01)
        pending = cli.get('/api/reimbursements/pending').get_json()['by_founder']
        queued = [d['id'] for g in pending for d in g['deals']]
        assert deal['id'] not in queued

    def test_ruble_deal_still_waits_reimbursement(self, cli, tx_hash):
        """Рублёвая — как раньше: долг перед фаундером висит до возврата."""
        r = cli.post('/api/deals', json={
            'client_name': 'Рублёвая', 'deal_type': 'pay_in',
            'payin_method': 'sber_wl', 'payin_amount_rub': 45000,
            'payout_method': 'transfer', 'payout_source': 'founder_personal',
            'payout_founder_name': 'Андрей', 'payout_amount_thb': 16600,
            'payout_tx_hashes': [{'hash': tx_hash, 'amount_usdt': 509.42}],
        })
        deal = r.get_json()['deal']
        assert deal['needs_reimbursement'] is True
        assert deal['status'] == 'pending'
        pending = cli.get('/api/reimbursements/pending').get_json()['by_founder']
        queued = [d['id'] for g in pending for d in g['deals']]
        assert deal['id'] in queued

    def test_explicit_flag_wins(self, cli, tx_hash):
        """Явный needs_reimbursement из формы важнее умного дефолта."""
        r = cli.post('/api/deals', json={
            'client_name': 'Крипта с возвратом', 'deal_type': 'pay_in',
            'payin_method': 'crypto_direct', 'payin_amount_usdt': 600,
            'payout_method': 'transfer', 'payout_source': 'founder_personal',
            'payout_founder_name': 'Андрей', 'payout_amount_thb': 16600,
            'needs_reimbursement': True,
            'payout_tx_hashes': [{'hash': tx_hash, 'amount_usdt': 509.42}],
        })
        deal = r.get_json()['deal']
        assert deal['needs_reimbursement'] is True
        assert deal['status'] == 'pending'


class TestBackfilledTxVerifiedOnDemand:
    """Бэкфилл ставит сумму «сколько разнесли» — сеть уточняет её при работе.

    После миграции перевод 3d828b22… знал только про свою первую долю 509.42,
    хотя на самом деле ушло 1952. Если бы мы верили этой сумме, вторая сделка
    упёрлась бы в выдуманный потолок.
    """

    def test_manual_amount_replaced_by_chain(self, cli, tx_hash, monkeypatch):
        monkeypatch.setattr(appmod, '_tron_tx_info', lambda h: {})
        _create_deal(cli, 16600, tx_hash, 509.42)
        assert _tx(tx_hash).source == 'manual'
        # Сеть ожила — при следующей сделке сумма сверяется
        monkeypatch.setattr(appmod, '_tron_tx_info', lambda h: {
            'amount_usdt': 1952.0, 'from_address': WALLET, 'to_address': EXCHANGE})
        r = _create_deal(cli, 45000, tx_hash, 1375.46)
        assert r.status_code in (200, 201), r.get_json()
        tx = _tx(tx_hash)
        assert tx.amount_usdt == pytest.approx(1952.0)
        assert tx.source == 'tronscan'
        assert tx.free_usdt() == pytest.approx(67.12)

    def test_chain_amount_still_blocks_overspend(self, cli, tx_hash, monkeypatch):
        """Сеть сказала правду — сверх неё выдать всё равно нельзя."""
        monkeypatch.setattr(appmod, '_tron_tx_info', lambda h: {})
        _create_deal(cli, 16600, tx_hash, 509.42)
        monkeypatch.setattr(appmod, '_tron_tx_info', lambda h: {
            'amount_usdt': 1952.0, 'from_address': WALLET, 'to_address': EXCHANGE})
        r = _create_deal(cli, 45000, tx_hash, 1600.0)
        assert r.status_code == 409, r.get_json()
