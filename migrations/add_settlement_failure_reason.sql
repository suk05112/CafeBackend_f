-- 정산 실패 시 매장별 실패 사유 저장
ALTER TABLE settlement
    ADD COLUMN failure_reason VARCHAR(500) NULL COMMENT '정산 실패 사유' AFTER account_number;

-- status에 FAILED 추가 (정산 생성 실패한 매장용)
ALTER TABLE settlement
    MODIFY COLUMN status ENUM('READY', 'PENDING', 'COMPLETED', 'HOLD', 'FAILED') DEFAULT 'READY' COMMENT '정산 상태';
