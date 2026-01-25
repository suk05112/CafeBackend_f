-- order_history 테이블 생성
-- 주문의 모든 결제/취소 이력을 기록하는 테이블

CREATE TABLE IF NOT EXISTS order_history (
    history_id INT AUTO_INCREMENT PRIMARY KEY COMMENT '이력 ID',
    order_id INT NOT NULL COMMENT '주문 ID',
    action_type ENUM('PAYMENT', 'CANCEL', 'REFUND') NOT NULL COMMENT '행위 구분',
    amount DECIMAL(12, 0) NOT NULL COMMENT '발생 금액',
    status_to ENUM('PENDING', 'PAID', 'CANCELLED', 'PARTIAL_CANCELLED') NOT NULL COMMENT '변경된 상태',
    reason VARCHAR(255) COMMENT '취소 사유 등',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '생성일시',
    INDEX idx_order_id (order_id),
    INDEX idx_action_type (action_type),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='주문 이력 테이블';
