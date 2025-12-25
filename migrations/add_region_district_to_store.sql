-- Store 테이블에 region_code와 district_code 컬럼 추가
-- region_code: 시/도 코드 (예: "01" = 서울특별시)
-- district_code: 군/구 코드 (예: "23" = 강남구)

-- region_code 컬럼 추가
ALTER TABLE Store 
ADD COLUMN region_code VARCHAR(2) NULL COMMENT '시/도 코드' AFTER store_address;

-- district_code 컬럼 추가
ALTER TABLE Store 
ADD COLUMN district_code VARCHAR(10) NULL COMMENT '군/구 코드' AFTER region_code;

-- 인덱스 추가 (조회 성능 향상)
CREATE INDEX idx_region_code ON Store(region_code);
CREATE INDEX idx_district_code ON Store(district_code);
CREATE INDEX idx_region_district ON Store(region_code, district_code);

-- 기존 데이터가 있다면 업데이트 (store_address나 다른 정보를 기반으로)
-- 주의: 이 부분은 실제 데이터에 맞게 수정이 필요합니다
-- 예시:
-- UPDATE Store SET region_code = '01', district_code = '23' WHERE store_id = 1;

