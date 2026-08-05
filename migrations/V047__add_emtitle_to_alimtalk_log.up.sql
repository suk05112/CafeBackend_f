-- GNB-233: subject(카카오톡 알림톡 제목)와 emtitle(강조표기형 핵심정보, Aligo emtitle_1)은
-- 개념적으로 다른 값이며 항상 같지 않다. templateEmType=TEXT로 등록된 템플릿은 emtitle_1을
-- 등록된 templtTitle과 함께 보내지 않으면 "메시지가 템플릿과 일치하지않음"으로 리젝된다
-- (2026-08-05 Aligo 고객센터 확인). 템플릿별 emtitle 값을 subject와 별도로 저장한다.
ALTER TABLE alimtalk_log
    ADD COLUMN emtitle VARCHAR(50) NULL COMMENT '강조표기형 핵심정보 (Aligo emtitle_1). templateEmType=TEXT인 템플릿만 필요' AFTER subject;
