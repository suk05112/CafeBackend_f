ALTER TABLE fee_promotions
    ADD COLUMN title VARCHAR(100) NOT NULL DEFAULT '' COMMENT '프로모션 제목' AFTER promo_id;
