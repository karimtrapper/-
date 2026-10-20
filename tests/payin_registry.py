"""Тестовый кошелёк реестра для прихода: ручной перенос требует, чтобы получатель перевода
был нашим активным кошельком (accepts_payin). Запись помечена и удаляется conftest-фикстурой."""
import app as m

FIXTURE_LABEL = 'test-payin-fixture'
RECEIVER = 'TReceiverWallet111111111111'


def ensure_payin_wallet(address=RECEIVER, blockchain='TRON'):
    db = m.SessionLocal()
    try:
        m.Base.metadata.create_all(m.engine, tables=[m.Wallet.__table__])
        if not db.query(m.Wallet).filter(m.Wallet.address == address).first():
            db.add(m.Wallet(address=address, blockchain=blockchain, label=FIXTURE_LABEL,
                            active=True, accepts_payin=True, is_monitored=False))
            db.commit()
    finally:
        db.close()
