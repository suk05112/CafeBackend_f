-- 새로운 정산 테이블 생성
-- settlement: 정산 마스터 테이블
-- settlement_details: 정산 상세 테이블

-- 주의: 기존 settlement 테이블이 있으면 백업 후 삭제 필요
-- 기존 테이블 백업 (수동 실행 필요: CREATE TABLE settlement_old AS SELECT * FROM settlement;)

-- 1. 기존 settlement 테이블이 있으면 백업 테이블로 이름 변경
-- RENAME TABLE settlement TO settlement_old;

-- 2. settlement 테이블 (정산 마스터) - 새로 생성
CREATE TABLE IF NOT EXISTS settlement (
    settlement_id INT AUTO_INCREMENT PRIMARY KEY COMMENT '정산 ID',
    store_id INT NOT NULL COMMENT '매장 ID',
    cycle_id INT COMMENT '정산 주기 ID',
    period_start DATE NOT NULL COMMENT '정산 대상 기간 시작일',
    period_end DATE NOT NULL COMMENT '정산 대상 기간 종료일',
    total_sales_amount DECIMAL(15, 0) NOT NULL DEFAULT 0 COMMENT '총 매출액',
    total_fee_amount DECIMAL(15, 0) NOT NULL DEFAULT 0 COMMENT '총 수수료 (차감액)',
    net_payout_amount DECIMAL(15, 0) NOT NULL DEFAULT 0 COMMENT '실 지급액 (매출 - 수수료)',
    status ENUM('READY', 'PENDING', 'COMPLETED', 'HOLD') DEFAULT 'READY' COMMENT '정산 상태',
    payout_date DATE NULL COMMENT '실제 지급(예정)일',
    bank_name VARCHAR(50) COMMENT '지급 당시 매장 계좌 정보 (스냅샷)',
    account_number VARCHAR(100) COMMENT '계좌번호',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '생성일시',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일시',
    INDEX idx_store_id (store_id),
    INDEX idx_cycle_id (cycle_id),
    INDEX idx_payout_date (payout_date),
    INDEX idx_status (status),
    INDEX idx_period (period_start, period_end)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='정산 마스터 테이블';

-- 3. settlement_details 테이블 (정산 상세)
CREATE TABLE IF NOT EXISTS settlement_details (
    id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '상세 ID',
    settlement_id INT NOT NULL COMMENT '정산 ID',
    gifticon_id BIGINT NOT NULL COMMENT '기프티콘 ID',
    sales_amount INT NOT NULL COMMENT '판매가',
    fee_amount INT NOT NULL COMMENT '수수료액',
    settlement_amount INT NOT NULL COMMENT '실지급액 (sales - fee)',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '생성일시',
    FOREIGN KEY (settlement_id) REFERENCES settlement(settlement_id) ON DELETE CASCADE,
    FOREIGN KEY (gifticon_id) REFERENCES gifticon(id) ON DELETE CASCADE,
    UNIQUE KEY uk_gifticon_id (gifticon_id) COMMENT '하나의 기프티콘은 딱 한 번만 정산되어야 함',
    INDEX idx_settlement_id (settlement_id),
    INDEX idx_gifticon_id (gifticon_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='정산 상세 테이블';
