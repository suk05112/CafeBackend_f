-- GNB-131: owner 성별 컬럼 추가 (mobileOK 본인확인 결과 저장)
-- birthdate는 V022에서 이미 추가됨

ALTER TABLE owner
    ADD COLUMN gender CHAR(1) NULL COMMENT '성별 (M=남성, F=여성, mobileOK 본인확인 결과)' AFTER birthdate;
