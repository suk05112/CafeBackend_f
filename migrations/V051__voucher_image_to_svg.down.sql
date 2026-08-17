-- GNB-245 롤백: 금액권 이미지를 PNG로 되돌림

UPDATE menu
SET image_key = REPLACE(image_key, '.svg', '.png')
WHERE product_type = 'VOUCHER'
  AND image_key LIKE 'voucher/%.svg';
