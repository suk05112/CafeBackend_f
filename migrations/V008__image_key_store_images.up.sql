-- GNB-41: S3 이미지 캐시 문제 해결 - image_key DB 저장 방식으로 전환
-- 변경 사항:
--   1. menu 테이블: image_key 컬럼 추가
--   2. store_images 테이블 신규 생성 (store_photo_cnt 대체)
--   3. store 테이블: store_photo_cnt 컬럼 제거

-- 1. menu 테이블에 image_key 컬럼 추가
ALTER TABLE `menu`
    ADD COLUMN `image_key` varchar(255) DEFAULT NULL COMMENT 'S3 이미지 키 (uuid 포함)';

-- 2. store_images 테이블 신규 생성
CREATE TABLE `store_images` (
    `id` bigint(20) NOT NULL AUTO_INCREMENT,
    `store_id` bigint(20) NOT NULL COMMENT 'FK store.id',
    `image_key` varchar(255) NOT NULL COMMENT 'S3 이미지 키 (uuid 포함)',
    `order` int(11) NOT NULL DEFAULT 0 COMMENT '이미지 정렬 순서',
    `created_at` timestamp NULL DEFAULT current_timestamp(),
    PRIMARY KEY (`id`),
    KEY `idx_store_images_store_id` (`store_id`),
    CONSTRAINT `fk_store_images_store` FOREIGN KEY (`store_id`) REFERENCES `store` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='매장 이미지 테이블';

-- 3. store 테이블에서 store_photo_cnt 컬럼 제거
ALTER TABLE `store`
    DROP COLUMN `store_photo_cnt`;
