-- V023 down: gifticon 인덱스 제거
DROP INDEX idx_gifticon_store_id_used_at ON gifticon;
DROP INDEX idx_gifticon_status_used_at ON gifticon;
DROP INDEX idx_gifticon_created_at ON gifticon;

UPDATE migration_history SET rolled_back_at = NOW(), status = 'rolled_back' WHERE version = 'V023' AND status = 'applied';
