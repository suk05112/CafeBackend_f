#!/usr/bin/env python3
"""
GNB-53: 구매 시점 수수료율 확정 테스트

테스트 케이스:
  TC-1: 프로모션 없음 (store_id=1) → base_fee_rate(6.30%)가 applied_fee_rate로 저장
  TC-2: 활성 프로모션 (store_id=2) → promo_fee_rate(1.50%)가 applied_fee_rate로 저장, applied_promo_id 설정
  TC-3: 만료된 프로모션 (store_id=7) → base_fee_rate(6.30%) fallback

  각 TC는 store_id를 다르게 사용하여 프로모션이 서로 간섭하지 않도록 격리

실행 방법:
  cd /home/ubuntu/CafeBackend
  ENV=dev python3 tests/test_fee_policy_order.py

사전 조건:
  - 서버가 실행 중이어야 합니다 (uvicorn main:app --port 8001)
"""
import sys
import os
import pymysql
import requests
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["ENV"] = "dev"

from db.session import get_db_connection

BASE_URL = "http://localhost:8001/dev"
TEST_USER_ID = 44
BASE_FEE_RATE = 6.30
PROMO_FEE_RATE = 1.50

# TC별 store/menu 격리
TC1_STORE_ID, TC1_MENU_ID, TC1_AMOUNT = 1, 2, 5000   # 프로모션 없음
TC2_STORE_ID, TC2_MENU_ID, TC2_AMOUNT = 2, 3, 4500   # 활성 프로모션
TC3_STORE_ID, TC3_MENU_ID, TC3_AMOUNT = 7, 4, 5000   # 만료된 프로모션


def print_result(name: str, passed: bool, detail: str = ""):
    mark = "✓" if passed else "✗"
    print(f"  {mark} {name}" + (f": {detail}" if detail else ""))


def create_order(store_id: int, menu_id: int, amount: int) -> dict | None:
    res = requests.post(
        f"{BASE_URL}/order/{TEST_USER_ID}",
        json={
            "type": 1,
            "sender": "테스트발신자",
            "receiver": "테스트수신자",
            "receiver_phone_number": "01012345678",
            "menu_id": menu_id,
            "store_id": store_id,
            "total_price": amount,
            "payment_key": None,
            "payment": "CARD",
        }
    )
    if res.status_code == 200:
        return res.json()
    print(f"  주문 생성 실패: {res.status_code} {res.text[:200]}")
    return None


def use_gifticon(gifticon_id: int) -> bool:
    res = requests.patch(f"{BASE_URL}/gifticon/use/{gifticon_id}")
    return res.status_code == 200 and res.json().get("result") == 0


def get_gifticon_fee_info(order_id: int) -> dict | None:
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    try:
        cursor.execute(
            "SELECT id, base_fee_rate, applied_promo_id, applied_fee_rate, status FROM gifticon WHERE order_id = %s LIMIT 1",
            (order_id,)
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        connection.close()


def get_settlement_detail(gifticon_id: int) -> dict | None:
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    try:
        cursor.execute(
            "SELECT * FROM settlement_details WHERE gifticon_id = %s LIMIT 1",
            (gifticon_id,)
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        connection.close()


def create_promo(store_id: int, fee_rate: float, start_date: date, end_date: date) -> int:
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            "INSERT INTO fee_promotions (promo_fee_rate, start_date, end_date, is_active) VALUES (%s, %s, %s, TRUE)",
            (fee_rate, start_date, end_date)
        )
        promo_id = cursor.lastrowid
        cursor.execute(
            "INSERT INTO fee_promotion_stores (promo_id, store_id) VALUES (%s, %s)",
            (promo_id, store_id)
        )
        connection.commit()
        return promo_id
    finally:
        cursor.close()
        connection.close()


def delete_promo(promo_id: int):
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        cursor.execute("DELETE FROM fee_promotions WHERE promo_id = %s", (promo_id,))
        connection.commit()
    finally:
        cursor.close()
        connection.close()


# ──────────────────────────────────────────
# TC-1: 프로모션 없음 → 기본 수수료율 적용
# ──────────────────────────────────────────
def test_no_promotion():
    print("\n[TC-1] 프로모션 없음 → 기본 수수료율(6.30%) 적용 (store_id=1)")

    order = create_order(TC1_STORE_ID, TC1_MENU_ID, TC1_AMOUNT)
    if not order:
        return

    order_id, gifticon_id = order["order_id"], order["gifticon_id"]
    fee = get_gifticon_fee_info(order_id)
    if not fee:
        print_result("gifticon 조회", False, "row not found")
        return

    print_result("주문 생성 성공", True, f"order_id={order_id}, gifticon_id={gifticon_id}")
    print_result(f"base_fee_rate={BASE_FEE_RATE}", float(fee["base_fee_rate"]) == BASE_FEE_RATE, f"actual={fee['base_fee_rate']}")
    print_result(f"applied_fee_rate={BASE_FEE_RATE}", float(fee["applied_fee_rate"]) == BASE_FEE_RATE, f"actual={fee['applied_fee_rate']}")
    print_result("applied_promo_id=NULL", fee["applied_promo_id"] is None, f"actual={fee['applied_promo_id']}")

    # 기프티콘 사용 처리
    used = use_gifticon(gifticon_id)
    print_result("기프티콘 사용 처리", used)

    sd = get_settlement_detail(gifticon_id)
    print_result("settlement_details 생성", sd is not None, f"id={sd['id'] if sd else None}")


# ──────────────────────────────────────────
# TC-2: 활성 프로모션 → 프로모션 수수료율 적용
# ──────────────────────────────────────────
def test_active_promotion():
    print("\n[TC-2] 활성 프로모션 → 프로모션 수수료율(1.50%) 적용 (store_id=2)")

    today = date.today()
    promo_id = create_promo(TC2_STORE_ID, PROMO_FEE_RATE, today, today + timedelta(days=7))

    try:
        order = create_order(TC2_STORE_ID, TC2_MENU_ID, TC2_AMOUNT)
        if not order:
            return

        order_id, gifticon_id = order["order_id"], order["gifticon_id"]
        fee = get_gifticon_fee_info(order_id)
        if not fee:
            print_result("gifticon 조회", False, "row not found")
            return

        print_result("주문 생성 성공", True, f"order_id={order_id}, gifticon_id={gifticon_id}")
        print_result(f"base_fee_rate={BASE_FEE_RATE}", float(fee["base_fee_rate"]) == BASE_FEE_RATE, f"actual={fee['base_fee_rate']}")
        print_result(f"applied_fee_rate={PROMO_FEE_RATE}", float(fee["applied_fee_rate"]) == PROMO_FEE_RATE, f"actual={fee['applied_fee_rate']}")
        print_result(f"applied_promo_id={promo_id}", fee["applied_promo_id"] == promo_id, f"actual={fee['applied_promo_id']}")

        # 기프티콘 사용 처리
        used = use_gifticon(gifticon_id)
        print_result("기프티콘 사용 처리", used)

        sd = get_settlement_detail(gifticon_id)
        print_result("settlement_details 생성", sd is not None, f"id={sd['id'] if sd else None}")
    finally:
        delete_promo(promo_id)


# ──────────────────────────────────────────
# TC-3: 만료된 프로모션 → 기본 수수료율 fallback
# ──────────────────────────────────────────
def test_expired_promotion():
    print("\n[TC-3] 만료된 프로모션 → 기본 수수료율(6.30%) fallback (store_id=7)")

    today = date.today()
    promo_id = create_promo(TC3_STORE_ID, PROMO_FEE_RATE, today - timedelta(days=10), today - timedelta(days=1))

    try:
        order = create_order(TC3_STORE_ID, TC3_MENU_ID, TC3_AMOUNT)
        if not order:
            return

        order_id, gifticon_id = order["order_id"], order["gifticon_id"]
        fee = get_gifticon_fee_info(order_id)
        if not fee:
            print_result("gifticon 조회", False, "row not found")
            return

        print_result("주문 생성 성공", True, f"order_id={order_id}, gifticon_id={gifticon_id}")
        print_result(f"base_fee_rate={BASE_FEE_RATE}", float(fee["base_fee_rate"]) == BASE_FEE_RATE, f"actual={fee['base_fee_rate']}")
        print_result(f"applied_fee_rate={BASE_FEE_RATE} (fallback)", float(fee["applied_fee_rate"]) == BASE_FEE_RATE, f"actual={fee['applied_fee_rate']}")
        print_result("applied_promo_id=NULL", fee["applied_promo_id"] is None, f"actual={fee['applied_promo_id']}")

        # 기프티콘 사용 처리
        used = use_gifticon(gifticon_id)
        print_result("기프티콘 사용 처리", used)

        sd = get_settlement_detail(gifticon_id)
        print_result("settlement_details 생성", sd is not None, f"id={sd['id'] if sd else None}")
    finally:
        delete_promo(promo_id)


# ──────────────────────────────────────────
# 메인
# ──────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("GNB-53: 구매 시점 수수료율 확정 테스트")
    print(f"BASE_URL: {BASE_URL}")
    print("=" * 60)

    test_no_promotion()
    test_active_promotion()
    test_expired_promotion()

    print("\n" + "=" * 60)
    print("테스트 완료")
    print("=" * 60)
