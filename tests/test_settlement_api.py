#!/usr/bin/env python3
"""
정산 API 기댓값 vs 실제 응답값 비교 테스트

실행 방법:
  cd /home/ubuntu/CafeBackend
  ENV=dev python3 tests/test_settlement_api.py

사전 조건:
  서버가 실행 중이어야 합니다 (uvicorn app.main:app --port 8000)
  또는 --insert-only 옵션으로 데이터 삽입만 할 수 있습니다.
"""
import sys
import os
import argparse
import pymysql
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 테스트는 항상 dev DB만 사용
os.environ["ENV"] = "dev"
from core.config import settings

BASE_URL = "http://localhost:8001/dev"

# ──────────────────────────────────────────
# 테스트 픽스처 (삽입할 가짜 데이터 + 기댓값)
# ──────────────────────────────────────────
FIXTURES = [
    {
        "input": {
            "store_id": 9999,
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "total_sales_amount": 150000,
            "total_fee_amount": 5775,
            "net_payout_amount": 144225,
            "base_fee_rate": 3.50,
            "applied_promo_id": None,
            "applied_fee_rate": 3.50,
            "original_fee_supply": 5250,
            "original_fee_vat": 525,
            "original_fee_amount": 5775,
            "promo_fee_supply": None,
            "promo_fee_vat": None,
            "promo_fee_amount": None,
            "status": "COMPLETED",
            "payout_date": "2026-01-10",
            "memo": "테스트 정산 1월",
            "tax_invoice_issued": 0,
            "tax_invoice_issued_date": None,
        },
        "expected_list_item": {
            "total_price": 150000,
            "settlement_msg": "테스트 정산 1월",
            "settlement_date": "2026-01-10",
            "settlement_period": "2026-01",
            "status": "COMPLETED",
            "tax_invoice_issued": False,
            "tax_invoice_issued_date": None,
        },
    },
    {
        "input": {
            "store_id": 9999,
            "period_start": "2026-02-01",
            "period_end": "2026-02-28",
            "total_sales_amount": 220000,
            "total_fee_amount": 8470,
            "net_payout_amount": 211530,
            "base_fee_rate": 3.50,
            "applied_promo_id": None,
            "applied_fee_rate": 3.50,
            "original_fee_supply": 7700,
            "original_fee_vat": 770,
            "original_fee_amount": 8470,
            "promo_fee_supply": None,
            "promo_fee_vat": None,
            "promo_fee_amount": None,
            "status": "PENDING",
            "payout_date": None,
            "memo": "",
            "tax_invoice_issued": 0,
            "tax_invoice_issued_date": None,
        },
        "expected_list_item": {
            "total_price": 220000,
            "settlement_msg": "",
            "settlement_date": None,
            "settlement_period": "2026-02",
            "status": "PENDING",
            "tax_invoice_issued": False,
            "tax_invoice_issued_date": None,
        },
    },
]


# ──────────────────────────────────────────
# DB 유틸
# ──────────────────────────────────────────
def get_conn():
    return pymysql.connect(
        host=settings.db_host,
        user=settings.db_user,
        password=settings.db_password,
        database=settings.db_name,
        port=settings.db_port,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )


def insert_fixtures():
    """가짜 정산 데이터를 DB에 삽입하고 삽입된 ID 목록 반환"""
    conn = get_conn()
    cursor = conn.cursor()
    inserted_ids = []

    try:
        for f in FIXTURES:
            inp = f["input"]
            cursor.execute(
                """
                INSERT INTO settlement
                  (store_id, period_start, period_end,
                   total_sales_amount, total_fee_amount, net_payout_amount,
                   base_fee_rate, applied_promo_id, applied_fee_rate,
                   original_fee_supply, original_fee_vat, original_fee_amount,
                   promo_fee_supply, promo_fee_vat, promo_fee_amount,
                   status, payout_date, memo,
                   tax_invoice_issued, tax_invoice_issued_date)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    inp["store_id"],
                    inp["period_start"],
                    inp["period_end"],
                    inp["total_sales_amount"],
                    inp["total_fee_amount"],
                    inp["net_payout_amount"],
                    inp["base_fee_rate"],
                    inp["applied_promo_id"],
                    inp["applied_fee_rate"],
                    inp["original_fee_supply"],
                    inp["original_fee_vat"],
                    inp["original_fee_amount"],
                    inp["promo_fee_supply"],
                    inp["promo_fee_vat"],
                    inp["promo_fee_amount"],
                    inp["status"],
                    inp["payout_date"],
                    inp["memo"],
                    inp["tax_invoice_issued"],
                    inp["tax_invoice_issued_date"],
                ),
            )
            inserted_ids.append(cursor.lastrowid)
        conn.commit()
        print(f"[SETUP] 가짜 데이터 {len(inserted_ids)}건 삽입 완료 (IDs: {inserted_ids})")
        return inserted_ids
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()
        conn.close()


def cleanup_fixtures(store_id: int = 9999):
    """테스트용 가짜 데이터 삭제"""
    conn = get_conn()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM settlement WHERE store_id = %s", (store_id,))
        conn.commit()
        print(f"[TEARDOWN] store_id={store_id} 테스트 데이터 삭제 완료 ({cursor.rowcount}건)")
    finally:
        cursor.close()
        conn.close()


# ──────────────────────────────────────────
# 테스트 헬퍼
# ──────────────────────────────────────────
passed = 0
failed = 0


def assert_eq(label: str, expected, actual):
    global passed, failed
    # Decimal → float/int 변환 허용
    if isinstance(actual, float) and isinstance(expected, int):
        actual = int(actual)
    if expected == actual:
        print(f"  ✓  {label}")
        passed += 1
    else:
        print(f"  ✗  {label}")
        print(f"       기댓값: {repr(expected)}")
        print(f"       실제값: {repr(actual)}")
        failed += 1


# ──────────────────────────────────────────
# 테스트 케이스
# ──────────────────────────────────────────
def test_settlement_list(store_id: int = 9999):
    print("\n" + "=" * 60)
    print(f"[TEST] GET /settlement/list/{store_id}")
    print("=" * 60)

    resp = requests.get(f"{BASE_URL}/settlement/list/{store_id}", timeout=5)
    assert_eq("HTTP 200 응답", 200, resp.status_code)

    body = resp.json()
    assert_eq("응답에 'settlements' 키 존재", True, "settlements" in body)

    settlements = body.get("settlements", [])
    assert_eq(f"정산 건수 = {len(FIXTURES)}", len(FIXTURES), len(settlements))

    # API는 최신순 정렬(DESC)이므로 FIXTURES 역순과 비교
    for i, (settlement, fixture) in enumerate(zip(settlements, reversed(FIXTURES))):
        exp = fixture["expected_list_item"]
        prefix = f"  [건{i+1}]"
        print(f"\n{prefix} settlement_id={settlement.get('settlement_id')}")

        assert_eq(f"{prefix} total_price", exp["total_price"], settlement.get("total_price"))
        assert_eq(f"{prefix} settlement_msg", exp["settlement_msg"], settlement.get("settlement_msg"))
        assert_eq(f"{prefix} settlement_date", exp["settlement_date"], settlement.get("settlement_date"))
        assert_eq(f"{prefix} settlement_period", exp["settlement_period"], settlement.get("settlement_period"))
        assert_eq(f"{prefix} status", exp["status"], settlement.get("status"))
        assert_eq(f"{prefix} tax_invoice_issued", exp["tax_invoice_issued"], settlement.get("tax_invoice_issued"))
        assert_eq(f"{prefix} tax_invoice_issued_date", exp["tax_invoice_issued_date"], settlement.get("tax_invoice_issued_date"))

    return settlements


def test_settlement_list_empty(store_id: int = 88888):
    print("\n" + "=" * 60)
    print(f"[TEST] GET /settlement/list/{store_id} (존재하지 않는 store)")
    print("=" * 60)

    resp = requests.get(f"{BASE_URL}/settlement/list/{store_id}", timeout=5)
    assert_eq("HTTP 200 응답", 200, resp.status_code)

    body = resp.json()
    settlements = body.get("settlements", [])
    assert_eq("빈 리스트 반환", [], settlements)


def test_settlement_account_not_found(store_id: int = 9999):
    print("\n" + "=" * 60)
    print(f"[TEST] GET /settlement/info/{store_id} (계좌 없음)")
    print("=" * 60)

    resp = requests.get(f"{BASE_URL}/settlement/info/{store_id}", timeout=5)
    assert_eq("HTTP 200 응답", 200, resp.status_code)

    body = resp.json()
    assert_eq("account = {}", {}, body.get("account"))


# ──────────────────────────────────────────
# 메인
# ──────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--insert-only", action="store_true", help="데이터 삽입만 하고 종료")
    parser.add_argument("--cleanup-only", action="store_true", help="테스트 데이터 삭제만 하고 종료")
    parser.add_argument("--no-cleanup", action="store_true", help="테스트 후 데이터 삭제 안 함")
    args = parser.parse_args()

    if args.cleanup_only:
        cleanup_fixtures()
        return 0

    insert_fixtures()

    if args.insert_only:
        print("[INFO] --insert-only 모드: 서버 테스트 생략")
        return 0

    try:
        test_settlement_list()
        test_settlement_list_empty()
        test_settlement_account_not_found()
    finally:
        if not args.no_cleanup:
            cleanup_fixtures()

    print("\n" + "=" * 60)
    print(f"결과: {passed}개 통과 / {failed}개 실패 / 총 {passed+failed}개")
    print("=" * 60)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
