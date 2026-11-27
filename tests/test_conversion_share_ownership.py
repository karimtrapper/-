"""A conversion must never clear another conversion's share of the same hash."""
import uuid

import app as m


def test_recalculation_preserves_other_conversion_share():
    db = m.get_session()
    try:
        tx = m.PayinTx(tx_hash=uuid.uuid4().hex * 2, amount_usdt=200, source='tronscan')
        db.add(tx)
        deals, convs = [], []
        for _ in range(2):
            deal = m.Deal(client_name='ownership', deal_type=m.DealType.PAY_IN)
            conv = m.Conversion(status=m.ConversionStatus.RECEIVED)
            db.add_all([deal, conv])
            db.flush()
            income = m.SberIncome(uuid=uuid.uuid4().hex, amount_rub=10000,
                                  claimed_deal_id=deal.id)
            db.add(income)
            db.flush()
            db.add_all([
                m.ConversionSource(conversion_id=conv.id, sber_income_id=income.id,
                                   amount_rub=10000),
                m.ConversionTx(conversion_id=conv.id, payin_tx_id=tx.id, amount_usdt=100),
                m.PayinTxUse(tx_id=tx.id, deal_id=deal.id, amount_usdt=100),
            ])
            db.flush()
            deals.append(deal)
            convs.append(conv)
        other = db.query(m.PayinTxUse).filter_by(tx_id=tx.id, deal_id=deals[1].id).one()
        other_id = other.id
        m._apply_conversion_shares(db, convs[0])
        db.expire_all()
        preserved = db.query(m.PayinTxUse).filter_by(id=other_id).one()
        assert preserved.deal_id == deals[1].id
        assert preserved.amount_usdt == 100
        assert tx.used_usdt() == 200
        assert tx.free_usdt() == 0
        m._clear_conversion_payin_uses(db, convs[0])
        assert db.query(m.PayinTxUse).filter_by(id=other_id).one().amount_usdt == 100
        assert tx.used_usdt() == 100
    finally:
        db.rollback()
        db.close()
