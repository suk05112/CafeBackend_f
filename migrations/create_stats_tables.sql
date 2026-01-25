-- 통계 테이블 생성
-- stats_daily_platform: 플랫폼 일별 통계
-- stats_daily_store: 매장 일별 통계

-- 1. 플랫폼 일별 통계 테이블
CREATE TABLE IF NOT EXISTS stats_daily_platform (
    target_date DATE PRIMARY KEY COMMENT '기준 날짜',
    total_issued_count INT DEFAULT 0 COMMENT '전체 발행 수',
    total_used_count INT DEFAULT 0 COMMENT '전체 사용 수',
    total_sales_amount DECIMAL(15, 0) DEFAULT 0 COMMENT '전체 매출액',
    total_fee_revenue DECIMAL(15, 0) DEFAULT 0 COMMENT '플랫폼의 순수 수수료 매출',
    active_store_count INT DEFAULT 0 COMMENT '당일 거래가 발생한 매장 수',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '생성일시',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일시',
    INDEX idx_target_date (target_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='플랫폼 일별 통계 테이블';

-- 2. 매장 일별 통계 테이블
CREATE TABLE IF NOT EXISTS stats_daily_store (
    stat_id INT AUTO_INCREMENT PRIMARY KEY COMMENT '통계 ID',
    store_id INT NOT NULL COMMENT '매장 ID',
    target_date DATE NOT NULL COMMENT '기준 날짜',
    realtime_sales DECIMAL(15, 0) DEFAULT 0 COMMENT '당일 판매 합계',
    expected_payout DECIMAL(15, 0) DEFAULT 0 COMMENT '당일 정산 예정액 (매출 - 수수료)',
    used_count INT DEFAULT 0 COMMENT '당일 사용 건수',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '생성일시',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일시',
    UNIQUE KEY unique_store_date (store_id, target_date) COMMENT '한 매장의 특정 날짜 데이터는 유일',
    INDEX idx_store_id (store_id),
    INDEX idx_target_date (target_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='매장 일별 통계 테이블';
