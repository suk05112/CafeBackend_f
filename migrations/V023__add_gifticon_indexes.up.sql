-- V023 up: gifticon 인덱스 추가 (created_at, status+used_at, store_id+used_at)
INSERT INTO migration_history (version, filename, applied_at, status)
VALUES ('V023', 'V023__add_gifticon_indexes.up.sql', NOW(), 'applied');

CREATE INDEX idx_gifticon_created_at ON gifticon (created_at);
CREATE INDEX idx_gifticon_status_used_at ON gifticon (status, used_at);
CREATE INDEX idx_gifticon_store_id_used_at ON gifticon (store_id, used_at);
