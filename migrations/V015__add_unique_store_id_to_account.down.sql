-- account 테이블 store_id UNIQUE 제약 제거
ALTER TABLE account DROP INDEX uq_account_store_id;
