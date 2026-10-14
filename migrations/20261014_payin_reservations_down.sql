-- Stop writers first. Refuse rollback if new reservations/origins exist: never discard money or provenance.
DO $$ BEGIN
 IF EXISTS (SELECT 1 FROM payin_tx_uses WHERE deal_id IS NULL OR stand_generation IS NOT NULL OR stand_cnv_id IS NOT NULL OR conversion_id IS NOT NULL) THEN
 RAISE EXCEPTION 'Cannot roll back: reservation/provenance rows exist. Restore the pre-deployment backup or settle and archive them explicitly first.';
 END IF;
END $$;
DROP INDEX IF EXISTS uq_payin_tx_stand;
DROP INDEX IF EXISTS uq_payin_tx_deal;
ALTER TABLE payin_tx_uses DROP CONSTRAINT IF EXISTS ck_payin_use_owner;
ALTER TABLE payin_tx_uses ALTER COLUMN deal_id SET NOT NULL;
ALTER TABLE payin_tx_uses ADD CONSTRAINT uq_payin_tx_use UNIQUE (tx_id, deal_id);
ALTER TABLE payin_tx_uses DROP COLUMN conversion_id;
ALTER TABLE payin_tx_uses DROP COLUMN stand_cnv_id;
ALTER TABLE payin_tx_uses DROP COLUMN stand_generation;
