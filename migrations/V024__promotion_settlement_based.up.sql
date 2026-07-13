-- GNB-142: 카페 프로모션 정산주기 총액 기반 적용 방식으로 변경
-- 1. gifticon: 수수료 관련 컬럼 삭제
-- 2. settlement_details: 개별 기프티콘 수수료 컬럼 삭제 (총액 기반으로 변경되므로)
-- 3. settlement: 프로모션 및 원본/할인 후 수수료 스냅샷 컬럼 추가

INSERT INTO migration_history (version, filename, applied_at, status)
VALUES ('V024', 'V024__promotion_settlement_based.up.sql', NOW(), 'applied');

-- 1. gifticon 테이블: 수수료 관련 컬럼 삭제
ALTER TABLE gifticon
    DROP FOREIGN KEY fk_gifticon_promo;

ALTER TABLE gifticon
    DROP COLUMN base_fee_rate,
    DROP COLUMN applied_fee_rate,
    DROP COLUMN applied_promo_id;

-- 2. settlement_details 테이블: 개별 기프티콘 수수료 컬럼 삭제
ALTER TABLE settlement_details
    DROP COLUMN fee_amount,
    DROP COLUMN settlement_amount,
    DROP COLUMN base_fee_rate,
    DROP COLUMN applied_promo_id,
    DROP COLUMN applied_fee_rate,
    DROP COLUMN fee_supply,
    DROP COLUMN fee_vat;

-- 3. settlement 테이블: 프로모션 관련 및 원본/할인 후 수수료 스냅샷 컬럼 추가
ALTER TABLE settlement
    ADD COLUMN base_fee_rate DECIMAL(5,2) DEFAULT NULL COMMENT '기본 수수료율 스냅샷 (%)' AFTER net_payout_amount,
    ADD COLUMN applied_promo_id INT DEFAULT NULL COMMENT '적용된 프로모션 ID (NULL=미적용)' AFTER base_fee_rate,
    ADD COLUMN applied_fee_rate DECIMAL(5,2) DEFAULT NULL COMMENT '실제 적용된 수수료율 (%)' AFTER applied_promo_id,
    ADD COLUMN original_fee_supply INT DEFAULT NULL COMMENT '프로모션 미적용 공급가' AFTER applied_fee_rate,
    ADD COLUMN original_fee_vat INT DEFAULT NULL COMMENT '프로모션 미적용 VAT (10%)' AFTER original_fee_supply,
    ADD COLUMN original_fee_amount INT DEFAULT NULL COMMENT '프로모션 미적용 총 수수료' AFTER original_fee_vat,
    ADD COLUMN promo_fee_supply INT DEFAULT NULL COMMENT '프로모션 적용 공급가 (NULL=미적용)' AFTER original_fee_amount,
    ADD COLUMN promo_fee_vat INT DEFAULT NULL COMMENT '프로모션 적용 VAT' AFTER promo_fee_supply,
    ADD COLUMN promo_fee_amount INT DEFAULT NULL COMMENT '프로모션 적용 총 수수료' AFTER promo_fee_vat,
    ADD CONSTRAINT fk_settlement_promo FOREIGN KEY (applied_promo_id) REFERENCES fee_promotions(promo_id) ON DELETE SET NULL;
