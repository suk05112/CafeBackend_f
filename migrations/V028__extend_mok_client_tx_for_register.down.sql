-- GNB-147: V027 롤백

ALTER TABLE mok_client_tx
    DROP COLUMN IF EXISTS consumed_at,
    DROP COLUMN IF EXISTS verified_at,
    DROP COLUMN IF EXISTS verified_gender,
    DROP COLUMN IF EXISTS verified_birthdate,
    DROP COLUMN IF EXISTS verified_phone,
    DROP COLUMN IF EXISTS verified_name;
