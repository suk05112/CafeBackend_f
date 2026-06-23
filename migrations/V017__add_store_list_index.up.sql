-- GNB-101: store 테이블 매장 목록 조회 성능 개선용 복합 인덱스 추가
CREATE INDEX idx_store_list
    ON store (region_code, inspection_status, contract_completed, updated_at DESC, id DESC);
