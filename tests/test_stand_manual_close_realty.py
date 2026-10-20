"""manualOverride для недвижимости (Лизхолд/Аренда, kind=mf_realty) — та же
рубрика «известно/не хватает», что и у payin/payout для обмена, но по полям
инвойса (invoice_amount_thb, rates.usdtThb/client, company_percent,
назначение платежа, перевод в MF Corp, документы) — ровно тем же, что уже
проверяет crmGaps() на фронте для обычного закрытия через s27. Формула
прибыли — существующая compute_mf_realty, не новая (докладная СД-1489 от
координатора: 14.10 поля инвойса/курсов уже внесены на ранних шагах).

Запуск: python3 scripts/run_fenced_pytest.py tests/test_stand_manual_close_realty.py -v
"""
import json
import secrets

import app as m
import pytest

pytestmark = pytest.mark.usefixtures('stand_demo_environment')

# Хеш прихода обязателен всегда; уникален на тест, чтобы доли PayinTx не копились в общей БД.
PAYIN = {'hash': 'c' * 64}
REASON = 'Клиент заплатил наличными партнёру, флоу аренда+наличные задачник не поддерживает.'


def confirmed_echo(ref, network, sender, receiver, amount):
    return {'status': 'confirmed', 'verifiedAmount': float(amount or 0),
            'verifiedAt': '2026-01-01T00:00:00Z', 'from': sender or 'TSenderWallet11111111111111'}


def _realty_board(**overrides):
    """Сделка «как 1489» — шаги s4-s12 пройдены (инвойс/курсы/назначение/
    перевод в MF Corp/документы уже на доске), застряла после них на
    аренда+наличные, которую обычный флоу не поддерживает."""
    deal = {
        'id': 1489, 'code': 'СД-1489', 'client': 'Synthetic Rental',
        'type': 'Оплата недвижимости', 'kind': 'Аренда', 'manager': 'Елизавета',
        'step': 's14', 'closed': False, 'crmDealId': None, 'sentToClient': False,
        'pay': {}, 'payinHashes': [], 'log': [],
        'amountThb': 50000, 'companyPct': 1,
        'rates': {'usdtThb': 36.0, 'client': 35.0},
        'payTo': {'purpose': 'Оплата аренды виллы, авг 2026'},
        'mfPayout': [{'hash': 'b' * 64, 'net': 'TRC20', 'amount': 1388.89}],
        'docs': {'inv': True, 'receipt': True},
        'files': {'receipt': [{'file': 'receipt.pdf', 'mime': 'application/pdf',
                               'data': 'data:application/pdf;base64,JVBERi0='}]},
    }
    deal.update(overrides)
    return {'deals': [deal], 'notes': [], 'convs': []}


def _override(**overrides):
    override = {
        'reason': REASON,
        'payin': {'method': 'Наличные', 'amountUsdt': 1400, 'manualBankConfirmed': True,
                  'hashes': [{'hash': PAYIN['hash'], 'network': 'trc20',
                              'receiver': 'TReceiverWallet111111111111', 'amount': 1400}]},
    }
    override.update(overrides)
    return override


def _crm(**overrides):
    crm = {
        'deal_kind': 'mf_realty', 'client_name': 'Synthetic Rental', 'manager_name': 'Елизавета',
        'payin_method': 'partners_cash', 'payin_amount_usdt': 1400,
        'realty_purpose': 'Оплата аренды виллы, авг 2026',
        'invoice_amount_thb': 50000, 'buy_rate_thb_usdt': 36.0, 'sell_rate_thb_usdt': 35.0,
        'company_percent': 1,
        'payin_tx_hashes': [{'hash': PAYIN['hash'], 'network': 'trc20', 'amount_usdt': 1400}],
        'payout_tx_hashes': [{'hash': 'b' * 64, 'network': 'TRC20', 'amount_usdt': 1388.89}],
    }
    crm.update(overrides)
    return crm


def _setup(monkeypatch, board=None, role='manager'):
    monkeypatch.setattr(m, 'STAND_MODE', True)
    monkeypatch.setattr(m, 'verify_transfer', confirmed_echo)
    # sync_realty_deal_to_gsheet runs unconditionally for REALTY_KINDS (not
    # stand-gated, pre-existing behaviour unrelated to this feature) - stub
    # it so the test stays network-isolated like every other stand test.
    monkeypatch.setattr(m, 'sync_realty_deal_to_gsheet', lambda deal: None)
    # _stand_queue_close_card_note builds the card text via the same
    # _send_deal_telegram the prod path uses (only the delivery sender is
    # swapped for a local stand note) - that builder does its own network
    # lookups unrelated to this feature's own close/validation logic.
    monkeypatch.setattr(m, '_send_deal_telegram', lambda deal, sender=None: None)
    # _create_deal_impl's _enrich_payout_transfers independently re-verifies
    # payout_tx_hashes over the real network (pre-existing, applies to any
    # deal_kind with payout hashes, not introduced by this feature) - stub
    # the network call so a synthetic test hash doesn't trip the fence.
    monkeypatch.setattr(m, '_tx_info_by_network', lambda tx_hash, network: None)
    m._stand_migrate()
    PAYIN['hash'] = secrets.token_hex(32)
    db = m.get_session()
    try:
        user = m.AdminUser(username='realty-' + secrets.token_hex(6),
                           display_name='Realty Manager', role=role, password_hash='unused')
        db.add(user)
        db.flush()
        uid = user.id
        row = db.query(m.StandState).filter_by(id=1).first()
        if row is None:
            row = m.StandState(id=1)
            db.add(row)
        row.generation = secrets.token_hex(16)
        row.data = json.dumps(board or _realty_board(), ensure_ascii=False)
        row.version = 1
        db.commit()
        return uid
    finally:
        db.close()


def _client(uid):
    client = m.app.test_client()
    with client.session_transaction() as sess:
        sess['user_id'] = uid
        sess['username'] = 'realty'
        sess['display_name'] = 'Realty Manager'
    return client


def _post(client, override=None, crm=None, deal_id=1489, version=1):
    return client.post(f'/api/stand/deals/{deal_id}/crm-close',
                       json={'version': version, 'crm': crm or _crm(),
                             'manualOverride': override or _override()})


def test_realty_rental_closes_with_known_invoice_and_profit_matches_formula(monkeypatch):
    uid = _setup(monkeypatch)
    resp = _post(_client(uid))
    assert resp.status_code == 201, resp.json
    created = resp.json['deal']
    assert created['deal_kind'] == 'mf_realty'

    # Та же формула, что сервер применяет внутри _apply_mf_realty — не
    # завели вторую копию, дёрнули прямо её, чтобы тест действительно
    # сверял «совпадает с обычной CRM-формой», а не тавтологию.
    expected = m.compute_mf_realty(
        invoice_thb=50000, buy_rate=36.0, payin_usdt=1400, sell_rate=35.0,
        company_percent=1, company_sent_thb=None, agents=[],
        actual_cost_usdt=1388.89)
    assert created['profit_usdt'] == pytest.approx(expected['crypto_profit_usdt'], abs=0.01)
    assert created['company_fee_thb'] == pytest.approx(expected['company_fee_thb'], abs=0.01)
    assert created['invoice_amount_thb'] == 50000


def test_realty_rejects_when_invoice_amount_missing(monkeypatch):
    board = _realty_board()
    board['deals'][0]['amountThb'] = None
    uid = _setup(monkeypatch, board=board)
    resp = _post(_client(uid))
    assert resp.status_code == 400, resp.json
    assert resp.json['error'] == 'realty_invoice_missing'


def test_realty_rejects_when_rates_missing(monkeypatch):
    board = _realty_board()
    board['deals'][0]['rates'] = {}
    uid = _setup(monkeypatch, board=board)
    resp = _post(_client(uid))
    assert resp.status_code == 400, resp.json
    assert resp.json['error'] == 'realty_rate_missing'


def test_realty_rejects_when_purpose_missing(monkeypatch):
    board = _realty_board()
    board['deals'][0]['payTo'] = {}
    uid = _setup(monkeypatch, board=board)
    resp = _post(_client(uid))
    assert resp.status_code == 400, resp.json
    assert resp.json['error'] == 'realty_purpose_missing'


def test_realty_rejects_when_mf_transfer_missing(monkeypatch):
    board = _realty_board()
    board['deals'][0]['mfPayout'] = []
    uid = _setup(monkeypatch, board=board)
    resp = _post(_client(uid))
    assert resp.status_code == 400, resp.json
    assert resp.json['error'] == 'realty_transfer_missing'


def test_realty_rejects_when_docs_missing(monkeypatch):
    board = _realty_board()
    board['deals'][0]['docs'] = {}
    uid = _setup(monkeypatch, board=board)
    resp = _post(_client(uid))
    assert resp.status_code == 400, resp.json
    assert resp.json['error'] == 'realty_docs_missing'
