#!/usr/bin/env python3
"""
GNB-199: 발행잔액(issued_balance) PG수수료 반영 검증 테스트

실행 방법:
    cd /home/ubuntu/CafeBackend
    ENV=dev python3 tests/test_dashboard_summary.py

사전 조건:
    - dev DB 접속 가능 상태

테스트 전략:
    - order(pgcode, amount) + menu(price) + gifticon(status) 조합을 직접 INSERT
    - crud.stats.get_dashboard_summary()를 전/후로 호출해 issued_balance 증분을
      파이썬에서 독립적으로 재계산한 기대값과 비교
    - pgcode별 수수료율, USED 상태(집계 제외) 케이스, orders.amount != menu.price
      케이스(프로모션 할인 등)를 검증
"""
import sys
import os
import math

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["ENV"] = "dev"

import pymysql
from core.config import settings
from core.fees import PG_FEE_RATE_MAP, PG_FEE_RATE_DEFAULT
from crud import stats as stats_crud


def new_conn():
    return pymysql.connect(
        host=settings.db_host, user=settings.db_user,
        password=settings.db_password, database="cafeplatform_dev",
        port=settings.db_port, charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )


def setup_gifticon(menu_price: int, order_amount: int, pgcode: str, status: str) -> tuple[int, int, int]:
    """(menu_id, order_id, gifticon_id) 반환"""
    conn = new_conn()
    cur = conn.cursor()
    cur.execute("SET FOREIGN_KEY_CHECKS=0")
    cur.execute(
        "INSERT INTO menu (store_id, menu_name, price, status) VALUES (99999, '테스트메뉴', %s, 'ACTIVE')",
        (menu_price,)
    )
    menu_id = cur.lastrowid
    cur.execute(
        """INSERT INTO orders (store_id, user_id, payment_key, amount, status, order_no, payment, pgcode)
           VALUES (99999, 99999, 'TEST_FAKE_KEY', %s, 'COMPLETED', %s, 'card', %s)""",
        (order_amount, f"BAL-TEST-{os.getpid()}-{menu_id}", pgcode)
    )
    order_id = cur.lastrowid
    cur.execute(
        """INSERT INTO gifticon (user_id, type, sender, menu_id, store_id, order_id, status, gift_code)
           VALUES (99999, 1, '테스트발신', %s, 99999, %s, %s, %s)""",
        (menu_id, order_id, status, f"BAL-GIFT-{order_id}")
    )
    gifticon_id = cur.lastrowid
    cur.execute("SET FOREIGN_KEY_CHECKS=1")
    conn.commit()
    cur.close(); conn.close()
    return menu_id, order_id, gifticon_id


def teardown(menu_id: int, order_id: int, gifticon_id: int):
    conn = new_conn()
    cur = conn.cursor()
    cur.execute("SET FOREIGN_KEY_CHECKS=0")
    cur.execute("DELETE FROM gifticon WHERE id = %s", (gifticon_id,))
    cur.execute("DELETE FROM orders WHERE id = %s", (order_id,))
    cur.execute("DELETE FROM menu WHERE id = %s", (menu_id,))
    cur.execute("SET FOREIGN_KEY_CHECKS=1")
    conn.commit()
    cur.close(); conn.close()


def test_pg_fee_deducted_per_pgcode():
    """pgcode별 수수료율이 orders.amount 기준으로 정확히 차감되는지 검증"""
    cases = [
        ("creditcard", 10000, 10000),
        ("naverpay", 10000, 10000),
        ("kakaopay", 10000, 10000),
        ("applepay", 10000, 10000),
        ("samsungpay", 10000, 10000),
        ("banktransfer", 10000, 10000),
        ("voucher", 10000, 10000),
        ("unknown_pg", 10000, 10000),  # PG_FEE_RATE_DEFAULT 적용 확인
    ]
    created = []
    try:
        before = stats_crud.get_dashboard_summary()["issued_balance"]
        expected_delta = 0
        for pgcode, menu_price, order_amount in cases:
            ids = setup_gifticon(menu_price, order_amount, pgcode, "UNUSED")
            created.append(ids)
            rate = PG_FEE_RATE_MAP.get(pgcode, PG_FEE_RATE_DEFAULT)
            expected_delta += menu_price - math.floor(order_amount * rate / 100)

        after = stats_crud.get_dashboard_summary()["issued_balance"]
        assert after - before == expected_delta, f"기대 증분 {expected_delta}, 실제 {after - before}"
    finally:
        for ids in created:
            teardown(*ids)


def test_used_status_excluded():
    """USED 상태는 발행잔액 집계에서 제외됨을 유지 검증(회귀 방지)"""
    before = stats_crud.get_dashboard_summary()["issued_balance"]
    ids = setup_gifticon(10000, 10000, "creditcard", "USED")
    try:
        after = stats_crud.get_dashboard_summary()["issued_balance"]
        assert after == before, "USED 상태는 잔액에 포함되면 안 됨"
    finally:
        teardown(*ids)


def test_refund_requested_included():
    """REFUND_REQUESTED(환불 요청 중, 아직 미완료)는 발행잔액에 포함되어야 함"""
    before = stats_crud.get_dashboard_summary()["issued_balance"]
    menu_price, order_amount = 10000, 10000
    ids = setup_gifticon(menu_price, order_amount, "creditcard", "REFUND_REQUESTED")
    try:
        after = stats_crud.get_dashboard_summary()["issued_balance"]
        rate = PG_FEE_RATE_MAP["creditcard"]
        expected = menu_price - math.floor(order_amount * rate / 100)
        assert after - before == expected, f"REFUND_REQUESTED가 잔액에서 누락됨: 기대 {expected}, 실제 {after - before}"
    finally:
        teardown(*ids)


def test_refunded_and_canceled_excluded():
    """REFUNDED(환불 완료), CANCELED(취소 완료)는 발행잔액에서 제외되어야 함"""
    before = stats_crud.get_dashboard_summary()["issued_balance"]
    ids_refunded = setup_gifticon(10000, 10000, "creditcard", "REFUNDED")
    ids_canceled = setup_gifticon(10000, 10000, "creditcard", "CANCELED")
    try:
        after = stats_crud.get_dashboard_summary()["issued_balance"]
        assert after == before, "REFUNDED/CANCELED 상태는 잔액에 포함되면 안 됨"
    finally:
        teardown(*ids_refunded)
        teardown(*ids_canceled)


def test_promo_price_uses_order_amount_not_menu_price():
    """menu.price와 orders.amount가 다른 경우(프로모션 할인 등) PG수수료는 orders.amount 기준"""
    before = stats_crud.get_dashboard_summary()["issued_balance"]
    menu_price, order_amount = 10000, 8000  # 20% 할인 결제 가정
    ids = setup_gifticon(menu_price, order_amount, "creditcard", "PENDING")
    try:
        after = stats_crud.get_dashboard_summary()["issued_balance"]
        rate = PG_FEE_RATE_MAP["creditcard"]
        expected = menu_price - math.floor(order_amount * rate / 100)
        assert after - before == expected, f"기대 {expected}, 실제 {after - before}"
    finally:
        teardown(*ids)


if __name__ == "__main__":
    tests = [
        test_pg_fee_deducted_per_pgcode,
        test_used_status_excluded,
        test_refund_requested_included,
        test_refunded_and_canceled_excluded,
        test_promo_price_uses_order_amount_not_menu_price,
    ]
    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {t.__name__}: {e}")
            failed += 1
    print(f"\n{passed}/{len(tests)} 통과")
    sys.exit(0 if failed == 0 else 1)
