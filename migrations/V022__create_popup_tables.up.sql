CREATE TABLE popup (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    target_type   ENUM('user', 'owner') NOT NULL COMMENT '노출 대상',
    title         VARCHAR(255) NOT NULL COMMENT '팝업 제목',
    image_url     TEXT NOT NULL COMMENT 'S3 이미지 URL',
    link_url      TEXT NULL COMMENT '클릭 시 이동 URL (선택)',
    display_order INT NOT NULL DEFAULT 0 COMMENT '노출 순서',
    is_active     TINYINT(1) NOT NULL DEFAULT 1 COMMENT '노출 유무',
    start_at      DATETIME NULL COMMENT '노출 시작일 (NULL=즉시)',
    end_at        DATETIME NULL COMMENT '노출 종료일 (NULL=무제한)',
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_target_active_order (target_type, is_active, display_order)
);

CREATE TABLE popup_views (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    viewer_type  ENUM('user', 'owner') NOT NULL COMMENT '뷰어 유형',
    viewer_id    INT NOT NULL COMMENT '유저 또는 사장님 ID',
    hidden_until DATETIME NOT NULL COMMENT '이 시각 이전엔 팝업 숨김',
    UNIQUE KEY uq_viewer (viewer_type, viewer_id)
);
