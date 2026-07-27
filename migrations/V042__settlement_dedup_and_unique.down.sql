-- GNB-220: 정산 중복 생성 방지 롤백
-- 주의: 삭제된 중복 레코드는 복원되지 않음

ALTER TABLE settlement
    DROP KEY uk_store_cycle;

ALTER TABLE settlement
    MODIFY COLUMN status ENUM('READY', 'PENDING', 'COMPLETED', 'HOLD') DEFAULT 'READY' COMMENT '정산 상태';
