ALTER TABLE user_terms_agreement
    ADD COLUMN agreed_ip VARCHAR(45) NULL AFTER agreed_at;

ALTER TABLE owner_terms_agreement
    ADD COLUMN agreed_ip VARCHAR(45) NULL AFTER agreed_at;
