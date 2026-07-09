-- 사장님 개인정보 처리방침 v260708: 수집항목(성별·생년월일) 추가, 위탁사(드림시큐리티·페이레터) 추가
INSERT INTO terms_version (term_id, version, notice_date, effective_date, reagreement_required)
SELECT id, '260708', '2026-06-08', '2026-07-08', TRUE
FROM terms
WHERE target = 'owner' AND term_type = 'PRIVACY';

-- 사장님 개인정보 수집 및 이용 동의 v260708: 동일 항목 추가, 위탁 섹션 신규 추가
INSERT INTO terms_version (term_id, version, notice_date, effective_date, reagreement_required)
SELECT id, '260708', '2026-06-08', '2026-07-08', TRUE
FROM terms
WHERE target = 'owner' AND term_type = 'PRIVACY_CONSENT';
