-- platform_config 테이블 생성
-- 플랫폼 공통 설정 (기본 수수료 및 정산 주기)

CREATE TABLE IF NOT EXISTS platform_config (
    config_id INT PRIMARY KEY DEFAULT 1 COMMENT '설정 ID (단일 행)',
    base_fee_rate DECIMAL(5, 2) DEFAULT 3.00 COMMENT '전체 공통 수수료 (%)',
    settlement_days INT DEFAULT 5 COMMENT '정산 주기 (일 단위)',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '생성일시',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일시'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='플랫폼 공통 설정 테이블';

-- 초기 데이터 삽입
INSERT INTO platform_config (config_id, base_fee_rate, settlement_days)
VALUES (1, 3.00, 5)
ON DUPLICATE KEY UPDATE
    base_fee_rate = VALUES(base_fee_rate),
    settlement_days = VALUES(settlement_days);
