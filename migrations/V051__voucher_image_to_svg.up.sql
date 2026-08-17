-- GNB-245: 금액권 이미지를 PNG에서 SVG(벡터 원본)로 전환
-- 발행된 금액권 기프티콘이 없어 gifticon.image_key_snapshot 백필은 불필요하며,
-- 전환 이후 발행분부터 구매 시점 스냅샷에 .svg가 저장된다.

UPDATE menu
SET image_key = REPLACE(image_key, '.png', '.svg')
WHERE product_type = 'VOUCHER'
  AND image_key LIKE 'voucher/%.png';
