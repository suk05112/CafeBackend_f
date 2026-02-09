-- 기프티콘 환불 이력 테이블
-- 7일 이내: 구매자 환불(PURCHASER), 7일 이후: 수신자 환불(RECEIVER) 시 계좌정보 저장

CREATE TABLE IF NOT EXISTS refund (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '환불 ID',
    order_id INT NOT NULL COMMENT '주문 ID',
    refund_type ENUM('PURCHASER', 'RECEIVER') NOT NULL COMMENT '구매자 환불 / 수신자 환불',
    amount INT NOT NULL DEFAULT 0 COMMENT '환불 금액',
    status VARCHAR(20) NOT NULL DEFAULT 'COMPLETED' COMMENT 'REQUESTED, COMPLETED, FAILED',
    refunded_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '환불 처리 시각',
    receiver_user_id INT NULL COMMENT '수신자 user_id (RECEIVER일 때)',
    account_holder VARCHAR(50) NULL COMMENT '예금주명 (RECEIVER일 때)',
    bank_code VARCHAR(20) NULL COMMENT '은행코드 (RECEIVER일 때)',
    bank_name VARCHAR(100) NULL COMMENT '은행명 (RECEIVER일 때)',
    account_number VARCHAR(20) NULL COMMENT '계좌번호 (RECEIVER일 때)',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_order_id (order_id),
    INDEX idx_refund_type (refund_type),
    INDEX idx_refunded_at (refunded_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='기프티콘 환불 이력';
