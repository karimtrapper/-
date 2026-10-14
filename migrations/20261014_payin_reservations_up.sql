-- Run in a transaction, with application writers stopped. No existing row is changed.
ALTER TABLE payin_tx_uses ADD COLUMN IF NOT EXISTS stand_generation VARCHAR(64);
ALTER TABLE payin_tx_uses ADD COLUMN IF NOT EXISTS stand_cnv_id VARCHAR(128);
ALTER TABLE payin_tx_uses ADD COLUMN IF NOT EXISTS conversion_id INTEGER REFERENCES conversions(id);
ALTER TABLE payin_tx_uses ALTER COLUMN deal_id DROP NOT NULL;
ALTER TABLE payin_tx_uses DROP CONSTRAINT IF EXISTS uq_payin_tx_use;
CREATE UNIQUE INDEX IF NOT EXISTS uq_payin_tx_deal ON payin_tx_uses(tx_id, deal_id) WHERE deal_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_payin_tx_stand ON payin_tx_uses(tx_id, stand_generation, stand_cnv_id) WHERE deal_id IS NULL;
DO $$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='ck_payin_use_owner' AND conrelid='payin_tx_uses'::regclass) THEN
 ALTER TABLE payin_tx_uses ADD CONSTRAINT ck_payin_use_owner CHECK (deal_id IS NOT NULL OR (stand_generation IS NOT NULL AND stand_cnv_id IS NOT NULL));
 END IF;
END $$;
