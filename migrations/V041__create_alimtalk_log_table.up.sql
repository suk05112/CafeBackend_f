-- GNB-217: 카카오 알림톡 발송을 큐 테이블 기반 배치 처리로 전환
CREATE TABLE alimtalk_log (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '알림톡 로그 ID',
    tpl_code VARCHAR(20) NOT NULL COMMENT '알리고 템플릿 코드 (예: UH_9771)',
    category VARCHAR(40) NOT NULL COMMENT '업무 목적 태그 (AUTO_REFUND_SENDER 등)',
    receiver_phone VARCHAR(20) NOT NULL COMMENT '수신자 전화번호',
    recvname VARCHAR(50) NOT NULL DEFAULT '' COMMENT '수신자 이름',
    subject VARCHAR(100) NOT NULL COMMENT '알림톡 제목',
    message TEXT NOT NULL COMMENT '알림톡 본문 (변수 치환 완료)',
    button_json JSON NULL COMMENT '버튼 정보',
    ref_type VARCHAR(30) NULL COMMENT '연관 엔티티 타입 (예: order)',
    ref_id INT NULL COMMENT '연관 엔티티 ID',
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING' COMMENT 'PENDING, SENT, FAILED',
    retry_count INT NOT NULL DEFAULT 0 COMMENT '발송 시도(실패) 횟수',
    aligo_mid VARCHAR(50) NULL COMMENT '알리고 발송 성공 시 메시지 ID',
    fail_reason VARCHAR(255) NULL COMMENT '최종 실패 사유',
    sent_at DATETIME NULL COMMENT '발송 성공 시각',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_status_retry (status, retry_count),
    INDEX idx_category (category),
    INDEX idx_ref (ref_type, ref_id),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='카카오 알림톡 발송 큐/이력';
