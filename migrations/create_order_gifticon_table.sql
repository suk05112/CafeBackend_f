-- Order_Gifticon 테이블 생성
-- Order와 Gifticon을 연결하는 중간 테이블
-- 주문(Order)과 기프티콘(Gifticon)의 다대다 관계를 표현

CREATE TABLE IF NOT EXISTS orders_gifticon (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '기본키',
    user_id INT NOT NULL COMMENT '사용자 ID',
    order_id INT NOT NULL COMMENT '주문 ID',
    menu_id INT NOT NULL COMMENT '메뉴 ID',
    gifticon_id INT NOT NULL COMMENT '기프티콘 ID',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '생성일시',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일시',
    CONSTRAINT fk_order_gifticon_user FOREIGN KEY (user_id) REFERENCES `user`(`id`) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_order_gifticon_order FOREIGN KEY (order_id) REFERENCES `orders`(`id`) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_order_gifticon_menu FOREIGN KEY (menu_id) REFERENCES `Menu`(`menuId`) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_order_gifticon_gifticon FOREIGN KEY (gifticon_id) REFERENCES `Gifticon`(`id`) ON DELETE CASCADE ON UPDATE CASCADE,
    UNIQUE KEY uk_order_gifticon (order_id, gifticon_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='주문-기프티콘 연결 테이블';

-- 인덱스 추가 (조회 성능 향상)
CREATE INDEX idx_user_id ON orders_gifticon(user_id);
CREATE INDEX idx_order_id ON orders_gifticon(order_id);
CREATE INDEX idx_menu_id ON orders_gifticon(menu_id);
CREATE INDEX idx_gifticon_id ON orders_gifticon(gifticon_id);
CREATE INDEX idx_user_gifticon ON orders_gifticon(user_id, gifticon_id);
