ALTER TABLE app_versions
    ADD COLUMN app_type ENUM('user','owner') NOT NULL DEFAULT 'user' COMMENT '앱 종류' AFTER platform;

DROP INDEX idx_platform_created ON app_versions;
CREATE INDEX idx_platform_apptype_created ON app_versions (platform, app_type, created_at DESC);
