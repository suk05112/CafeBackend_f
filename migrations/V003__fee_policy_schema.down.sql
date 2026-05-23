-- GNB-52: 수수료 정책 개선 스키마 변경 (down)

-- 1. settlement_details 롤백
ALTER TABLE settlement_details
    DROP FOREIGN KEY fk_settlement_details_settlement;

ALTER TABLE settlement_details
    MODIFY COLUMN settlement_id INT NOT NULL COMMENT '정산 ID',
    DROP COLUMN fee_vat,
    DROP COLUMN fee_supply,
    DROP COLUMN applied_fee_rate,
    DROP COLUMN applied_promo_id,
    DROP COLUMN base_fee_rate,
    ADD CONSTRAINT settlement_details_ibfk_1 FOREIGN KEY (settlement_id) REFERENCES settlement(settlement_id) ON DELETE CASCADE;

-- 2. gifticon 롤백
ALTER TABLE gifticon
    DROP FOREIGN KEY fk_gifticon_promo,
    DROP COLUMN applied_promo_id,
    DROP COLUMN base_fee_rate;
