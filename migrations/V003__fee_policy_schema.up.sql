-- GNB-52: 수수료 정책 개선 스키마 변경 (up)
-- 1. gifticon: 구매 시점 수수료율 정보 컬럼 추가
-- 2. settlement_details: 수수료 상세 스냅샷 컬럼 추가 + settlement_id NULL 허용

-- 1. gifticon 테이블
ALTER TABLE gifticon
    ADD COLUMN base_fee_rate DECIMAL(5,2) DEFAULT NULL COMMENT '구매 시점 플랫폼 기본 수수료율 (%)' AFTER store_id,
    ADD COLUMN applied_promo_id INT DEFAULT NULL COMMENT '적용된 프로모션 ID (NULL=프로모션 없음)' AFTER base_fee_rate,
    ADD CONSTRAINT fk_gifticon_promo FOREIGN KEY (applied_promo_id) REFERENCES fee_promotions(promo_id) ON DELETE SET NULL;

-- 2. settlement_details: settlement_id NULL 허용 (사용 시점 선생성, 배치 시 연결)
ALTER TABLE settlement_details
    DROP FOREIGN KEY settlement_details_ibfk_1;

ALTER TABLE settlement_details
    MODIFY COLUMN settlement_id INT DEFAULT NULL COMMENT '정산 ID (NULL=미정산)',
    ADD COLUMN base_fee_rate DECIMAL(5,2) DEFAULT NULL COMMENT '구매 시점 기본 수수료율 (%)' AFTER settlement_amount,
    ADD COLUMN applied_promo_id INT DEFAULT NULL COMMENT '적용된 프로모션 ID' AFTER base_fee_rate,
    ADD COLUMN applied_fee_rate DECIMAL(5,2) DEFAULT NULL COMMENT '최종 적용 수수료율 (%)' AFTER applied_promo_id,
    ADD COLUMN fee_supply INT DEFAULT NULL COMMENT '수수료 공급가 (원미만 절사)' AFTER applied_fee_rate,
    ADD COLUMN fee_vat INT DEFAULT NULL COMMENT '수수료 부가세 (10%, 반올림)' AFTER fee_supply,
    ADD CONSTRAINT fk_settlement_details_settlement FOREIGN KEY (settlement_id) REFERENCES settlement(settlement_id) ON DELETE CASCADE;
