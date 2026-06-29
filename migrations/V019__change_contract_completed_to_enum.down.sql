-- Step 1: 인덱스 제거
DROP INDEX IF EXISTS idx_store_list ON store;

-- Step 2: 임시 컬럼으로 현재 값 보존
ALTER TABLE store ADD COLUMN contract_completed_tmp ENUM('NONE', 'SENT', 'COMPLETED') NOT NULL DEFAULT 'NONE';
UPDATE store SET contract_completed_tmp = contract_completed;

-- Step 3: 컬럼 타입 복구
ALTER TABLE store MODIFY COLUMN contract_completed TINYINT(1) NOT NULL DEFAULT 0;

-- Step 4: 데이터 복구 (COMPLETED → 1, NONE/SENT → 0)
UPDATE store SET contract_completed = 1 WHERE contract_completed_tmp = 'COMPLETED';
UPDATE store SET contract_completed = 0 WHERE contract_completed_tmp IN ('NONE', 'SENT');

-- Step 5: 임시 컬럼 제거
ALTER TABLE store DROP COLUMN contract_completed_tmp;

-- Step 6: 인덱스 재생성 (원래 BOOLEAN 기준)
CREATE INDEX idx_store_list ON store (region_code, inspection_status, contract_completed, updated_at DESC, id DESC);
