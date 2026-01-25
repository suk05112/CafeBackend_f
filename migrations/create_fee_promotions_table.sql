-- fee_promotions 테이블 생성
-- 매장별 수수료 프로모션 관리 테이블

CREATE TABLE IF NOT EXISTS fee_promotions (
    promo_id INT AUTO_INCREMENT PRIMARY KEY COMMENT '프로모션 ID',
    store_id INT NOT NULL COMMENT '매장 ID',
    promo_fee_rate DECIMAL(5,2) NOT NULL COMMENT '프로모션 수수료율 (%)',
    start_date DATE NOT NULL COMMENT '시작일',
    end_date DATE NOT NULL COMMENT '종료일',
    is_active BOOLEAN DEFAULT TRUE COMMENT '활성화 여부',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '생성일시',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일시',
    INDEX idx_store_id (store_id),
    INDEX idx_dates (start_date, end_date),
    INDEX idx_is_active (is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='수수료 프로모션 테이블';
