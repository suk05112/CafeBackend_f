-- GNB-195: 컬럼명을 더 직관적인 이름으로 변경 (구매자 100% 환불 마감일임을 명시)
ALTER TABLE gifticon
    CHANGE COLUMN refund_deadline purchaser_refund_deadline DATE NULL COMMENT '구매자 100% 환불 마감일(이 날짜까지 구매자 환불 가능, NULL=환불정책없음). 발급 시점 정책값으로 고정 저장';
