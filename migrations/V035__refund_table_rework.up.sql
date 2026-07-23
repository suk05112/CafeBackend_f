-- GNB-195: refund.status ENUM화, amount -> refunded_amount 컬럼명 변경, original_amount/fee_amount 추가
ALTER TABLE refund
    MODIFY COLUMN status ENUM('REQUESTED', 'PROCESSING', 'COMPLETED', 'FAILED')
        NOT NULL DEFAULT 'REQUESTED'
        COMMENT 'REQUESTED=신청접수(수동처리대기), PROCESSING=자동환불진행중, COMPLETED=완료, FAILED=실패',
    CHANGE COLUMN amount refunded_amount INT NOT NULL DEFAULT 0 COMMENT '실제 환불된 금액',
    ADD COLUMN original_amount INT NOT NULL DEFAULT 0 COMMENT '원결제금액(스냅샷)' AFTER refund_type,
    ADD COLUMN fee_amount INT NOT NULL DEFAULT 0 COMMENT '원금 대비 차감액' AFTER refunded_amount;

UPDATE refund SET original_amount = refunded_amount WHERE original_amount = 0;
