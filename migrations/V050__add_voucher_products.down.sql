-- GNB-236 롤백: 금액권(교환권) 상품 제거

DELETE FROM menu WHERE store_id = 1 AND product_type = 'VOUCHER';

DROP INDEX idx_gifticon_used_store_id ON gifticon;

ALTER TABLE gifticon
    DROP COLUMN product_type,
    DROP COLUMN used_store_id;

ALTER TABLE menu
    DROP COLUMN product_type;

DELETE FROM store WHERE id = 1;
