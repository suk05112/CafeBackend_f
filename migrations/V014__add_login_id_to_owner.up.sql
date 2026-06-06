-- owner 테이블에 login_id 컬럼 추가 (@gifnut.com 내부 계정용)
-- email 컬럼을 NULL 허용으로 변경 (일반 이메일 계정만 사용)

ALTER TABLE owner
    ADD COLUMN login_id VARCHAR(255) NULL COMMENT '@gifnut.com 내부 로그인 ID (이메일 전체 저장)' AFTER uid,
    ADD UNIQUE KEY uk_login_id (login_id),
    MODIFY COLUMN email VARCHAR(255) NULL COMMENT '일반 이메일';
