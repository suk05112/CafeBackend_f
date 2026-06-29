-- Step 1: 기존 인덱스 제거 (V017에서 생성된 인덱스)
DROP INDEX IF EXISTS idx_store_list ON store;

-- Step 2: 임시 컬럼으로 기존 값 보존
ALTER TABLE store ADD COLUMN contract_completed_tmp TINYINT(1) NOT NULL DEFAULT 0;
UPDATE store SET contract_completed_tmp = CASE WHEN contract_completed = 1 THEN 1 ELSE 0 END;

-- Step 3: 기존 컬럼 제거 후 ENUM으로 재추가
ALTER TABLE store DROP COLUMN contract_completed;
ALTER TABLE store ADD COLUMN contract_completed ENUM('NONE', 'SENT', 'COMPLETED') NOT NULL DEFAULT 'NONE' AFTER contract_completed_tmp;

-- Step 4: 데이터 마이그레이션
UPDATE store SET contract_completed = 'COMPLETED' WHERE contract_completed_tmp = 1;
UPDATE store SET contract_completed = 'NONE' WHERE contract_completed_tmp = 0;

-- Step 5: 임시 컬럼 제거
ALTER TABLE store DROP COLUMN contract_completed_tmp;

-- Step 6: 인덱스 재생성
CREATE INDEX idx_store_list ON store (region_code, inspection_status, contract_completed, updated_at DESC, id DESC);
