-- EXPIRY 타입 제거: PURCHASER/RECEIVER만 남김
ALTER TABLE refund
    MODIFY COLUMN refund_type ENUM('PURCHASER', 'RECEIVER') NOT NULL
        COMMENT '구매자 환불 / 수신자 환불';
