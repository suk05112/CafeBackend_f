-- GNB-195: 구매자 100% 환불 마감일을 발급 시점 정책으로 gifticon에 고정 저장
ALTER TABLE gifticon
    ADD COLUMN refund_deadline DATE NULL COMMENT '구매자 100% 환불 마감일(이 날짜까지 구매자 환불 가능, NULL=환불정책없음). 발급 시점 정책값으로 고정 저장' AFTER validity;

UPDATE gifticon SET refund_deadline = DATE(DATE_ADD(created_at, INTERVAL 60 DAY)) WHERE refund_deadline IS NULL;
