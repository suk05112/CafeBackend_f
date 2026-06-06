-- V014 롤백: login_id 컬럼 제거, email NOT NULL 복원

ALTER TABLE owner
    DROP INDEX uk_login_id,
    DROP COLUMN login_id,
    MODIFY COLUMN email VARCHAR(255) NOT NULL COMMENT '이메일';
