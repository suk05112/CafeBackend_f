-- 정산 생성 실패 시 사유 저장
ALTER TABLE settlement_cycles
    ADD COLUMN last_error TEXT NULL COMMENT '마지막 정산 생성 실패 사유' AFTER status,
    ADD COLUMN last_error_at DATETIME NULL COMMENT '마지막 실패 시각' AFTER last_error;
