-- Run only after Flow Sole and other-account receipts and their conversions are removed.
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM sber_incomes WHERE COALESCE(account_key, 'sber') <> 'sber') THEN
    RAISE EXCEPTION 'Cannot drop account_key while non-Sber receipts exist';
  END IF;
  IF EXISTS (SELECT 1 FROM deals WHERE payin_method::text = 'FLOW_SOLE_REQS') THEN
    RAISE EXCEPTION 'Cannot drop Flow Sole method while its deals exist';
  END IF;
END $$;
ALTER TABLE sber_incomes DROP COLUMN IF EXISTS account_key;
DO $$
DECLARE
  labels TEXT;
BEGIN
  IF EXISTS (SELECT 1 FROM pg_enum e JOIN pg_type t ON t.oid=e.enumtypid
             WHERE t.typname='payinmethod' AND e.enumlabel='FLOW_SOLE_REQS') THEN
    SELECT string_agg(quote_literal(e.enumlabel), ', ' ORDER BY e.enumsortorder)
      INTO labels FROM pg_enum e JOIN pg_type t ON t.oid=e.enumtypid
      WHERE t.typname='payinmethod' AND e.enumlabel <> 'FLOW_SOLE_REQS';
    ALTER TYPE public.payinmethod RENAME TO payinmethod_before_flowsole;
    EXECUTE 'CREATE TYPE public.payinmethod AS ENUM (' || labels || ')';
    ALTER TABLE public.deals ALTER COLUMN payin_method TYPE public.payinmethod
      USING payin_method::text::public.payinmethod;
    DROP TYPE public.payinmethod_before_flowsole;
  END IF;
END $$;
