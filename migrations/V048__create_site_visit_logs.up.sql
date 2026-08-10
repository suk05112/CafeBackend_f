CREATE TABLE site_visit_logs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    page VARCHAR(50) NOT NULL COMMENT '방문 페이지 식별자 (예: home, profile)',
    visitor_id VARCHAR(64) NOT NULL COMMENT '클라이언트에서 생성한 익명 방문자 식별자',
    visit_date DATE NOT NULL COMMENT '방문 날짜(KST 기준)',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_page_date_visitor (page, visit_date, visitor_id),
    INDEX idx_page_date (page, visit_date)
) COMMENT='hello-gifnut 페이지별 방문 로그(UV 집계용)';
