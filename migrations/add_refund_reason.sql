-- 7일 전/후 환불 사유 저장 (구매자/수신자 환불 모두)
ALTER TABLE refund
    ADD COLUMN reason VARCHAR(500) NULL COMMENT '환불 사유' AFTER account_number;
