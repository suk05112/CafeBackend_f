-- refund_type에 EXPIRY 추가: 유효기간 만료 자동 환불
ALTER TABLE refund
    MODIFY COLUMN refund_type ENUM('PURCHASER', 'RECEIVER', 'EXPIRY') NOT NULL
        COMMENT '구매자 환불 / 수신자 환불 / 유효기간 만료 환불';
