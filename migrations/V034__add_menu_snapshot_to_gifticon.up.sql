-- 기프티콘 발급 시점의 메뉴 이름/가격/설명/이미지를 스냅샷으로 저장 (메뉴 수정/삭제와 무관하게 구매 당시 정보 보존)
ALTER TABLE gifticon
    ADD COLUMN menu_name_snapshot VARCHAR(255) NULL COMMENT '발급 시점 메뉴 이름 스냅샷',
    ADD COLUMN price_snapshot INT NULL COMMENT '발급 시점 메뉴 가격 스냅샷',
    ADD COLUMN description_snapshot TEXT NULL COMMENT '발급 시점 메뉴 설명 스냅샷',
    ADD COLUMN image_key_snapshot VARCHAR(255) NULL COMMENT '발급 시점 메뉴 이미지 키 스냅샷';
