-- GNB-80 rollback: 생성된 정산 주기 데이터 삭제 (settlement가 연결되지 않은 OPEN 주기만)
DELETE FROM settlement_cycles
WHERE status = 'OPEN'
  AND period_start_date >= '2026-06-01'
  AND NOT EXISTS (
      SELECT 1 FROM settlement s WHERE s.cycle_id = settlement_cycles.cycle_id
  );
