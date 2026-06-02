ALTER TABLE orders DROP COLUMN idempotency_key;

UPDATE migration_history SET rolled_back_at = NOW(), status = 'rolled_back'
WHERE version = '012' AND filename = 'V012__add_idempotency_key_to_orders.up.sql';
