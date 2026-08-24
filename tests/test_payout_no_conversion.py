"""Выдача своими батами: фаундер платил из своих, конвертации USDT→THB не было.

У Теодора лежали баты, он выдал их клиенту сам — с кошельков ничего не уходило,
значит нет ни исходящего перевода, ни хеша, и себестоимость выдачи неоткуда
вывести. Раньше такая сделка сохранялась с пустой суммой: прибыль «после
возмещения», в очереди возмещений строка без цифры, автозачёт её пропускал.

Теперь менеджер ставит сумму возврата руками (галка «выдал свои баты»), а
дальше всё едет по накатанной: прибыль считается сразу, долг гасится переводом
или автозачётом, когда приход пачки падает на кошелёк фаундера.

Запуск: cd Dev/CalcCRM && python -m pytest tests/test_payout_no_conversion.py -v
"""
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('SECRET_KEY', 'test-secret-key-for-pytest')
os.environ['REESTR_SYNC_ENABLED'] = '0'

import pytest

import app as appmod
from app import (app as flask_app, get_session, Client, Conversion, ConversionSource,
                 ConversionStatus, ConversionTx, Deal, DealAgent, DealStatus, PayinTx,
                 PayinTxUse, Reimbursement, ReimbursementTxUse, SberIncome, Wallet,
                 conversion_distribution)

TEODOR = 'TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn'   # кошелёк фаундера, куда вернём долг
VITALY = 'TKkeEVf2zySaWTLyX2qPwvi6kcdHRuPxkJ'   # кошелёк, куда пришла CNV-0002


def _uid():
    return uuid.uuid4().hex


@pytest.fixture
def cli(monkeypatch):
    flask_app.config['TESTING'] = True
    monkeypatch.setenv('LOCAL_NO_AUTH', '1')
    monkeypatch.setattr(appmod, 'sync_deals_to_gsheet', lambda *a, **kw: None)
    monkeypatch.setattr(appmod, '_send_deal_telegram', lambda *a, **kw: None)
    monkeypatch.setattr(appmod, 'send_deal_completed_webhook', lambda *a, **kw: None)
    monkeypatch.setattr(appmod, '_tron_tx_amount', lambda h: None)
    monkeypatch.setattr(appmod, 'CONVERSIONS_LAUNCH_DATE', '2026-01-01')
    with flask_app.test_client() as c:
        yield c


@pytest.fixture(autouse=True)
def clean():
    def _clean():
        db = get_session()
        try:
            db.query(ReimbursementTxUse).delete()
            db.query(PayinTxUse).delete()
            db.query(ConversionTx).delete()
            db.query(ConversionSource).delete()
            db.query(Conversion).delete()
            db.query(PayinTx).delete()
            db.query(DealAgent).delete()
            db.query(Deal).delete()
            db.query(Reimbursement).delete()
            db.query(SberIncome).delete()
            db.query(Client).delete()
            db.commit()
        finally:
            db.close()
    _clean()
    yield
    _clean()


def _wallet(address, label):
    db = get_session()
    try:
        w = db.query(Wallet).filter(Wallet.address == address).first()
        if not w:
            w = Wallet(address=address, label=label)
            db.add(w)
            db.commit()
        return w.id
    finally:
        db.close()


def _payload(wallet_id, **over):
    """Сделка Вадима со скрина: 18 100 ฿ своими батами, вернуть 463 USDT."""
    data = {
        'client_name': 'Вадим', 'status': 'pending',
        'payin_method': 'sber_reqs', 'payin_amount_rub': 40000.0,
        'payin_amount_usdt': 470.55,
        'payout_method': 'atm', 'payout_source': 'founder_personal',
        'payout_founder_name': 'Теодор', 'payout_wallet_id': wallet_id,
        'payout_amount_thb': 18100.0, 'payout_amount_usdt': 463.0,
        'payout_no_conversion': True, 'skip_sync': True,
    }
    data.update(over)
    return data


# ── Сохранение и прибыль ──────────────────────────────────────────────────

def test_сделка_сохраняется_без_хеша_и_считает_прибыль(cli):
    """Хеша выдачи нет, но себестоимость известна — прибыль сразу, не «после возмещения»."""
    wid = _wallet(TEODOR, 'Теодор')
    r = cli.post('/api/deals', json=_payload(wid)).get_json()
    assert r['success'] is True

    db = get_session()
    try:
        deal = db.query(Deal).get(r['deal']['id'])
        assert deal.payout_no_conversion is True
        assert deal.payout_amount_usdt == 463.0        # ручная сумма выжила
        assert deal.payout_tx_hashes is None           # переводов не существует
        assert deal.payout_tx_hash is None
        assert deal.profit_usdt == 7.55                # 470.55 − 463.00
        assert deal.needs_reimbursement is not False   # долг перед фаундером есть
    finally:
        db.close()


def test_сумма_обязательна(cli):
    """Без суммы возврата сделку пускать нельзя — её неоткуда вывести."""
    wid = _wallet(TEODOR, 'Теодор')
    r = cli.post('/api/deals', json=_payload(wid, payout_amount_usdt=None))
    assert r.status_code == 400
    assert 'сколько USDT вернуть' in r.get_json()['error']


def test_кошелёк_обязателен(cli):
    """Без кошелька автозачёт не найдёт, куда возвращать, — сделка зависнет."""
    r = cli.post('/api/deals', json=_payload(None))
    assert r.status_code == 400
    assert 'кошелёк' in r.get_json()['error'].lower()


def test_курс_вне_коридора_не_проходит(cli):
    """46,30 вместо 463,00 даёт 391 ฿/USDT — это опечатка, а не сделка."""
    wid = _wallet(TEODOR, 'Теодор')
    r = cli.post('/api/deals', json=_payload(wid, payout_amount_usdt=46.30))
    assert r.status_code == 400
    assert 'коридор' in r.get_json()['error']


def test_галка_чистит_ранее_отмеченный_перевод(cli):
    """Сделку завели с хешем, потом выяснилось, что фаундер платил своими."""
    wid = _wallet(TEODOR, 'Теодор')
    created = cli.post('/api/deals', json=_payload(
        wid, payout_no_conversion=False, payout_amount_usdt=None,
        payout_tx_hashes=[{'hash': _uid(), 'amount_usdt': 400.0, 'to_address': 'TClient'}],
    )).get_json()['deal']

    r = cli.put(f"/api/deals/{created['id']}", json={
        'payout_no_conversion': True, 'payout_amount_usdt': 463.0,
        'payout_wallet_id': wid, 'payout_tx_hashes': [], 'skip_sync': True,
    })
    assert r.status_code == 200

    db = get_session()
    try:
        deal = db.query(Deal).get(created['id'])
        assert deal.payout_no_conversion is True
        assert deal.payout_tx_hashes is None
        assert deal.payout_tx_hash is None
        assert deal.payout_amount_usdt == 463.0    # ручная сумма, не сумма перевода
    finally:
        db.close()


def test_смена_источника_снимает_флаг(cli):
    """Выдали с карты — переводы снова обязательны, ручная сумма больше не в счёт."""
    wid = _wallet(TEODOR, 'Теодор')
    created = cli.post('/api/deals', json=_payload(wid)).get_json()['deal']

    r = cli.put(f"/api/deals/{created['id']}",
                json={'payout_source': 'binance', 'skip_sync': True})
    assert r.status_code == 200

    db = get_session()
    try:
        assert db.query(Deal).get(created['id']).payout_no_conversion is False
    finally:
        db.close()


# ── Возмещение ────────────────────────────────────────────────────────────

def _income_for(cli, deal_id, rub=40000.0):
    db = get_session()
    try:
        inc = SberIncome(uuid=_uid(), operation_date='2026-08-24', amount_rub=rub,
                         payer='Вадим', purpose='тест выдачи своими батами')
        db.add(inc)
        db.commit()
        inc_id = inc.id
        db.query(SberIncome).filter(SberIncome.id == inc_id).update(
            {'claimed_deal_id': deal_id})
        db.commit()
        return inc_id
    finally:
        db.close()


def _batch(cli, income_ids, tx_to_address, received_usdt, rate=84.8):
    db = get_session()
    try:
        conv = Conversion(broker='tradex', request_no='48', rate_rub_usdt=rate,
                          status=ConversionStatus.SENT)
        db.add(conv)
        db.flush()
        for iid in income_ids:
            inc = db.query(SberIncome).get(iid)
            db.add(ConversionSource(conversion_id=conv.id, sber_income_id=iid,
                                    amount_rub=inc.amount_rub))
        db.commit()
        conv_id = conv.id
    finally:
        db.close()

    orig = appmod._tron_tx_to_address
    appmod._tron_tx_to_address = lambda h: tx_to_address
    try:
        r = cli.post(f'/api/conversions/{conv_id}/txs',
                     json={'tx_hash': _uid(), 'amount_usdt': received_usdt}).get_json()
    finally:
        appmod._tron_tx_to_address = orig
    assert r['success'] is True
    return conv_id


def test_приход_на_кошелёк_фаундера_гасит_долг_сам(cli):
    """Он забирает своё из прихода: возмещение на ручную сумму, маржа остаётся нам."""
    wid = _wallet(TEODOR, 'Теодор')
    deal_id = cli.post('/api/deals', json=_payload(wid)).get_json()['deal']['id']
    _batch(cli, [_income_for(cli, deal_id)], TEODOR, 470.55)

    db = get_session()
    try:
        deal = db.query(Deal).get(deal_id)
        assert deal.reimbursement_id is not None
        reimb = db.query(Reimbursement).get(deal.reimbursement_id)
        assert reimb.kind == 'auto'
        assert round(reimb.amount_usdt, 2) == 463.0      # не доля 470.55
        assert reimb.settled_by_payin_tx_id is not None  # хеш входящего, своего нет
        assert deal.status == DealStatus.COMPLETED
    finally:
        db.close()


def test_приход_на_чужой_кошелёк_оставляет_сделку_в_очереди(cli):
    """USDT упал Виталию — фаундеру нужен реальный перевод."""
    wid = _wallet(TEODOR, 'Теодор')
    _wallet(VITALY, 'кошелек виталия с мультисингом')
    deal_id = cli.post('/api/deals', json=_payload(wid)).get_json()['deal']['id']
    _batch(cli, [_income_for(cli, deal_id)], VITALY, 470.55)

    db = get_session()
    try:
        assert db.query(Deal).get(deal_id).reimbursement_id is None
    finally:
        db.close()

    pending = cli.get('/api/reimbursements/pending').get_json()
    deals = [d for g in pending['by_founder'] for d in g['deals']]
    assert any(d['id'] == deal_id and d['payout_no_conversion'] for d in deals)


def test_в_сводке_видно_что_конвертации_не_было(cli):
    """Иначе пустой хеш выдачи читается как «перевод потеряли»."""
    wid = _wallet(TEODOR, 'Теодор')
    _wallet(VITALY, 'кошелек виталия с мультисингом')
    deal_id = cli.post('/api/deals', json=_payload(wid)).get_json()['deal']['id']
    conv_id = _batch(cli, [_income_for(cli, deal_id)], VITALY, 470.55)

    db = get_session()
    try:
        dist = conversion_distribution(db, db.query(Conversion).get(conv_id))
    finally:
        db.close()

    group = dist['to_return'][0]
    assert group['no_conversion'] is True
    assert group['deals'][0]['no_conversion'] is True
    assert group['deals'][0]['cost_usdt'] == 463.0
    # Сумма возврата известна — предупреждать «переводы не отмечены» не о чем
    assert dist['needs_input'] is False
