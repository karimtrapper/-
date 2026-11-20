"""Editing a posted leasehold classification preserves existing financial entries."""
from datetime import datetime
import json
import re
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app as crm

export_reclassification = crm._sync_reclassified_deal_gsheet
export_realty = crm.sync_realty_deal_to_gsheet


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    engine = create_engine(f'sqlite:///{tmp_path / "reclassification.sqlite"}')
    crm.Base.metadata.create_all(engine)
    monkeypatch.setattr(crm, 'get_session', sessionmaker(bind=engine))
    monkeypatch.setenv('LOCAL_NO_AUTH', '1')
    for name in ('_tx_info_by_network', '_tron_tx_amount', '_etherscan_tx_info'):
        monkeypatch.setattr(crm, name, lambda *args: pytest.fail('Historical edit looked up a hash'))
    monkeypatch.setattr(crm, '_sync_reclassified_deal_gsheet', lambda deal: {'ok': True})
    monkeypatch.setattr(crm, 'sync_realty_deal_to_gsheet', lambda deal: {'ok': True})
    try:
        with crm.app.test_client() as http:
            yield http
    finally:
        engine.dispose()


def seed_direct(db, *, kind='exchange', reimbursed=False):
    outgoing = '0x' + 'a' * 64
    incoming = ['b' * 64, 'c' * 64]
    card = crm.BankCard(bank_name='Bangkok Bank', card_name='QA card',
                        holder_name='Андрей', personal_owner='andrey', balance_thb=41234)
    deal = crm.Deal(
        deal_type=crm.DealType.PAY_IN, deal_kind=kind, created_at=datetime(2026, 11, 5),
        status=crm.DealStatus.COMPLETED, payout_method=crm.PayOutMethod.TRANSFER,
        payout_source=crm.PayOutSource.FOUNDER_PERSONAL, payout_founder_name='Андрей',
        payout_amount_thb=1125699, payout_amount_usdt=34636.91,
        payout_tx_hash=outgoing, payout_tx_hashes=json.dumps([
            {'hash': outgoing, 'network': 'erc20', 'amount_usdt': 34500 if reimbursed else 34636.91},
        ]),
        payin_method=crm.PayInMethod.CRYPTO_DIRECT, payin_amount_usdt=35000,
        payin_tx_hash=incoming[0], payin_tx_hashes=json.dumps([
            {'hash': tx, 'network': 'trc20', 'amount_usdt': 17500} for tx in incoming
        ]),
        needs_reimbursement=False, bank_card=card, profit_usdt=363.09,
        net_profit_usdt=315, referrer_payout_usdt=48.09, realty_purpose='Unit QA',
    )
    if reimbursed:
        deal.reimbursement = crm.Reimbursement(founder_name='Андрей',
                                                amount_usdt=34636.91, kind='manual')
    db.add(deal)
    db.flush()
    tx = crm.PayoutTx(tx_hash=outgoing, network='erc20', amount_usdt=36000)
    db.add(crm.PayoutTxUse(deal_id=deal.id, tx=tx, amount_usdt=34500 if reimbursed else 34636.91))
    for h in incoming:
        db.add(crm.PayinTxUse(deal_id=deal.id, tx=crm.PayinTx(tx_hash=h, amount_usdt=17500),
                             amount_usdt=17500))
    return deal


def snapshot(db, deal_id):
    deal = db.get(crm.Deal, deal_id)
    values = {column.name: getattr(deal, column.name) for column in crm.Deal.__table__.columns
              if column.name not in ('deal_kind', 'notes', 'updated_at')}
    claims = []
    for model in (crm.PayinTxUse, crm.PayoutTxUse, crm.CardAllocation, crm.CashAllocation,
                  crm.WalletOperation):
        claims.append([[getattr(row, col.name) for col in model.__table__.columns]
                       for row in db.query(model).filter_by(deal_id=deal_id).order_by(model.id)])
    return values, claims, deal.bank_card.balance_thb


@pytest.mark.parametrize('kind,reimbursed', [('exchange', False), (None, False), ('exchange', True)])
def test_same_id_direct_move_and_offline_notes(ledger, kind, reimbursed):
    with crm.get_session() as db:
        deal = seed_direct(db, kind=kind, reimbursed=reimbursed)
        deal_id = deal.id
        db.commit()
        before = snapshot(db, deal_id)
    url = f'/api/deals/{deal_id}'
    assert ledger.get(url).json['deal']['reclassification_target'] == 'personal_realty'
    change = {'deal_kind': 'personal_realty', 'reclassify': True}
    refused = ledger.put(url, json={**change, 'payout_amount_thb': 1})
    assert refused.status_code == 409, refused.json
    with crm.get_session() as db:
        assert snapshot(db, deal_id) == before
        assert db.get(crm.Deal, deal_id).deal_kind == kind
    for _ in range(2):
        updated = ledger.put(url, json=change)
        assert updated.status_code == 200, updated.json
        assert updated.json['deal']['id'] == deal_id
        assert updated.json['deal']['payout_amount_usdt'] == 34636.91
    row = ledger.get(url).json['deal']
    assert row['reclassification_target'] == 'exchange'
    assert row['payout_wallet_id'] is None
    assert row['needs_reimbursement'] is False
    assert row['realty_purpose'] == 'Unit QA'
    assert not row.get('bank_card_name')
    assert ledger.put(url, json={'notes': 'Уточнение менеджера'}).status_code == 200
    with crm.get_session() as db:
        assert snapshot(db, deal_id) == before
    assert ledger.put(url, json={'deal_kind': 'exchange'}).status_code == 200
    assert ledger.put(url, json={'notes': 'Уточнение после смены типа'}).status_code == 200
    with crm.get_session() as db:
        assert snapshot(db, deal_id) == before


@pytest.mark.parametrize('card_name,owner,kind', [
    (crm.IPPS_CARD_NAME, None, 'ipps_realty'), ('QA personal', 'theodor', 'personal_realty'),
])
def test_card_reclassification_preserves_historic_rate_and_balance(ledger, card_name, owner, kind):
    with crm.get_session() as db:
        card = crm.BankCard(bank_name='SCB', card_name=card_name, personal_owner=owner, balance_thb=47000)
        card.topups.append(crm.CardTopup(amount_thb=80000, cost_usdt=1620, purchase_rate=49.38))
        deal = crm.Deal(deal_type=crm.DealType.PAY_IN, deal_kind='exchange',
                        payout_source=crm.PayOutSource.BANK_CARD, payout_method=crm.PayOutMethod.TRANSFER,
                        bank_card=card, payout_amount_thb=33000, payout_amount_usdt=1000,
                        status=crm.DealStatus.COMPLETED, needs_reimbursement=False)
        db.add(deal)
        db.flush()
        db.add(crm.CardAllocation(deal_id=deal.id, card_id=card.id,
                                  amount_thb=33000, cost_usdt=1000, card_rate=33))
        deal_id = deal.id
        db.commit()
        before = snapshot(db, deal_id)
    url = f'/api/deals/{deal_id}'
    assert ledger.get(url).json['deal']['reclassification_target'] == kind
    incompatible = 'personal_realty' if kind == 'ipps_realty' else 'ipps_realty'
    assert ledger.put(url, json={'deal_kind': incompatible}).status_code == 409
    corrected = ledger.put(url, json={'deal_kind': kind})
    assert corrected.status_code == 200, corrected.json
    assert ledger.put(url, json={'notes': 'Уточнение'}).status_code == 200
    with crm.get_session() as db:
        assert snapshot(db, deal_id) == before


class Worksheet:
    def __init__(self, title, rows):
        self.title = title
        self.rows = rows
        self.fail = False
        self.id = 1

    def col_values(self, col):
        return [row[col - 1] if len(row) >= col else '' for row in self.rows]

    def get_all_values(self):
        return [row.copy() for row in self.rows]

    def append_row(self, row, **kwargs):
        if self.fail:
            raise RuntimeError('mock Sheets interruption')
        self.rows.append(row)

    def insert_rows(self, rows, *, row, **kwargs):
        if self.fail:
            raise RuntimeError('mock Sheets interruption')
        self.rows[row - 1:row - 1] = rows

    def delete_rows(self, row):
        self.rows.pop(row - 1)

    def update(self, range_name, rows, **kwargs):
        start = int(re.search(r'\d+', range_name).group()) - 1
        self.rows[start:start + len(rows)] = rows


class Book:
    def __init__(self, sheets):
        self.sheets = {sheet.title: sheet for sheet in sheets}

    def worksheet(self, title):
        return self.sheets[title]

    def worksheets(self):
        return list(self.sheets.values())

    def batch_update(self, data):
        pass


@pytest.mark.parametrize('reverse', [False, True])
def test_export_is_exact_retryable_and_routes_future_manual_sync(ledger, monkeypatch, reverse):
    monkeypatch.setattr(crm, '_sync_reclassified_deal_gsheet', export_reclassification)
    with crm.get_session() as db:
        deal = seed_direct(db, kind='personal_realty' if reverse else 'exchange')
        deal_id = deal.id
        db.commit()

    def anchored(col, value):
        return [''] * (col - 1) + [str(value)]
    rid = crm.GSHEET_REALTY_ID_COL
    destination = 'exchange' if reverse else 'personal_realty'
    exchange = Worksheet(crm.GSHEET_WORKSHEET, [['№'], anchored(18, 99)])
    month = Worksheet(crm.realty_month_sheet_name(datetime(2026, 11, 5)),
                      [crm.GSHEET_REALTY_HEADERS.copy(), anchored(rid, 99)])
    summary = Worksheet(crm.GSHEET_REALTY_ALL,
                        [crm.GSHEET_REALTY_HEADERS.copy(), anchored(rid, 99)])
    if reverse:
        month.rows.extend([anchored(rid, deal_id), anchored(rid, 102), anchored(rid, deal_id)])
        summary.rows.append(anchored(rid, deal_id))
    else:
        exchange.rows.extend([anchored(18, deal_id), anchored(18, 102), anchored(18, deal_id)])
    books = {crm.GSHEET_ID: Book([exchange]), crm.GSHEET_REALTY_ID: Book([month, summary])}
    monkeypatch.setattr(crm, 'get_gsheet_client', lambda: SimpleNamespace(open_by_key=books.__getitem__))
    failing = exchange if reverse else summary
    failing.fail = True
    url = f'/api/deals/{deal_id}'
    correction = {'deal_kind': destination, 'reclassify': True}
    old_sheet, old_col = (month, rid) if reverse else (exchange, 18)
    with crm.get_session() as delayed:
        # The notification loaded the old type before another session changed it.
        stale = delayed.get(crm.Deal, deal_id)
        partial = ledger.put(url, json=correction)
        assert partial.status_code == 200 and partial.json['export_pending']
        assert old_sheet.col_values(old_col).count(str(deal_id)) == 2

        failing.fail = False
        for _ in range(2):
            finished = ledger.put(url, json=correction)
            assert finished.status_code == 200 and not finished.json.get('export_pending'), finished.json
        # The actual callback must re-read under lock and follow the new route.
        callback = export_realty(stale) if reverse else crm.update_deal_in_gsheet(stale)
        assert callback['ok'], callback
    if not reverse:
        assert ledger.post('/api/deals/sync-gsheet', json={'deal_ids': [deal_id]}).status_code == 200
    assert old_sheet.col_values(old_col).count(str(deal_id)) == 0
    assert old_sheet.col_values(old_col).count('99') == old_sheet.col_values(old_col).count('102') == 1
    expected = [exchange] if reverse else [month, summary]
    for sheet in expected:
        col = 18 if reverse else rid
        assert [str(value) for value in sheet.col_values(col)].count(str(deal_id)) == 1
