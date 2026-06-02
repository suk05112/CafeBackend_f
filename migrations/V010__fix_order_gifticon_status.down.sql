-- orders.status: PENDING default, UNKNOWN 복원
ALTER TABLE orders
    MODIFY COLUMN status ENUM(
        'PENDING',
        'COMPLETED',
        'EXPIRED',
        'REFUNDED',
        'UNKNOWN'
    ) NOT NULL DEFAULT 'UNKNOWN';

-- gifticon.status: UNKNOWN 복원, REFUNDED 제거, default UNKNOWN
ALTER TABLE gifticon
    MODIFY COLUMN status ENUM(
        'UNUSED',
        'USED',
        'EXPIRED',
        'CANCELED',
        'UNKNOWN'
    ) DEFAULT 'UNKNOWN';

UPDATE migration_history SET rolled_back_at = NOW(), status = 'rolled_back'
WHERE version = '010' AND filename = 'V010__fix_order_gifticon_status.up.sql';
