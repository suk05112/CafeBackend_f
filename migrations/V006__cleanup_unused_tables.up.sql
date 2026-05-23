-- GNB-56: 불필요한 테이블/인덱스 정리

DROP TABLE IF EXISTS monthly_settlement;
DROP TABLE IF EXISTS order_settlement;

ALTER TABLE gifticon DROP INDEX idx_applied_fee_rate;
