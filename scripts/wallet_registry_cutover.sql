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
