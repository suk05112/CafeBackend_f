-- GNB-131: 드림시큐리티 mobileOK 본인확인 연동 (사장님 전용)
-- 1. mok_client_tx: clientTxId 재사용 방지 테이블 신규 생성
-- 2. owner: birthdate 컬럼 추가

CREATE TABLE mok_client_tx (
    client_tx_id VARCHAR(40) NOT NULL COMMENT '이용기관 거래 ID (clientTxId)',
    used         TINYINT(1)  NOT NULL DEFAULT 0 COMMENT '사용 여부 (0=미사용, 1=사용)',
    created_at   DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성 일시',
    PRIMARY KEY (client_tx_id),
    INDEX idx_mok_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='mobileOK clientTxId 재사용 방지';

ALTER TABLE owner
    ADD COLUMN birthdate DATE NULL COMMENT '생년월일 (mobileOK 본인확인 결과)' AFTER phone_number;
