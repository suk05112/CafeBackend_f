-- orders.status: default UNKNOWN → PENDING, 각 값 COMMENT 추가
ALTER TABLE orders
    MODIFY COLUMN status ENUM(
        'PENDING',    -- 결제 URL 발급 완료, 사용자 결제 대기 중
        'COMPLETED',  -- 결제 성공
        'EXPIRED',    -- 결제 없이 15분 초과 자동 만료
        'REFUNDED',   -- 환불 완료
        'UNKNOWN'     -- 비정상 (레거시, 신규 발생 불가)
    ) NOT NULL DEFAULT 'PENDING'
    COMMENT '주문 상태. PENDING=결제대기, COMPLETED=결제성공, EXPIRED=자동만료, REFUNDED=환불완료';

-- gifticon.status: UNKNOWN 제거, REFUNDED 추가, default PENDING, COMMENT 추가
ALTER TABLE gifticon
    MODIFY COLUMN status ENUM(
        'PENDING',   -- 결제 대기 중 (결제 미완료 포함)
        'UNUSED',    -- 결제 완료, 미사용
        'USED',      -- 사용 완료
        'EXPIRED',   -- 유효기간(1년) 초과, 환불 대기 중
        'REFUNDED',  -- 유효기간 만료로 90% 환불 완료
        'CANCELED'   -- 구매 취소 (7일 내 환불)
    ) NOT NULL DEFAULT 'PENDING'
    COMMENT '기프티콘 상태. PENDING=결제대기, UNUSED=미사용, USED=사용완료, EXPIRED=유효기간만료, REFUNDED=만료환불완료, CANCELED=구매취소';

INSERT INTO migration_history (version, filename, applied_at, status)
VALUES ('010', 'V010__fix_order_gifticon_status.up.sql', NOW(), 'applied');
