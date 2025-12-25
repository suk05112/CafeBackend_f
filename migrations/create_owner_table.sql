-- owner 테이블 생성 (사장님)
-- 카페 사장님 정보를 저장하는 테이블

CREATE TABLE IF NOT EXISTS owner (
    id BIGINT(20) AUTO_INCREMENT PRIMARY KEY COMMENT '기본키',
    name VARCHAR(255) NOT NULL COMMENT '이름',
    email VARCHAR(255) NOT NULL COMMENT '이메일',
    uid VARCHAR(255) NOT NULL COMMENT '로그인 UID',
    phone_number VARCHAR(20) NOT NULL COMMENT '전화번호',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '생성일시',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일시',
    UNIQUE KEY uk_uid (uid),
    UNIQUE KEY uk_email (email),
    INDEX idx_phone_number (phone_number),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='사장님 테이블';

