-- GNB-80: 정산 주기 데이터 생성 (일~토 7일 주기, 2026-06-01 ~ 2027-12-27)
-- payout_date: 주기 종료일(토요일) 기준 3주 후 화요일

INSERT INTO settlement_cycles (period_start_date, period_end_date, payout_date, status)
SELECT period_start, period_end, payout_date, 'OPEN'
FROM (
    WITH RECURSIVE weeks AS (
        SELECT
            -- 2026-05-31이 일요일, 6/1 포함 주부터 시작
            DATE('2026-06-01') - INTERVAL (DAYOFWEEK(DATE('2026-06-01')) - 1) DAY AS period_start
        UNION ALL
        SELECT period_start + INTERVAL 7 DAY
        FROM weeks
        WHERE period_start + INTERVAL 7 DAY <= DATE('2027-12-25')
    )
    SELECT
        period_start,
        period_start + INTERVAL 6 DAY AS period_end,
        -- 종료일(토) + 21일 = 3주 후, 그 주의 화요일 (DAYOFWEEK: 1=일,2=월,3=화)
        (period_start + INTERVAL 6 DAY + INTERVAL 21 DAY)
            + INTERVAL ((3 - DAYOFWEEK(period_start + INTERVAL 6 DAY + INTERVAL 21 DAY) + 7) % 7) DAY AS payout_date
    FROM weeks
) AS cycles
WHERE NOT EXISTS (
    SELECT 1 FROM settlement_cycles sc
    WHERE sc.period_start_date = cycles.period_start
      AND sc.period_end_date = cycles.period_end
);
