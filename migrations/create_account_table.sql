-- account 테이블 생성 (계좌 정보)
-- 매장의 정산 계좌 정보를 저장하는 테이블

CREATE TABLE IF NOT EXISTS account (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '기본키',
    store_id INT NOT NULL COMMENT '매장 ID',
    name VARCHAR(255) NOT NULL COMMENT '예금주명',
    code VARCHAR(50) NOT NULL COMMENT '은행 코드',
    bank VARCHAR(100) NOT NULL COMMENT '은행명',
    account VARCHAR(100) NOT NULL COMMENT '계좌번호',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '생성일시',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일시',
    INDEX idx_store_id (store_id),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='계좌 정보 테이블';

