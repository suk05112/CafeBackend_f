-- GNB-220: 정산 중복 생성 방지 롤백
-- 주의: 병합/삭제된 중복 레코드와 재계산된 합계는 복원되지 않음

ALTER TABLE settlement
    DROP KEY uk_store_cycle;
