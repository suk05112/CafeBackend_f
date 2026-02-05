-- user 테이블에 fb_email 컬럼 추가 (이메일 로그인 시 저장)
-- provider가 'email'일 때 request의 email을 fb_email에 저장

ALTER TABLE `user`
ADD COLUMN fb_email VARCHAR(255) NOT NULL DEFAULT '' COMMENT '이메일 로그인 시 저장' AFTER email;
