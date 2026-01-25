-- gifticon 테이블에 applied_fee_rate 컬럼 추가
-- 기프티콘 생성 시점의 수수료율 저장

ALTER TABLE gifticon 
ADD COLUMN IF NOT EXISTS applied_fee_rate DECIMAL(5,2) DEFAULT NULL COMMENT '적용된 수수료율 (%)' AFTER store_id;

CREATE INDEX IF NOT EXISTS idx_applied_fee_rate ON gifticon(applied_fee_rate);
