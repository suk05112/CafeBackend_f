ALTER TABLE stats_daily_platform
    ADD COLUMN new_store_count INT DEFAULT 0 COMMENT '당일 신규 입점 매장 수' AFTER active_store_count,
    ADD COLUMN total_issued_amount DECIMAL(15, 0) DEFAULT 0 COMMENT '당일 발행 금액 합계' AFTER total_issued_count,
    ADD COLUMN total_payment_amount DECIMAL(15, 0) DEFAULT 0 COMMENT '당일 총 결제 금액' AFTER total_issued_amount;
