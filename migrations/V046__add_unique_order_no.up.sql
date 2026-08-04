-- GNB-234: order_no 중복 생성 방지를 위한 UNIQUE 제약 추가
ALTER TABLE orders ADD UNIQUE INDEX uk_order_no (order_no);
