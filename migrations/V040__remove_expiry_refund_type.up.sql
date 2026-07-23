-- GNB-196: 유효기간 만료 자동환불 폐지에 따라 refund_type에서 EXPIRY 제거
ALTER TABLE refund
    MODIFY COLUMN refund_type ENUM('PURCHASER', 'RECEIVER') NOT NULL
        COMMENT '구매자 환불 / 수신자 환불';
