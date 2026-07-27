-- GNB-220: 정산 중복 생성 방지 (동일 매장·주기 중복 skip + 재발 방지 제약)

-- 1. status ENUM에 FAILED 추가 (crud/stats.py, crud/settlement.py에서 이미 사용 중이나 원본 스키마에는 누락되어 있었음)
ALTER TABLE settlement
    MODIFY COLUMN status ENUM('READY', 'PENDING', 'COMPLETED', 'HOLD', 'FAILED') DEFAULT 'READY' COMMENT '정산 상태';

-- 2. 기존 중복 레코드 정리: (store_id, cycle_id)별 가장 최신(settlement_id 최대) 1건만 남기고 삭제
--    settlement_details가 연결된 행은 삭제 대상에서 제외 (정상 정산 완료 건 보호)
DELETE s FROM settlement s
INNER JOIN (
    SELECT store_id, cycle_id, MAX(settlement_id) AS keep_id
    FROM settlement
    WHERE cycle_id IS NOT NULL
    GROUP BY store_id, cycle_id
) keep ON s.store_id = keep.store_id AND s.cycle_id = keep.cycle_id
WHERE s.settlement_id != keep.keep_id
  AND NOT EXISTS (
      SELECT 1 FROM settlement_details sd WHERE sd.settlement_id = s.settlement_id
  );

-- 3. 재발 방지: 매장×주기 조합 유일 제약 (cycle_id NULL 인 레코드는 제약 대상 제외됨 - MySQL UNIQUE는 NULL 다중 허용)
ALTER TABLE settlement
    ADD UNIQUE KEY uk_store_cycle (store_id, cycle_id);
