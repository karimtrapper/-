-- Historical rows retain the Sber account without rewriting their other columns.
ALTER TYPE public.payinmethod ADD VALUE IF NOT EXISTS 'FLOW_SOLE_REQS';
ALTER TABLE sber_incomes ADD COLUMN IF NOT EXISTS account_key VARCHAR(80) DEFAULT 'sber';
