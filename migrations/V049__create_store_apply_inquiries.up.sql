CREATE TABLE store_apply_inquiries (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    store_name VARCHAR(100) NOT NULL COMMENT '매장명',
    applicant_name VARCHAR(50) NOT NULL COMMENT '신청자 성함',
    email VARCHAR(255) NULL COMMENT '이메일 (선택)',
    phone VARCHAR(20) NOT NULL COMMENT '연락처',
    region VARCHAR(100) NOT NULL COMMENT '주소(시/구 단위)',
    message TEXT NOT NULL COMMENT '문의 내용',
    privacy_agreed BOOLEAN NOT NULL DEFAULT FALSE COMMENT '개인정보 수집·이용 동의 여부',
    status VARCHAR(20) NOT NULL DEFAULT 'pending' COMMENT '처리 상태 (pending, contacted)',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_created_at (created_at)
) COMMENT='hello-gifnut 매장 입점 문의';
