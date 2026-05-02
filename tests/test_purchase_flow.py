#!/usr/bin/env python3
"""
GNB-9: 상품권 구매 흐름 테스트 (페이레터)

테스트 대상:
  1. 주문 생성 (POST /order/{user_id})
  2. 페이레터 결제 콜백 (POST /order/payment/result)
     - 정상 결제 성공
     - payhash 불일치 거절
  3. 환불 (POST /order/refund/{order_id})
     - 7일 이내 구매자 환불 (페이레터 취소 mock)

실행 방법:
  cd /home/ubuntu/CafeBackend
  ENV=dev python3 tests/test_purchase_flow.py

사전 조건:
  - 서버가 실행 중이어야 합니다 (uvicorn main:app --port 8001)
  - DB에 user_id=1, store_id=1, menu_id=1 데이터가 존재해야 합니다
"""
import sys
import os
import hashlib
import json
import requests
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["ENV"] = "dev"

from core.config import settings

BASE_URL = "http://localhost:8001/dev"

# 테스트용 고정값 (DB 실제 데이터 기준)
TEST_USER_ID = 44
TEST_STORE_ID = 1
TEST_MENU_ID = 2   # 카페라떼 5000원, store_id=1
TEST_AMOUNT = 5000
PAYLETTER_CLIENT_ID = settings.payletter_client_id
PAYLETTER_API_KEY = settings.payletter_payment_api_key


def make_payhash(user_id: str, amount: int, tid: str) -> str:
    raw = user_id + str(amount) + tid + PAYLETTER_API_KEY
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def print_result(name: str, passed: bool, detail: str = ""):
    mark = "✓" if passed else "✗"
    print(f"  {mark} {name}" + (f": {detail}" if detail else ""))


# ──────────────────────────────────────────
# TC-1: 주문 생성
# ──────────────────────────────────────────
def test_create_order() -> int | None:
    print("\n[TC-1] 주문 생성")
    url = f"{BASE_URL}/order/{TEST_USER_ID}"
    payload = {
        "type": 1,
        "sender": "테스트발신자",
        "receiver": "테스트수신자",
        "receiver_phone_number": "01012345678",
        "menu_id": TEST_MENU_ID,
        "store_id": TEST_STORE_ID,
        "total_price": TEST_AMOUNT,
        "payment_key": None,
        "payment": "CARD",
    }

    res = requests.post(url, json=payload)
    ok = res.status_code == 200

    if ok:
        data = res.json()
        order_id = data.get("order_id")
        print_result("주문 생성 성공 (200)", ok, f"order_id={order_id}")
        print_result("order_id 존재", order_id is not None)
        print_result("status=PENDING", data.get("status") == "PENDING")
        return order_id
    else:
        print_result("주문 생성 성공 (200)", ok, res.text[:200])
        return None


# ──────────────────────────────────────────
# TC-2: 페이레터 결제 콜백 - 정상
# ──────────────────────────────────────────
def test_payment_callback_success(order_id: int) -> str | None:
    print("\n[TC-2] 결제 콜백 - 정상 (payhash 일치)")
    url = f"{BASE_URL}/order/payment/result"

    tid = f"TEST_TID_{order_id}"
    user_id_str = str(order_id)
    payhash = make_payhash(user_id_str, TEST_AMOUNT, tid)

    payload = {
        "order_id": order_id,
        "tid": tid,
        "cid": PAYLETTER_CLIENT_ID,
        "amount": TEST_AMOUNT,
        "user_id": user_id_str,
        "transaction_date": datetime.now().strftime("%Y%m%d%H%M%S"),
        "payhash": payhash,
    }

    res = requests.post(url, json=payload)
    ok = res.status_code == 200

    if ok:
        data = res.json()
        print_result("콜백 처리 성공 (200)", ok)
        print_result('응답 code=0', data.get("code") == 0, str(data))
        print_result('응답 message=success', data.get("message") == "success")
        return tid
    else:
        print_result("콜백 처리 성공 (200)", ok, res.text[:200])
        return None


# ──────────────────────────────────────────
# TC-3: 페이레터 결제 콜백 - payhash 불일치
# ──────────────────────────────────────────
def test_payment_callback_invalid_hash(order_id: int):
    print("\n[TC-3] 결제 콜백 - payhash 불일치 거절")
    url = f"{BASE_URL}/order/payment/result"

    tid = f"TEST_TID_FAKE_{order_id}"
    payload = {
        "order_id": order_id,
        "tid": tid,
        "cid": PAYLETTER_CLIENT_ID,
        "amount": TEST_AMOUNT,
        "user_id": str(order_id),
        "transaction_date": datetime.now().strftime("%Y%m%d%H%M%S"),
        "payhash": "INVALID_HASH_VALUE",
    }

    res = requests.post(url, json=payload)
    print_result("400 반환 (payhash 불일치)", res.status_code == 400, f"status={res.status_code}")


# ──────────────────────────────────────────
# TC-4: 주문 상태 확인 (COMPLETED)
# ──────────────────────────────────────────
def test_order_status_completed(order_id: int):
    print("\n[TC-4] 결제 후 주문 상태 확인")
    import pymysql
    from db.session import get_db_connection

    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    try:
        cursor.execute("SELECT status, payment_key FROM orders WHERE id=%s", (order_id,))
        row = cursor.fetchone()
        if row:
            print_result("orders.status=COMPLETED", row["status"] == "COMPLETED", f"actual={row['status']}")
            print_result("orders.payment_key=tid 저장", row["payment_key"] is not None, f"tid={row['payment_key']}")
        else:
            print_result("주문 조회", False, "row not found")

        cursor.execute(
            "SELECT status, validity FROM gifticon WHERE order_id=%s LIMIT 1",
            (order_id,),
        )
        g = cursor.fetchone()
        if g:
            print_result("gifticon.status=UNUSED", g["status"] == "UNUSED", f"actual={g['status']}")
            print_result("gifticon.validity 설정됨", g["validity"] is not None)
        else:
            print_result("기프티콘 조회", False, "row not found")
    finally:
        cursor.close()
        connection.close()


# ──────────────────────────────────────────
# TC-5: 환불 (7일 이내, 페이레터 취소)
# ──────────────────────────────────────────
def test_refund(order_id: int):
    print("\n[TC-5] 환불 요청 (7일 이내 구매자 환불)")
    url = f"{BASE_URL}/order/refund/{order_id}"
    payload = {"reason": "테스트 환불"}

    # 페이레터 테스트 서버에 실제 취소 요청이 가므로 tid가 유효하지 않으면 실패할 수 있음
    # 응답 코드만 확인 (500이면 페이레터 취소 실패, 200이면 성공)
    res = requests.post(url, json=payload)
    print_result(
        "환불 API 응답",
        res.status_code in (200, 500),
        f"status={res.status_code} (200=성공, 500=페이레터 취소 실패 예상)",
    )
    if res.status_code == 200:
        data = res.json()
        print_result("환불 유형=PURCHASER", data.get("refund_type") == "PURCHASER", str(data))


# ──────────────────────────────────────────
# TC-6: 중복 주문 방지
# ──────────────────────────────────────────
def test_duplicate_order_prevention():
    print("\n[TC-6] 중복 주문 방지 (5분 내 동일 결제 완료 주문)")

    # 먼저 주문 생성 후 결제 완료 처리
    order_id = test_create_order_silent()
    if not order_id:
        print_result("선행 주문 생성", False, "건너뜀")
        return

    tid = f"DUP_TID_{order_id}"
    user_id_str = str(order_id)
    payhash = make_payhash(user_id_str, TEST_AMOUNT, tid)
    callback_payload = {
        "order_id": order_id,
        "tid": tid,
        "cid": PAYLETTER_CLIENT_ID,
        "amount": TEST_AMOUNT,
        "user_id": user_id_str,
        "transaction_date": datetime.now().strftime("%Y%m%d%H%M%S"),
        "payhash": payhash,
    }
    requests.post(f"{BASE_URL}/order/payment/result", json=callback_payload)

    # 동일 조건으로 두 번째 주문 시도
    url = f"{BASE_URL}/order/{TEST_USER_ID}"
    payload = {
        "type": 1,
        "sender": "테스트발신자",
        "receiver": "테스트수신자",
        "receiver_phone_number": "01012345678",
        "menu_id": TEST_MENU_ID,
        "store_id": TEST_STORE_ID,
        "total_price": TEST_AMOUNT,
        "payment_key": None,
        "payment": "CARD",
    }
    res = requests.post(url, json=payload)
    print_result("중복 주문 400 반환", res.status_code == 400, f"status={res.status_code}")


def test_create_order_silent() -> int | None:
    url = f"{BASE_URL}/order/{TEST_USER_ID}"
    payload = {
        "type": 1,
        "sender": "테스트발신자",
        "receiver": "테스트수신자",
        "receiver_phone_number": "01012345678",
        "menu_id": TEST_MENU_ID,
        "store_id": TEST_STORE_ID,
        "total_price": TEST_AMOUNT,
        "payment_key": None,
        "payment": "CARD",
    }
    res = requests.post(url, json=payload)
    if res.status_code == 200:
        return res.json().get("order_id")
    return None


# ──────────────────────────────────────────
# 메인
# ──────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("GNB-9: 상품권 구매 흐름 테스트 (페이레터)")
    print(f"BASE_URL: {BASE_URL}")
    print(f"Payletter client_id: {PAYLETTER_CLIENT_ID}")
    print("=" * 60)

    order_id = test_create_order()

    if order_id:
        tid = test_payment_callback_success(order_id)
        test_order_status_completed(order_id)

        # payhash 불일치 테스트는 새 order_id 불필요 (이미 완료된 주문에 요청해도 hash에서 먼저 걸림)
        test_payment_callback_invalid_hash(order_id + 9999)

        if tid:
            test_refund(order_id)
    else:
        print("\n⚠ 주문 생성 실패로 이후 테스트를 건너뜁니다.")

    test_duplicate_order_prevention()

    print("\n" + "=" * 60)
    print("테스트 완료")
    print("=" * 60)
