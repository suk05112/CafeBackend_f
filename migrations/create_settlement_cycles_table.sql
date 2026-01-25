-- settlement_cycles 테이블 생성
-- 정산 주기 정의 테이블 (1년치 미리 생성)

CREATE TABLE IF NOT EXISTS settlement_cycles (
    cycle_id INT AUTO_INCREMENT PRIMARY KEY COMMENT '정산 주기 ID',
    period_start_date DATE NOT NULL COMMENT '시작일',
    period_end_date DATE NOT NULL COMMENT '종료일 (시작일 + 4일)',
    payout_date DATE NOT NULL COMMENT '입금일 (종료일 + 10일, 영업일 기준)',
    status ENUM('OPEN', 'CLOSED') DEFAULT 'OPEN' COMMENT '상태',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '생성일시',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일시',
    INDEX idx_dates (period_start_date, period_end_date),
    INDEX idx_payout_date (payout_date),
    INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='정산 주기 테이블';
