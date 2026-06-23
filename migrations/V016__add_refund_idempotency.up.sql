-- GNB-20: 환불 중복 방지를 위해 order_id에 UNIQUE INDEX 추가
ALTER TABLE refund
    ADD CONSTRAINT uq_refund_order_id UNIQUE (order_id);
