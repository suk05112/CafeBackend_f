-- account 테이블 store_id에 UNIQUE 제약 추가 (중복 계좌 등록 방지)
ALTER TABLE account ADD UNIQUE KEY uq_account_store_id (store_id);
