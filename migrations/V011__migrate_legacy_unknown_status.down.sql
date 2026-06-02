-- 데이터 롤백은 원복 불가 (UNKNOWN → PENDING/UNUSED 변환은 비가역적)
-- 필요 시 백업 데이터로 복구할 것

UPDATE migration_history SET rolled_back_at = NOW(), status = 'rolled_back'
WHERE version = '011' AND filename = 'V011__migrate_legacy_unknown_status.up.sql';
