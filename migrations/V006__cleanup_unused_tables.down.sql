-- GNB-56: rollback (테이블 복구는 스키마 재생성 필요, 데이터 복구 불가)

-- 인덱스만 복구
ALTER TABLE gifticon ADD INDEX idx_applied_fee_rate (applied_fee_rate);
