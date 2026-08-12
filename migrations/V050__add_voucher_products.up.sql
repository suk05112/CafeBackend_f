-- GNB-236: 금액권(교환권) 상품 도입
-- 금액권은 전용 가상매장(store id=1)의 menu 레코드로 관리한다.
-- 검수/계약 미완료 상태이므로 기존 매장 목록·메뉴 추천 쿼리에서 자동으로 제외된다.

INSERT INTO store (id, store_name, store_description, inspection_status, contract_completed)
VALUES (1, '기프넛 금액권', '금액권 전용 가상 매장', 'PENDING', 'NONE');

ALTER TABLE menu
    ADD COLUMN product_type ENUM('MENU','VOUCHER') NOT NULL DEFAULT 'MENU' COMMENT '상품 유형 (MENU=매장 메뉴, VOUCHER=금액권)';

-- product_type: 발행 시점 스냅샷 (메뉴가 변경되어도 발행 당시 유형 보존)
-- used_store_id: 금액권은 사용 시점에 사용처가 결정되므로 정산 귀속을 위해 기록
ALTER TABLE gifticon
    ADD COLUMN product_type ENUM('MENU','VOUCHER') NOT NULL DEFAULT 'MENU' COMMENT '발행 시점 상품 유형 스냅샷',
    ADD COLUMN used_store_id BIGINT NULL COMMENT '금액권 사용 매장 (정산 귀속)';

CREATE INDEX idx_gifticon_used_store_id ON gifticon(used_store_id);

INSERT INTO menu (store_id, menu_name, price, product_type, status, image_key) VALUES
    (1, '기프넛 5,000원 교환권',   5000, 'VOUCHER', 'ACTIVE', 'voucher/voucher_5000.png'),
    (1, '기프넛 10,000원 교환권', 10000, 'VOUCHER', 'ACTIVE', 'voucher/voucher_10000.png'),
    (1, '기프넛 20,000원 교환권', 20000, 'VOUCHER', 'ACTIVE', 'voucher/voucher_20000.png'),
    (1, '기프넛 30,000원 교환권', 30000, 'VOUCHER', 'ACTIVE', 'voucher/voucher_30000.png'),
    (1, '기프넛 40,000원 교환권', 40000, 'VOUCHER', 'ACTIVE', 'voucher/voucher_40000.png'),
    (1, '기프넛 45,000원 교환권', 45000, 'VOUCHER', 'ACTIVE', 'voucher/voucher_45000.png');
