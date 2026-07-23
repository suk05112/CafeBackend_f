ALTER TABLE gifticon
    CHANGE COLUMN purchaser_refund_deadline refund_deadline DATE NULL COMMENT '구매자 100% 환불 마감일(이 날짜까지 구매자 환불 가능, NULL=환불정책없음). 발급 시점 정책값으로 고정 저장';
