-- GNB-144: V025 롤백

-- 1. fee_promotion_stores 인덱스/컬럼 롤백 (IF EXISTS로 부분 실패 안전화)
DROP INDEX IF EXISTS idx_fps_store_active ON fee_promotion_stores;
DROP INDEX IF EXISTS idx_fps_active ON fee_promotion_stores;

ALTER TABLE fee_promotion_stores
    DROP COLUMN IF EXISTS removed_at,
    DROP COLUMN IF EXISTS applied_at,
    DROP COLUMN IF EXISTS end_date,
    DROP COLUMN IF EXISTS start_date;

-- 2. fee_promotions 컬럼 롤백 (uq_promo_store는 이미 존재하므로 재추가 불필요)
ALTER TABLE fee_promotions
    MODIFY COLUMN start_date DATE NOT NULL,
    MODIFY COLUMN end_date DATE NOT NULL,
    DROP COLUMN IF EXISTS active_store_count,
    DROP COLUMN IF EXISTS promo_type;
