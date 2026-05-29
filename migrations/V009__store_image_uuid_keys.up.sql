-- GNB-72: S3 이미지 키 UUID suffix 추가 - store_logo, bankbook, business_registration
-- 변경 사항:
--   store 테이블에 store_logo_key, bankbook_key, business_registration_key 컬럼 추가

ALTER TABLE `store`
    ADD COLUMN `store_logo_key` varchar(255) DEFAULT NULL COMMENT 'S3 store_logo 이미지 키 (uuid 포함)',
    ADD COLUMN `bankbook_key` varchar(255) DEFAULT NULL COMMENT 'S3 bankbook 이미지 키 (uuid 포함)',
    ADD COLUMN `business_registration_key` varchar(255) DEFAULT NULL COMMENT 'S3 business_registration 이미지 키 (uuid 포함)';
