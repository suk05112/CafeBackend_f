-- GNB-144: 프로모션 타입 확장 (FIXED_PERIOD / PER_STORE_PERIOD)
-- 1. fee_promotions: promo_type, active_store_count 컬럼 추가, start_date/end_date NULL 허용
-- 2. fee_promotion_stores: 매장별 시작/종료일, applied_at, removed_at 컬럼 추가 (soft delete)
-- 3. fee_promotion_stores: 기존 unique(promo_id, store_id) 제거 → 활성 상태(removed_at IS NULL) 조회용 인덱스 추가
--    FK가 unique 인덱스를 참조 중이므로 FK 임시 drop → unique 인덱스 drop → FK 재생성 순으로 진행

-- 1. fee_promotions 테이블 확장
ALTER TABLE fee_promotions
    ADD COLUMN promo_type ENUM('FIXED_PERIOD', 'PER_STORE_PERIOD') NOT NULL DEFAULT 'FIXED_PERIOD' COMMENT '프로모션 타입 (공용/매장별)' AFTER title,
    ADD COLUMN active_store_count INT NOT NULL DEFAULT 0 COMMENT '현재 활성 상태로 등록된 매장 수' AFTER is_active,
    MODIFY COLUMN start_date DATE NULL COMMENT '프로모션 시작일 (FIXED_PERIOD만 사용)',
    MODIFY COLUMN end_date DATE NULL COMMENT '프로모션 종료일 (FIXED_PERIOD만 사용)';

-- 2. fee_promotion_stores 테이블 확장
ALTER TABLE fee_promotion_stores
    ADD COLUMN start_date DATE NULL COMMENT '매장별 프로모션 시작일 (PER_STORE_PERIOD만 사용)' AFTER store_id,
    ADD COLUMN end_date DATE NULL COMMENT '매장별 프로모션 종료일 (PER_STORE_PERIOD만 사용)' AFTER start_date,
    ADD COLUMN applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '매장 등록 시각' AFTER end_date,
    ADD COLUMN removed_at TIMESTAMP NULL COMMENT '매장 제거 시각 (soft delete, NULL=활성)' AFTER applied_at;

-- 3. FK 임시 drop (unique 인덱스가 FK 참조 대상이므로)
ALTER TABLE fee_promotion_stores DROP FOREIGN KEY fk_fps_promo;
ALTER TABLE fee_promotion_stores DROP FOREIGN KEY fk_fps_store;

-- 4. 기존 unique 제약 제거 (제거 후 재등록 허용하기 위함)
ALTER TABLE fee_promotion_stores DROP INDEX uq_promo_store;

-- 5. 활성 프로모션 조회용 인덱스 추가
CREATE INDEX idx_fps_active ON fee_promotion_stores (promo_id, store_id, removed_at);
CREATE INDEX idx_fps_store_active ON fee_promotion_stores (store_id, removed_at);

-- 6. FK 재생성
ALTER TABLE fee_promotion_stores
    ADD CONSTRAINT fk_fps_promo FOREIGN KEY (promo_id) REFERENCES fee_promotions(promo_id) ON DELETE CASCADE,
    ADD CONSTRAINT fk_fps_store FOREIGN KEY (store_id) REFERENCES store(id) ON DELETE CASCADE;
