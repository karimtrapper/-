"""Автозачёт: приход от брокера упал на тот же кошелёк, с которого платили за сделку.

По схеме флоу (21.08) деньги от брокера приходят на кошелёк, а дальше уходят на тот,
с которого выдавали клиенту. Если брокер отдал сразу на нужный кошелёк, переводить
нечего — обязательство закрыто самим приходом. Раньше такую сделку приходилось либо
держать в «ожидает возмещения» вечно, либо заводить фиктивное возмещение руками.

Запуск: cd Dev/CalcCRM && python -m pytest tests/test_auto_reimbursement.py -v
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
                 PayinTxUse, Reimbursement, ReimbursementTxUse, SberIncome, Wallet)

ANDREY = 'TWyLcjJzyQmiT1nt7gEn8BVoNSN94RGcHb'   # кошелёк, с которого платили
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


def _deal_with_income(cli, wallet_id, rub=34755.0, cost=383.14, thb=12500.0):
    """Сделка Романа из CNV-0002: выдана с кошелька оунера, рубли лежат на счёте."""
    db = get_session()
    try:
        inc = SberIncome(uuid=_uid(), operation_date='2026-08-19',
                         amount_rub=rub, payer='Roman', purpose='тест автозачёта')
        db.add(inc)
        db.commit()
        income_id = inc.id
    finally:
        db.close()

    deal = cli.post('/api/deals', json={
        'client_name': 'Roman - Grusha', 'status': 'pending',
        'payin_method': 'sber_reqs', 'payin_amount_rub': rub,
        'payout_method': 'transfer', 'payout_source': 'founder_personal',
        'payout_founder_name': 'Андрей', 'payout_wallet_id': wallet_id,
        'payout_amount_thb': thb, 'skip_sync': True,
        'payout_tx_hashes': [{'hash': _uid(), 'amount_usdt': cost, 'to_address': 'TClient'}],
    }).get_json()['deal']

    db = get_session()
    try:
        db.query(SberIncome).filter(SberIncome.id == income_id).update(
            {'claimed_deal_id': deal['id']})
        db.commit()
    finally:
        db.close()
    return deal['id'], income_id


def _batch(cli, income_ids, tx_to_address, received_usdt, rate=84.8):
    """Пачка: рубли ушли брокеру, приход USDT упал на указанный адрес."""
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

    import app as m
    orig = m._tron_tx_to_address
    m._tron_tx_to_address = lambda h: tx_to_address
    try:
        r = cli.post(f'/api/conversions/{conv_id}/txs',
                     json={'tx_hash': _uid(), 'amount_usdt': received_usdt}).get_json()
    finally:
        m._tron_tx_to_address = orig
    assert r['success'] is True
    return conv_id


def test_кошельки_совпали_долг_гасится_приходом(cli):
    """Брокер отдал USDT прямо на кошелёк оунера — переводить нечего."""
    wid = _wallet(ANDREY, 'Андрей')
    deal_id, income_id = _deal_with_income(cli, wid)
    _batch(cli, [income_id], ANDREY, 408.04)

    db = get_session()
    try:
        deal = db.query(Deal).get(deal_id)
        assert deal.reimbursement_id is not None, 'долг должен закрыться сам'
        reimb = db.query(Reimbursement).get(deal.reimbursement_id)
        assert reimb.kind == 'auto'
        # Возврат считается по себестоимости выдачи, а НЕ по доле пачки (408,04):
        # иначе оунеру уходит наша маржа
        assert round(reimb.amount_usdt, 2) == 383.14
        assert deal.payout_amount_usdt == 383.14
        assert deal.profit_usdt == 24.90
        assert deal.status == DealStatus.COMPLETED
        # Показываем ВХОДЯЩИЙ хеш — исходящего перевода не было
        assert reimb.settled_by_payin_tx_id is not None
    finally:
        db.close()


def test_кошельки_разные_автозачёта_нет(cli):
    """Приход упал на другой кошелёк — нужен реальный перевод, сделка ждёт."""
    wid = _wallet(ANDREY, 'Андрей')
    deal_id, income_id = _deal_with_income(cli, wid)
    _batch(cli, [income_id], VITALY, 408.04)

    db = get_session()
    try:
        deal = db.query(Deal).get(deal_id)
        assert deal.reimbursement_id is None
        assert deal.status == DealStatus.PENDING
    finally:
        db.close()


def test_без_себестоимости_автозачёта_нет(cli):
    """Переводы выдачи не отмечены — сумма долга неизвестна, гадать нельзя."""
    wid = _wallet(ANDREY, 'Андрей')
    db = get_session()
    try:
        inc = SberIncome(uuid=_uid(), operation_date='2026-08-19', amount_rub=34755.0,
                         payer='Roman', purpose='тест автозачёта')
        db.add(inc)
        db.commit()
        income_id = inc.id
    finally:
        db.close()
    deal = cli.post('/api/deals', json={
        'client_name': 'Roman - Grusha', 'status': 'pending',
        'payin_method': 'sber_reqs', 'payin_amount_rub': 34755.0,
        'payout_method': 'transfer', 'payout_source': 'founder_personal',
        'payout_founder_name': 'Андрей', 'payout_wallet_id': wid,
        'payout_amount_thb': 12500.0, 'skip_sync': True,
    }).get_json()['deal']
    db = get_session()
    try:
        db.query(SberIncome).filter(SberIncome.id == income_id).update(
            {'claimed_deal_id': deal['id']})
        db.commit()
    finally:
        db.close()

    _batch(cli, [income_id], ANDREY, 408.04)
    db = get_session()
    try:
        assert db.query(Deal).get(deal['id']).reimbursement_id is None
    finally:
        db.close()


def test_повторный_привяз_не_плодит_второе_возмещение(cli):
    """Идемпотентность: тот же приход привязали дважды — долг гасится один раз."""
    wid = _wallet(ANDREY, 'Андрей')
    deal_id, income_id = _deal_with_income(cli, wid)
    conv_id = _batch(cli, [income_id], ANDREY, 408.04)

    import app as m
    orig = m._tron_tx_to_address
    m._tron_tx_to_address = lambda h: ANDREY
    try:
        db = get_session()
        try:
            tx_hash = db.query(PayinTx).first().tx_hash
        finally:
            db.close()
        cli.post(f'/api/conversions/{conv_id}/txs',
                 json={'tx_hash': tx_hash, 'amount_usdt': 408.04})
    finally:
        m._tron_tx_to_address = orig

    db = get_session()
    try:
        assert db.query(Reimbursement).count() == 1
    finally:
        db.close()


def test_сделка_без_долга_не_попадает_в_автозачёт(cli):
    """Оплачено со счёта IPPS — возмещать некому, возмещение заводить не за что."""
    wid = _wallet(ANDREY, 'Андрей')
    db = get_session()
    try:
        inc = SberIncome(uuid=_uid(), operation_date='2026-08-18', amount_rub=30535.46,
                         payer='Радимир', purpose='sansiri')
        db.add(inc)
        db.commit()
        income_id = inc.id
    finally:
        db.close()
    deal = cli.post('/api/deals', json={
        'client_name': 'Радимир', 'status': 'pending',
        'payin_method': 'sber_reqs', 'payin_amount_rub': 30535.46,
        'payout_method': 'transfer', 'payout_source': 'founder_personal',
        'payout_founder_name': 'Андрей', 'payout_wallet_id': wid,
        'payout_amount_thb': 11500.0, 'needs_reimbursement': False, 'skip_sync': True,
        'payout_tx_hashes': [{'hash': _uid(), 'amount_usdt': 358.50}],
    }).get_json()['deal']
    db = get_session()
    try:
        db.query(SberIncome).filter(SberIncome.id == income_id).update(
            {'claimed_deal_id': deal['id']})
        db.commit()
    finally:
        db.close()

    _batch(cli, [income_id], ANDREY, 358.50)
    db = get_session()
    try:
        assert db.query(Deal).get(deal['id']).reimbursement_id is None
        assert db.query(Reimbursement).count() == 0
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────────────
# Раскладка прихода: пачка не закрыта, пока приход не разложен до нуля
# ─────────────────────────────────────────────────────────────────────────────

def test_раскладка_cnv_0002(cli):
    """Боевой кейс: 1 918 USDT = 770,92 вернуть + 1 101,92 без возврата + 45,16 маржа.

    Возврат считается по себестоимости выдачи (383,14 + 387,78), а доли пачки
    у сделок Романа 408,04 + 408,04 — разница и есть наша маржа.
    """
    wid = _wallet(ANDREY, 'Андрей')
    d1, i1 = _deal_with_income(cli, wid, rub=34755.0, cost=383.14, thb=12500.0)
    d2, i2 = _deal_with_income(cli, wid, rub=34755.0, cost=387.78, thb=12650.0)

    # Две сделки оплачены со счёта IPPS — возвращать некому
    ipps = []
    for rub, cost, thb in ((63320.76, 743.42, 24000.0), (30535.46, 358.50, 11500.0)):
        db = get_session()
        try:
            inc = SberIncome(uuid=_uid(), operation_date='2026-08-19', amount_rub=rub,
                             payer='клиент', purpose='ipps')
            db.add(inc)
            db.commit()
            iid = inc.id
        finally:
            db.close()
        deal = cli.post('/api/deals', json={
            'client_name': 'Клиент IPPS', 'status': 'pending',
            'payin_method': 'sber_reqs', 'payin_amount_rub': rub,
            'payout_method': 'transfer', 'payout_source': 'founder_personal',
            'payout_founder_name': 'Андрей', 'payout_wallet_id': wid,
            'payout_amount_thb': thb, 'needs_reimbursement': False, 'skip_sync': True,
        }).get_json()['deal']
        db = get_session()
        try:
            db.query(SberIncome).filter(SberIncome.id == iid).update(
                {'claimed_deal_id': deal['id']})
            db.commit()
        finally:
            db.close()
        ipps.append(iid)

    # Приход упал на чужой кошелёк — автозачёта быть не должно, только раскладка
    conv_id = _batch(cli, [i1, i2] + ipps, VITALY, 1918.00)

    d = cli.get(f'/api/conversions/{conv_id}/distribution').get_json()
    assert d['success'] is True
    assert d['received_usdt'] == 1918.00
    assert len(d['to_return']) == 1
    ret = d['to_return'][0]
    assert ret['address'] == ANDREY
    assert ret['amount_usdt'] == 770.92
    assert sorted(x['deal_id'] for x in ret['deals']) == sorted([d1, d2])
    assert d['no_return_usdt'] == 1101.92
    assert d['margin_usdt'] == 45.16
    assert d['stays_usdt'] == 1147.08
    assert d['balanced'] is True
    assert d['needs_input'] is False


def test_раскладка_без_себестоимости_не_сходится(cli):
    """Переводы выдачи не отмечены — сумма возврата неизвестна, «сошлось» соврало бы."""
    wid = _wallet(ANDREY, 'Андрей')
    db = get_session()
    try:
        inc = SberIncome(uuid=_uid(), operation_date='2026-08-19', amount_rub=34755.0,
                         payer='Roman', purpose='тест')
        db.add(inc)
        db.commit()
        iid = inc.id
    finally:
        db.close()
    deal = cli.post('/api/deals', json={
        'client_name': 'Roman - Grusha', 'status': 'pending',
        'payin_method': 'sber_reqs', 'payin_amount_rub': 34755.0,
        'payout_method': 'transfer', 'payout_source': 'founder_personal',
        'payout_founder_name': 'Андрей', 'payout_wallet_id': wid,
        'payout_amount_thb': 12500.0, 'skip_sync': True,
    }).get_json()['deal']
    db = get_session()
    try:
        db.query(SberIncome).filter(SberIncome.id == iid).update(
            {'claimed_deal_id': deal['id']})
        db.commit()
    finally:
        db.close()

    conv_id = _batch(cli, [iid], VITALY, 408.04)
    d = cli.get(f'/api/conversions/{conv_id}/distribution').get_json()
    assert d['needs_input'] is True
    assert d['balanced'] is False
    assert d['to_return'][0]['deals'][0]['cost_usdt'] is None


def test_раскладка_показывает_автозачёт(cli):
    """Долг закрыт приходом — в раскладке он в «уже закрыто», а не в «вернуть»."""
    wid = _wallet(ANDREY, 'Андрей')
    _d, iid = _deal_with_income(cli, wid)
    conv_id = _batch(cli, [iid], ANDREY, 408.04)

    d = cli.get(f'/api/conversions/{conv_id}/distribution').get_json()
    assert d['to_return'] == []
    assert len(d['settled']) == 1
    assert d['settled'][0]['kind'] == 'auto'
    assert d['settled'][0]['amount_usdt'] == 383.14
    assert d['stays_usdt'] == 24.90         # приход 408,04 минус долг 383,14
    assert d['balanced'] is True


def test_раскладка_показывает_wl_сделку_обменника(cli):
    """Приход по WL-сделке — не «без сделки» и не наша маржа.

    Клиент мерчанта платит по ссылке WL-бота, эквайринг Сбера кладёт деньги нам,
    а клиенту выдаёт мерчант. Возврата оунеру тут нет, но и в «остаётся у нас»
    эти деньги записывать нельзя — они уйдут мерчанту заявкой в боте.
    """
    from app import ReestrSnapshot
    import json as _json

    db = get_session()
    try:
        db.query(ReestrSnapshot).filter(ReestrSnapshot.view == 'deals').delete()
        db.add(ReestrSnapshot(view='deals', payload=_json.dumps([
            {'wl': 'WL-0393', 'merchant': 'Four exchange', 'author': 'Artyom',
             'rub': 112600.0, 'usdt': 1265.45, 'dt': '19.08 14:20'}])))
        # 111 811,80 на счёте = 112 600 минус эквайринг 0,7 %
        inc = SberIncome(uuid=_uid(), operation_date='2026-08-19', amount_rub=111811.80,
                         payer='Московский банк Сбербанка России',
                         purpose=('Зачисление средств по операциям эквайринга. '
                                  'Мерчант №781003872118. Комиссия 788.20.'))
        db.add(inc)
        db.commit()
        iid = inc.id
    finally:
        db.close()

    conv_id = _batch(cli, [iid], VITALY, 1290.68)
    d = cli.get(f'/api/conversions/{conv_id}/distribution').get_json()
    assert d['success'] is True
    assert d['unassigned_usdt'] == 0, 'WL-сделка не должна попадать в «приходы без сделки»'
    assert len(d['wl_deals']) == 1
    assert d['wl_deals'][0]['wl'] == 'WL-0393'
    assert d['wl_deals'][0]['merchant'] == 'Four exchange'
    assert d['wl_deals'][0]['share_usdt'] == 1290.68
    # К выплате мерчанту — из реестра бота, а не доля пачки: доля включает нашу маржу
    assert d['wl_deals'][0]['to_pay_usdt'] == 1265.45
    assert d['wl_deals'][0]['margin_usdt'] == 25.23
    assert d['wl_usdt'] == 1265.45
    assert d['stays_usdt'] == 25.23, 'нам остаётся только маржа, выплата уйдёт мерчанту'
    assert d['balanced'] is True

    db = get_session()
    try:
        db.query(ReestrSnapshot).filter(ReestrSnapshot.view == 'deals').delete()
        db.commit()
    finally:
        db.close()
