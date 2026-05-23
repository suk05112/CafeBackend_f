-- GNB-58: 프로모션 구조 개선 rollback

-- 1. fee_promotions에 store_id 복구
ALTER TABLE fee_promotions ADD COLUMN store_id INT NOT NULL DEFAULT 0 COMMENT '매장 ID' AFTER promo_id;

-- 2. 데이터 복구 (fee_promotion_stores → fee_promotions.store_id, 첫 번째 매핑만)
UPDATE fee_promotions fp
JOIN fee_promotion_stores fps ON fp.promo_id = fps.promo_id
SET fp.store_id = fps.store_id;

-- 3. fee_promotion_stores 테이블 제거
DROP TABLE IF EXISTS fee_promotion_stores;
