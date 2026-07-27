-- GNB-195: 수신자 환불 신청 접수 시 사용 차단을 위한 상태값 추가
ALTER TABLE gifticon MODIFY COLUMN status ENUM(
    'PENDING', 'UNUSED', 'USED', 'EXPIRED', 'REFUNDED', 'CANCELED', 'REFUND_REQUESTED'
) NOT NULL DEFAULT 'PENDING'
COMMENT '기프티콘 상태. PENDING=결제대기, UNUSED=미사용, USED=사용완료, EXPIRED=유효기간만료, REFUNDED=만료환불완료, CANCELED=구매취소/수신자환불완료, REFUND_REQUESTED=수신자환불신청중';
