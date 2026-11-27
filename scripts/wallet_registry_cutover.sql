-- Разовый скрипт переноса известных кошельков в единый реестр (prod).
-- Не запускается автоматически — только вручную, при переходе прод-CRM на
-- единый реестр кошельков (см. wallet-registry, задача Карима).
--
-- Идемпотентен: ON CONFLICT (address) обновляет флаги, только если они ещё
-- не заданы (owner IS NULL) — решение админа, принятое руками, не перезаписываем.
--
-- Перед запуском проверить, что колонки is_multisig/accepts_payin/owner уже
-- добавлены миграцией при старте приложения (ALTER TABLE ... ADD COLUMN IF NOT EXISTS).

INSERT INTO wallets (address, blockchain, label, active, is_monitored, is_balance,
                      is_multisig, accepts_payin, owner, created_at)
VALUES
    ('TKkeEVf2zySaWTLyX2qPwvi6kcdHRuPxkJ', 'TRON', 'Кошелёк Груши', TRUE, TRUE, FALSE,
     TRUE, TRUE, 'компания', NOW()),
    ('TVmgzMQ2zwV2DVPscBf98WRRdhrcpf5x5p', 'TRON', NULL, TRUE, TRUE, FALSE,
     FALSE, TRUE, 'Теодор', NOW()),
    ('TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn', 'TRON', NULL, TRUE, TRUE, FALSE,
     FALSE, TRUE, 'Андрей', NOW()),
    ('0x68aEA0F5386a57b48953F6fFF2f22D29D00D9ba9', 'ETH', 'Теодор · ERC-20', TRUE, TRUE, FALSE,
     FALSE, TRUE, 'Теодор', NOW())
ON CONFLICT (address) DO UPDATE SET
    is_multisig = CASE WHEN wallets.owner IS NULL THEN EXCLUDED.is_multisig ELSE wallets.is_multisig END,
    accepts_payin = CASE WHEN wallets.owner IS NULL THEN EXCLUDED.accepts_payin ELSE wallets.accepts_payin END,
    owner = CASE WHEN wallets.owner IS NULL THEN EXCLUDED.owner ELSE wallets.owner END;

-- Existing addresses remain usable by existing deals, but are hidden from new ones.
UPDATE wallets SET not_for_new_deals = TRUE
WHERE address IN ('TKkeEVf2zySaWTLyX2qPwvi6kcdHRuPxkJ',
                  'TVmgzMQ2zwV2DVPscBf98WRRdhrcpf5x5p',
                  'TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn',
                  '0x68aEA0F5386a57b48953F6fFF2f22D29D00D9ba9');

INSERT INTO wallets (address, blockchain, label, active, is_monitored, is_balance,
                     is_multisig, accepts_payin, owner, purpose, limit_usd,
                     initiator_roles, confirmer_roles, owner_can_alone,
                     signer_addresses, not_for_new_deals, created_at)
VALUES
    ('TDuDeRiwrLLN3hnnA57G5yM6ibg58A6wZk', 'TRON', 'Груша Недвижимость', TRUE, TRUE, FALSE,
     TRUE, TRUE, 'компания', 'realty', NULL,
     '["operator","findir"]', '["teodor"]', TRUE,
     '{"operator":"TAXgSzqBJzcstEkTBu4FJvEBH8SdxfV3QC","findir":"TDsLTB3uHKhTcB3hWRaKByg3pLtrMAHcgd","teodor":"TUzvaUjzRN5XLqDqbWB2VRKWQRtukXFYrN"}', FALSE, NOW()),
    ('TA6S3RBEY57jq8fXEVVsU6H9JZ18inenG4', 'TRON', 'Груша Обменник', TRUE, TRUE, FALSE,
     TRUE, TRUE, 'компания', 'exchange', 10000,
     '["operator"]', '["findir","teodor"]', FALSE,
     '{"operator":"TAXgSzqBJzcstEkTBu4FJvEBH8SdxfV3QC","findir":"TDsLTB3uHKhTcB3hWRaKByg3pLtrMAHcgd","teodor":"TUzvaUjzRN5XLqDqbWB2VRKWQRtukXFYrN"}', FALSE, NOW())
ON CONFLICT (address) DO UPDATE SET
    label = EXCLUDED.label, purpose = EXCLUDED.purpose,
    limit_usd = EXCLUDED.limit_usd, initiator_roles = EXCLUDED.initiator_roles,
    confirmer_roles = EXCLUDED.confirmer_roles,
    owner_can_alone = EXCLUDED.owner_can_alone,
    signer_addresses = EXCLUDED.signer_addresses,
    not_for_new_deals = FALSE;
