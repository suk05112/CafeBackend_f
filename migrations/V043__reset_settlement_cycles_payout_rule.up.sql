-- 정산 지급일 규칙 변경 (종료일+3주가 속한 주 화요일 -> 종료일+17일)에 따라
-- 기존 정산/정산주기 데이터를 전체 삭제하고 scripts/generate_settlement_cycles.py로 재생성한다.
DELETE FROM settlement_details;
DELETE FROM settlement;
DELETE FROM settlement_cycles;
ALTER TABLE settlement_details AUTO_INCREMENT = 1;
ALTER TABLE settlement AUTO_INCREMENT = 1;
ALTER TABLE settlement_cycles AUTO_INCREMENT = 1;
