-- GNB-142: 롤백 - 정산주기 총액 기반 프로모션 방식을 기프티콘 단위 방식으로 복구

-- 3. settlement 테이블 롤백: 추가한 컬럼 제거
ALTER TABLE settlement
    DROP FOREIGN KEY fk_settlement_promo;

ALTER TABLE settlement
    DROP COLUMN promo_fee_amount,
    DROP COLUMN promo_fee_vat,
    DROP COLUMN promo_fee_supply,
    DROP COLUMN original_fee_amount,
    DROP COLUMN original_fee_vat,
    DROP COLUMN original_fee_supply,
    DROP COLUMN applied_fee_rate,
    DROP COLUMN applied_promo_id,
    DROP COLUMN base_fee_rate;

-- 2. settlement_details 테이블 롤백: 삭제한 컬럼 복원 (V003 스냅샷 기준)
ALTER TABLE settlement_details
    ADD COLUMN fee_amount INT NOT NULL DEFAULT 0 COMMENT '수수료액' AFTER sales_amount,
    ADD COLUMN settlement_amount INT NOT NULL DEFAULT 0 COMMENT '실지급액 (sales - fee)' AFTER fee_amount,
    ADD COLUMN base_fee_rate DECIMAL(5,2) DEFAULT NULL COMMENT '구매 시점 기본 수수료율 (%)' AFTER settlement_amount,
    ADD COLUMN applied_promo_id INT DEFAULT NULL COMMENT '적용된 프로모션 ID' AFTER base_fee_rate,
    ADD COLUMN applied_fee_rate DECIMAL(5,2) DEFAULT NULL COMMENT '최종 적용 수수료율 (%)' AFTER applied_promo_id,
    ADD COLUMN fee_supply INT DEFAULT NULL COMMENT '수수료 공급가 (원미만 절사)' AFTER applied_fee_rate,
    ADD COLUMN fee_vat INT DEFAULT NULL COMMENT '수수료 부가세 (10%, 반올림)' AFTER fee_supply;

-- 1. gifticon 테이블 롤백: 삭제한 컬럼 복원
ALTER TABLE gifticon
    ADD COLUMN base_fee_rate DECIMAL(5,2) DEFAULT NULL COMMENT '구매 시점 플랫폼 기본 수수료율 (%)' AFTER store_id,
    ADD COLUMN applied_promo_id INT DEFAULT NULL COMMENT '적용된 프로모션 ID (NULL=프로모션 없음)' AFTER base_fee_rate,
    ADD COLUMN applied_fee_rate DECIMAL(5,2) DEFAULT NULL COMMENT '최종 적용 수수료율 (%)' AFTER applied_promo_id,
    ADD CONSTRAINT fk_gifticon_promo FOREIGN KEY (applied_promo_id) REFERENCES fee_promotions(promo_id) ON DELETE SET NULL;

UPDATE migration_history SET rolled_back_at = NOW(), status = 'rolled_back' WHERE version = 'V024' AND status = 'applied';
