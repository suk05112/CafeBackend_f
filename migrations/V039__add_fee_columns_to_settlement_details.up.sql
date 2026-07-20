-- GNB-198: settlement_details에 건별 기본(프로모션 미적용) 수수료/부가세 저장
-- settlement.original_fee_*는 이 컬럼들의 합계로부터 산출하여 정합성을 보장한다.
ALTER TABLE settlement_details
    ADD COLUMN fee_rate DECIMAL(5,2) NULL COMMENT '적용된 기본 수수료율 (구매 시점, %)',
    ADD COLUMN fee_supply INT NULL COMMENT '기본 수수료 공급가',
    ADD COLUMN fee_vat INT NULL COMMENT '기본 수수료 부가세',
    ADD COLUMN fee_amount INT NULL COMMENT '기본 수수료 합계 (supply + vat)',
    ADD COLUMN settlement_amount INT NULL COMMENT '기본 수수료 기준 실지급액 (sales_amount - fee_amount)';
