-- Menu 테이블의 menuId 컬럼을 id로 변경
-- 주의: 이 작업은 외래키 제약조건이 있는 경우 실패할 수 있습니다.
-- 먼저 외래키를 제거하고, 컬럼명을 변경한 후 외래키를 다시 추가해야 합니다.

-- 1. 외래키 제약조건 확인 및 제거 (필요한 경우)
-- SHOW CREATE TABLE menu; -- 외래키 제약조건 확인

-- 2. menuId 컬럼을 id로 변경
ALTER TABLE menu CHANGE COLUMN menuId id INT AUTO_INCREMENT;

-- 3. 외래키 제약조건이 있었다면 다시 추가
-- 예시:
-- ALTER TABLE 다른테이블 ADD CONSTRAINT fk_다른테이블_menu 
-- FOREIGN KEY (menu_id) REFERENCES menu(id) ON DELETE CASCADE ON UPDATE CASCADE;

