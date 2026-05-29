-- V008 rollback: image_key DB 저장 방식 되돌리기

-- 1. store_images 테이블 삭제
DROP TABLE IF EXISTS `store_images`;

-- 2. menu 테이블에서 image_key 컬럼 제거
ALTER TABLE `menu`
    DROP COLUMN `image_key`;

-- 3. store 테이블에 store_photo_cnt 컬럼 복구
ALTER TABLE `store`
    ADD COLUMN `store_photo_cnt` int(11) DEFAULT 0;
