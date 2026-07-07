CREATE TABLE mok_client_tx (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    client_tx_id VARCHAR(40) NOT NULL,
    used TINYINT(1) NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_client_tx_id (client_tx_id),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='드림시큐리티 본인확인 거래ID 재사용 방지';

ALTER TABLE user ADD COLUMN birthdate VARCHAR(8) NULL COMMENT '생년월일(YYYYMMDD)' AFTER phone;
ALTER TABLE owner ADD COLUMN birthdate VARCHAR(8) NULL COMMENT '생년월일(YYYYMMDD)' AFTER phone;
