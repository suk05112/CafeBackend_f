-- GNB-220: 정산 중복 생성 방지 (동일 매장·주기 중복 병합 + 재발 방지 제약)
-- 참고: status ENUM은 dev DB 확인 결과 이미 'FAILED'를 포함하고 있어 별도 변경 불필요.

-- 1. 기존 중복 레코드 병합: (store_id, cycle_id)별 가장 먼저 생성된(settlement_id 최소) 1건만 남기고
--    나머지(중복분)의 settlement_details를 남길 레코드로 재연결한 뒤 중복 레코드를 삭제.
--    금액 재계산까지 완료해야 정산 내역이 정확해지므로, keep 레코드의 합계도 details 기준으로 다시 계산한다.

-- 1-1. 중복 대상 매핑 테이블 생성 (keep_id = 남길 settlement_id, dup_id = 병합 후 삭제할 settlement_id)
CREATE TEMPORARY TABLE settlement_dedup_map AS
SELECT s.settlement_id AS dup_id, keep.keep_id AS keep_id
FROM settlement s
INNER JOIN (
    SELECT store_id, cycle_id, MIN(settlement_id) AS keep_id
    FROM settlement
    WHERE cycle_id IS NOT NULL
    GROUP BY store_id, cycle_id
    HAVING COUNT(*) > 1
) keep ON s.store_id = keep.store_id
      AND s.cycle_id = (SELECT cycle_id FROM settlement WHERE settlement_id = keep.keep_id)
WHERE s.settlement_id != keep.keep_id
  AND s.cycle_id = (SELECT cycle_id FROM settlement WHERE settlement_id = keep.keep_id);

-- 1-2. 중복 레코드에 연결된 settlement_details를 keep 레코드로 재연결
UPDATE settlement_details sd
INNER JOIN settlement_dedup_map m ON sd.settlement_id = m.dup_id
SET sd.settlement_id = m.keep_id;

-- 1-3. keep 레코드의 합계를 details 기준으로 재계산 (기본 수수료 합산 방식은 crud/stats.py의 생성 로직과 동일)
UPDATE settlement s
INNER JOIN (
    SELECT
        sd.settlement_id,
        SUM(sd.sales_amount) AS total_sales,
        SUM(sd.fee_supply) AS total_fee_supply,
        SUM(sd.fee_vat) AS total_fee_vat,
        SUM(sd.fee_amount) AS total_fee_amount
    FROM settlement_details sd
    WHERE sd.settlement_id IN (SELECT DISTINCT keep_id FROM settlement_dedup_map)
    GROUP BY sd.settlement_id
) agg ON s.settlement_id = agg.settlement_id
SET
    s.total_sales_amount = agg.total_sales,
    s.original_fee_supply = agg.total_fee_supply,
    s.original_fee_vat = agg.total_fee_vat,
    s.original_fee_amount = agg.total_fee_amount,
    -- 프로모션 미적용(applied_promo_id IS NULL) 건은 total_fee_amount/net_payout도 원본 수수료 기준으로 재계산.
    -- 프로모션 적용 건은 promo_fee_amount가 이미 총액 기준으로 저장되어 있어 재계산 대상에서 제외(수동 확인 필요).
    s.total_fee_amount = IF(s.applied_promo_id IS NULL, agg.total_fee_amount, s.total_fee_amount),
    s.net_payout_amount = IF(s.applied_promo_id IS NULL, agg.total_sales - agg.total_fee_amount, s.net_payout_amount)
WHERE s.applied_promo_id IS NULL;

-- 1-4. 병합 완료된 중복 레코드 삭제
DELETE s FROM settlement s
INNER JOIN settlement_dedup_map m ON s.settlement_id = m.dup_id;

DROP TEMPORARY TABLE settlement_dedup_map;

-- 2. 재발 방지: 매장×주기 조합 유일 제약 (cycle_id NULL 인 레코드는 제약 대상 제외됨 - MySQL UNIQUE는 NULL 다중 허용)
ALTER TABLE settlement
    ADD UNIQUE KEY uk_store_cycle (store_id, cycle_id);
