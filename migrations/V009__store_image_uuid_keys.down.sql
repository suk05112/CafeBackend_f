-- V009 rollback: store_logo_key, bankbook_key, business_registration_key 컬럼 제거

ALTER TABLE `store`
    DROP COLUMN `store_logo_key`,
    DROP COLUMN `bankbook_key`,
    DROP COLUMN `business_registration_key`;
