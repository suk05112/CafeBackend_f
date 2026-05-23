ALTER TABLE settlement
  ADD COLUMN tax_invoice_issued      TINYINT(1) NOT NULL DEFAULT 0 COMMENT '세금계산서 발행 여부',
  ADD COLUMN tax_invoice_issued_date DATE       NULL              COMMENT '세금계산서 발행일',
  ADD COLUMN memo                    TEXT       NULL              COMMENT '메모';
