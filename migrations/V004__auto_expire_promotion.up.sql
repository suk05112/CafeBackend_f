-- GNB-57: 만료 프로모션 자동 비활성화 (MySQL Event Scheduler)
--
-- ⚠️  운영 배포 시 추가 작업 필요:
--     my.cnf [mysqld] 섹션에 아래 항목 추가 후 MySQL 재시작
--     event_scheduler=ON
--     (SET GLOBAL은 재시작 시 리셋되므로 영구 적용 안됨)

SET GLOBAL event_scheduler = ON;

CREATE EVENT IF NOT EXISTS evt_expire_fee_promotions
ON SCHEDULE EVERY 1 DAY
STARTS (CURDATE() + INTERVAL 1 DAY)
DO
    UPDATE fee_promotions
    SET is_active = FALSE
    WHERE end_date < CURDATE()
      AND is_active = TRUE;
