DROP INDEX idx_platform_apptype_created ON app_versions;
CREATE INDEX idx_platform_created ON app_versions (platform, created_at DESC);
ALTER TABLE app_versions DROP COLUMN app_type;
