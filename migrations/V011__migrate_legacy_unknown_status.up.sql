-- 1. 15분 초과 PENDING orders → EXPIRED (결제 미완료로 만료)
UPDATE orders
SET status = 'EXPIRED'
WHERE status = 'PENDING'
  AND created_at < NOW() - INTERVAL 15 MINUTE;

-- 2. EXPIRED orders에 연결된 gifticon UNKNOWN → PENDING (결제 미완료)
UPDATE gifticon
SET status = 'PENDING'
WHERE status = 'UNKNOWN'
  AND order_id IN (
      SELECT id FROM orders WHERE status = 'EXPIRED'
  );

-- 3. COMPLETED orders에 연결된 gifticon UNKNOWN → UNUSED (결제 완료, 미사용)
UPDATE gifticon
SET status = 'UNUSED'
WHERE status = 'UNKNOWN'
  AND order_id IN (
      SELECT id FROM orders WHERE status = 'COMPLETED'
  );

-- 4. 그 외 남은 UNKNOWN → PENDING (안전한 기본값)
UPDATE gifticon
SET status = 'PENDING'
WHERE status = 'UNKNOWN';

INSERT INTO migration_history (version, filename, applied_at, status)
VALUES ('011', 'V011__migrate_legacy_unknown_status.up.sql', NOW(), 'applied');
