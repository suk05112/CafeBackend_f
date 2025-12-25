-- inquiry 테이블 생성 (유저 문의)
-- 유저가 문의를 등록하는 테이블

CREATE TABLE IF NOT EXISTS inquiry (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '기본키',
    user_id INT NOT NULL COMMENT '사용자 ID',
    title VARCHAR(255) NOT NULL COMMENT '문의 제목',
    content TEXT NOT NULL COMMENT '문의 내용',
    status VARCHAR(20) DEFAULT 'pending' COMMENT '문의 상태 (pending, answered)',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '생성일시',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일시',
    INDEX idx_user_id (user_id),
    INDEX idx_status (status),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='유저 문의 테이블';

-- inquiry_response 테이블 생성 (유저 문의 답변)
-- 관리자가 문의에 답변하는 테이블

CREATE TABLE IF NOT EXISTS inquiry_response (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '기본키',
    inquiry_id INT NOT NULL COMMENT '문의 ID',
    response TEXT NOT NULL COMMENT '답변 내용',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '생성일시',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일시',
    UNIQUE KEY uk_inquiry_id (inquiry_id),
    INDEX idx_inquiry_id (inquiry_id),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='유저 문의 답변 테이블';

-- owner_inquiry 테이블 생성 (사장님 문의)
-- 사장님이 문의를 등록하는 테이블

CREATE TABLE IF NOT EXISTS owner_inquiry (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '기본키',
    owner_id INT NOT NULL COMMENT '사장님 ID',
    title VARCHAR(255) NOT NULL COMMENT '문의 제목',
    content TEXT NOT NULL COMMENT '문의 내용',
    status VARCHAR(20) DEFAULT 'pending' COMMENT '문의 상태 (pending, answered)',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '생성일시',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일시',
    INDEX idx_owner_id (owner_id),
    INDEX idx_status (status),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='사장님 문의 테이블';

-- owner_inquiry_response 테이블 생성 (사장님 문의 답변)
-- 관리자가 사장님 문의에 답변하는 테이블

CREATE TABLE IF NOT EXISTS owner_inquiry_response (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '기본키',
    inquiry_id INT NOT NULL COMMENT '문의 ID',
    response TEXT NOT NULL COMMENT '답변 내용',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '생성일시',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일시',
    UNIQUE KEY uk_inquiry_id (inquiry_id),
    INDEX idx_inquiry_id (inquiry_id),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='사장님 문의 답변 테이블';

-- ============================================
-- 외래키 제약조건 추가 (테이블 생성 후 별도로 추가)
-- ============================================
-- 아래 쿼리를 실행하기 전에 다음을 확인하세요:
-- 1. 참조하는 테이블이 존재하는지
-- 2. 참조하는 컬럼의 데이터 타입이 일치하는지 (INT)
-- 3. 참조하는 컬럼이 PRIMARY KEY나 UNIQUE 인덱스가 있는지
--
-- 확인 쿼리:
-- SHOW TABLES;
-- DESCRIBE `user`;
-- DESCRIBE `owner`;
-- DESCRIBE inquiry;
-- DESCRIBE owner_inquiry;

-- inquiry 테이블 외래키 추가
-- ALTER TABLE inquiry 
-- ADD CONSTRAINT fk_inquiry_user 
-- FOREIGN KEY (user_id) 
-- REFERENCES `user`(`id`) 
-- ON DELETE CASCADE ON UPDATE CASCADE;

-- inquiry_response 테이블 외래키 추가
-- ALTER TABLE inquiry_response 
-- ADD CONSTRAINT fk_inquiry_response_inquiry 
-- FOREIGN KEY (inquiry_id) 
-- REFERENCES inquiry(id) 
-- ON DELETE CASCADE ON UPDATE CASCADE;

-- owner_inquiry 테이블 외래키 추가
-- ALTER TABLE owner_inquiry 
-- ADD CONSTRAINT fk_owner_inquiry_owner 
-- FOREIGN KEY (owner_id) 
-- REFERENCES `owner`(`id`) 
-- ON DELETE CASCADE ON UPDATE CASCADE;

-- owner_inquiry_response 테이블 외래키 추가
-- ALTER TABLE owner_inquiry_response 
-- ADD CONSTRAINT fk_owner_inquiry_response_inquiry 
-- FOREIGN KEY (inquiry_id) 
-- REFERENCES owner_inquiry(id) 
-- ON DELETE CASCADE ON UPDATE CASCADE;
