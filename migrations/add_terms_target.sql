-- terms 테이블에 target 컬럼 추가 (유저/사장님 구분)
-- 이미 target이 있으면 스킵하려면 조건부 실행이 필요하므로, 없을 때만 실행하세요.

ALTER TABLE terms
    ADD COLUMN target VARCHAR(10) NOT NULL DEFAULT 'user' COMMENT 'user=유저용, owner=사장님용' AFTER id;

ALTER TABLE terms
    DROP INDEX uk_terms_term_type;

ALTER TABLE terms
    ADD UNIQUE KEY uk_terms_target_term_type (target, term_type),
    ADD INDEX idx_terms_target (target);

ALTER TABLE terms
    MODIFY COLUMN target VARCHAR(10) NOT NULL COMMENT 'user=유저용, owner=사장님용';
