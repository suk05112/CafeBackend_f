-- 정산 테이블 생성 스크립트
-- 주문건별 정산과 월별 정산을 관리하는 테이블

-- 1. 월별 정산 정보 테이블 (monthly_settlement)
CREATE TABLE IF NOT EXISTS monthly_settlement (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '기본키',
    store_id INT NOT NULL COMMENT '매장 ID',
    settlement_year INT NOT NULL COMMENT '정산 년도 (예: 2024)',
    settlement_month INT NOT NULL COMMENT '정산 월 (1~12)',
    total_order_count INT DEFAULT 0 COMMENT '주문 건수',
    total_amount DECIMAL(15, 2) DEFAULT 0 COMMENT '총 주문 금액',
    total_commission DECIMAL(15, 2) DEFAULT 0 COMMENT '총 수수료',
    settlement_amount DECIMAL(15, 2) DEFAULT 0 COMMENT '정산 금액 (주문금액 - 수수료)',
    status ENUM('PENDING', 'CALCULATED', 'CONFIRMED', 'PAID', 'CANCELLED') DEFAULT 'PENDING' COMMENT '정산 상태',
    settlement_date DATE COMMENT '정산 확정 일자',
    payment_date DATE COMMENT '지급 일자',
    tax_invoice_issued BOOLEAN DEFAULT FALSE COMMENT '세금계산서 발행 여부',
    tax_invoice_issued_date DATE COMMENT '세금계산서 발행 일자',
    memo TEXT COMMENT '메모',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '생성일시',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일시',
    UNIQUE KEY uk_store_year_month (store_id, settlement_year, settlement_month),
    INDEX idx_store_id (store_id),
    INDEX idx_settlement_date (settlement_date),
    INDEX idx_status (status),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='월별 정산 정보 테이블';

-- 2. 주문건별 정산 정보 테이블 (order_settlement)
CREATE TABLE IF NOT EXISTS order_settlement (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '기본키',
    order_id INT NOT NULL COMMENT '주문 ID',
    monthly_settlement_id INT COMMENT '월별 정산 ID (NULL 가능, 월별 정산에 포함될 때)',
    store_id INT NOT NULL COMMENT '매장 ID',
    order_amount DECIMAL(15, 2) NOT NULL COMMENT '주문 금액',
    commission_rate DECIMAL(5, 2) DEFAULT 0 COMMENT '수수료율 (%)',
    commission_amount DECIMAL(15, 2) DEFAULT 0 COMMENT '수수료 금액',
    settlement_amount DECIMAL(15, 2) NOT NULL COMMENT '정산 금액 (주문금액 - 수수료)',
    order_date DATETIME NOT NULL COMMENT '주문 일시',
    gifticon_used_date DATETIME COMMENT '기프티콘 사용 일시',
    status ENUM('PENDING', 'COMPLETED', 'FAILED') DEFAULT 'PENDING' COMMENT '정산 상태',
    -- PENDING: 정산 대기, COMPLETED: 정산 완료, FAILED: 정산 실패
    memo TEXT COMMENT '메모',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '생성일시',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일시',
    UNIQUE KEY uk_order_id (order_id),
    INDEX idx_monthly_settlement_id (monthly_settlement_id),
    INDEX idx_store_id (store_id),
    INDEX idx_order_date (order_date),
    INDEX idx_status (status),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='주문건별 정산 정보 테이블';

-- 3. orders 테이블에 order_settlement_id 컬럼 추가 (아직 없을 경우)
-- ALTER TABLE orders ADD COLUMN order_settlement_id INT COMMENT '주문 정산 ID' AFTER id;
-- ALTER TABLE orders ADD INDEX idx_order_settlement_id (order_settlement_id);

-- 4. 외래키 제약조건 추가 (필요시)
-- ALTER TABLE order_settlement 
-- ADD CONSTRAINT fk_order_settlement_order 
-- FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE ON UPDATE CASCADE;

-- ALTER TABLE order_settlement 
-- ADD CONSTRAINT fk_order_settlement_monthly 
-- FOREIGN KEY (monthly_settlement_id) REFERENCES monthly_settlement(id) ON DELETE SET NULL ON UPDATE CASCADE;

-- ALTER TABLE order_settlement 
-- ADD CONSTRAINT fk_order_settlement_store 
-- FOREIGN KEY (store_id) REFERENCES store(id) ON DELETE CASCADE ON UPDATE CASCADE;

-- ALTER TABLE monthly_settlement 
-- ADD CONSTRAINT fk_monthly_settlement_store 
-- FOREIGN KEY (store_id) REFERENCES store(id) ON DELETE CASCADE ON UPDATE CASCADE;

-- 5. 기존 테이블에 세금계산서 발행 여부 컬럼 추가 (이미 테이블이 생성된 경우)
-- ALTER TABLE monthly_settlement 
-- ADD COLUMN tax_invoice_issued BOOLEAN DEFAULT FALSE COMMENT '세금계산서 발행 여부' AFTER payment_date;
-- ALTER TABLE monthly_settlement 
-- ADD COLUMN tax_invoice_issued_date DATE COMMENT '세금계산서 발행 일자' AFTER tax_invoice_issued;

