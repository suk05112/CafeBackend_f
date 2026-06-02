ALTER TABLE orders
    ADD COLUMN idempotency_key VARCHAR(100) NULL UNIQUE
    COMMENT '앱에서 생성한 UUID. 동일 키 재요청 시 기존 주문 반환 (이중 결제 방지)';

INSERT INTO migration_history (version, filename, applied_at, status)
VALUES ('012', 'V012__add_idempotency_key_to_orders.up.sql', NOW(), 'applied');
