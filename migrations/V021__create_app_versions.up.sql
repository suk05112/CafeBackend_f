CREATE TABLE app_versions (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    platform        ENUM('ios', 'android') NOT NULL COMMENT '플랫폼',
    version         VARCHAR(20) NOT NULL COMMENT '버전 (예: 1.0.1)',
    is_force_update TINYINT(1) NOT NULL DEFAULT 0 COMMENT '강제업데이트 여부',
    memo            TEXT NULL COMMENT '변경사항 메모',
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '등록일시',
    INDEX idx_platform_created (platform, created_at DESC)
);
