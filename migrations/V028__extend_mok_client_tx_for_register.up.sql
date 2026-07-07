-- GNB-147: mok_client_tx에 본인확인 결과 임시 저장 컬럼 추가
-- 회원가입 시 /register가 clientTxId로 조회하여 owner에 복사

ALTER TABLE mok_client_tx
    ADD COLUMN verified_name VARCHAR(100) NULL COMMENT '본인확인 검증된 이름' AFTER used,
    ADD COLUMN verified_phone VARCHAR(20) NULL COMMENT '본인확인 검증된 전화번호' AFTER verified_name,
    ADD COLUMN verified_birthdate VARCHAR(8) NULL COMMENT '본인확인 검증된 생년월일(YYYYMMDD)' AFTER verified_phone,
    ADD COLUMN verified_gender CHAR(1) NULL COMMENT '본인확인 검증된 성별(M/F)' AFTER verified_birthdate,
    ADD COLUMN verified_at DATETIME NULL COMMENT '본인확인 완료 시각' AFTER verified_gender,
    ADD COLUMN consumed_at DATETIME NULL COMMENT '/register에서 소비된 시각 (재사용 방지)' AFTER verified_at;
