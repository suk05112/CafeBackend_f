-- GNB-58: 프로모션 구조 개선 - 하나의 프로모션을 여러 매장에 적용 가능

-- 1. fee_promotion_stores 매핑 테이블 생성
CREATE TABLE fee_promotion_stores (
    id INT AUTO_INCREMENT PRIMARY KEY,
    promo_id INT NOT NULL COMMENT '프로모션 ID',
    store_id BIGINT NOT NULL COMMENT '매장 ID',
    UNIQUE KEY uq_promo_store (promo_id, store_id),
    CONSTRAINT fk_fps_promo FOREIGN KEY (promo_id) REFERENCES fee_promotions(promo_id) ON DELETE CASCADE,
    CONSTRAINT fk_fps_store FOREIGN KEY (store_id) REFERENCES store(id) ON DELETE CASCADE
) COMMENT '프로모션-매장 매핑';

-- 2. 기존 데이터 마이그레이션 (fee_promotions.store_id → fee_promotion_stores)
INSERT INTO fee_promotion_stores (promo_id, store_id)
SELECT promo_id, store_id FROM fee_promotions;

-- 3. fee_promotions에서 store_id 컬럼 제거
ALTER TABLE fee_promotions DROP COLUMN store_id;
