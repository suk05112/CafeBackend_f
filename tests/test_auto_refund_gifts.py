#!/usr/bin/env python3
"""
GNB-173: 미등록 선물 기프티콘 7일 자동 환불 배치 테스트

실행 방법:
    cd /home/ubuntu/CafeBackend
    ENV=dev python3 tests/test_auto_refund_gifts.py

테스트 전략:
    - created_at을 과거로 직접 설정한 테스트 데이터 사용
    - clock.freeze_time()으로 현재 시간 고정
    - auto_refund_unregistered_gifts() 배치 함수를 직접 호출
    - 페이레터 API는 unittest.mock으로 대체
    - 각 테스트 후 데이터 정리
"""
import sys
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["ENV"] = "dev"

import pymysql
from core.config import settings
from core import clock
from core.scheduler import auto_refund_unregistered_gifts

KST = timezone(timedelta(hours=9))

# ── DB 헬퍼 ──────────────────────────────────────────────────────────────────

def new_conn():
    return pymysql.connect(
        host=settings.db_host, user=settings.db_user,
        password=settings.db_password, database="cafeplatform_dev",
        port=settings.db_port, charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )


def setup_test_data(days_ago: int) -> tuple[int, int]:
    """FK 비활성화 후 테스트용 order/gifticon 삽입. (order_id, gifticon_id) 반환."""
    conn = new_conn()
    cur = conn.cursor()
    created_at = clock.now() - timedelta(days=days_ago)

    cur.execute("SET FOREIGN_KEY_CHECKS=0")
    cur.execute("""
        INSERT INTO menu (id, store_id, menu_name, price, status)
        VALUES (99999, 99999, '테스트메뉴', 5000, 'ACTIVE')
        ON DUPLICATE KEY UPDATE menu_name='테스트메뉴'
    """)
    cur.execute("""
        INSERT INTO orders (store_id, user_id, payment_key, amount, status, order_no, payment, pgcode, created_at)
        VALUES (99999, 99999, 'TEST_GIFT_FAKE_KEY', 5000, 'COMPLETED', %s, 'card', 'creditcard', %s)
    """, (f"GIFT-TEST-{days_ago}d-{os.getpid()}", created_at))
    order_id = cur.lastrowid
    cur.execute("""
        INSERT INTO gifticon (user_id, type, sender, menu_id, store_id, order_id, status, gift_code,
                              receiver_phone, receiver_id)
        VALUES (99999, 2, '테스트발신자', 99999, 99999, %s, 'UNUSED', %s, '01000000000', NULL)
    """, (order_id, f"GTEST-{order_id}"))
    gifticon_id = cur.lastrowid
    conn.commit()
    cur.execute("SET FOREIGN_KEY_CHECKS=1")
    conn.commit()
    conn.close()
    return order_id, gifticon_id


def teardown_test_data(order_id: int, gifticon_id: int):
    conn = new_conn()
    cur = conn.cursor()
    cur.execute("SET FOREIGN_KEY_CHECKS=0")
    cur.execute("DELETE FROM refund WHERE order_id = %s", (order_id,))
    cur.execute("DELETE FROM gifticon WHERE id = %s", (gifticon_id,))
    cur.execute("DELETE FROM orders WHERE id = %s", (order_id,))
    cur.execute("SET FOREIGN_KEY_CHECKS=1")
    conn.commit()
    conn.close()


def fetch_gifticon(gifticon_id: int) -> dict:
    conn = new_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM gifticon WHERE id = %s", (gifticon_id,))
    row = cur.fetchone()
    conn.close()
    return row or {}


def fetch_order(order_id: int) -> dict:
    conn = new_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM orders WHERE id = %s", (order_id,))
    row = cur.fetchone()
    conn.close()
    return row or {}


def fetch_refunds(order_id: int) -> list:
    conn = new_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM refund WHERE order_id = %s ORDER BY id", (order_id,))
    rows = cur.fetchall()
    conn.close()
    return rows


# ── 테스트 케이스 ─────────────────────────────────────────────────────────────

results = []


def run(name, fn):
    try:
        fn()
        results.append((True, name))
        print(f"  PASS  {name}")
    except AssertionError as e:
        results.append((False, name))
        print(f"  FAIL  {name}: {e}")
    except Exception as e:
        results.append((False, name))
        print(f"  ERROR {name}: {e}")


# ── T01: 6일 경과 → 환불 대상 아님 ───────────────────────────────────────────
def test_not_yet_7_days():
    order_id, gifticon_id = setup_test_data(days_ago=6)
    try:
        with patch("core.scheduler._payletter_cancel", return_value=True):
            auto_refund_unregistered_gifts()
        g = fetch_gifticon(gifticon_id)
        assert g["status"] == "UNUSED", f"상태가 UNUSED 여야 함: {g['status']}"
        refunds = fetch_refunds(order_id)
        assert len(refunds) == 0, "환불 레코드가 없어야 함"
    finally:
        teardown_test_data(order_id, gifticon_id)


# ── T02: 7일 경과 + 페이레터 성공 → CANCELED + REFUNDED ─────────────────────
def test_7_days_payletter_success():
    order_id, gifticon_id = setup_test_data(days_ago=7)
    try:
        with patch("core.scheduler._payletter_cancel", return_value=True):
            auto_refund_unregistered_gifts()
        g = fetch_gifticon(gifticon_id)
        assert g["status"] == "CANCELED", f"gifticon 상태가 CANCELED 여야 함: {g['status']}"
        o = fetch_order(order_id)
        assert o["status"] == "REFUNDED", f"order 상태가 REFUNDED 여야 함: {o['status']}"
        refunds = fetch_refunds(order_id)
        assert len(refunds) == 1, f"환불 레코드 1건이어야 함: {len(refunds)}건"
        assert refunds[0]["status"] == "COMPLETED", f"refund 상태: {refunds[0]['status']}"
        assert int(refunds[0]["amount"]) == 5000, f"환불액: {refunds[0]['amount']}"
        assert refunds[0]["refund_type"] == "PURCHASER"
    finally:
        teardown_test_data(order_id, gifticon_id)


# ── T03: 7일 경과 + 페이레터 실패 → UNUSED 유지 + refund FAILED ──────────────
def test_7_days_payletter_failure():
    order_id, gifticon_id = setup_test_data(days_ago=7)
    try:
        with patch("core.scheduler._payletter_cancel", return_value=False):
            auto_refund_unregistered_gifts()
        g = fetch_gifticon(gifticon_id)
        assert g["status"] == "UNUSED", f"gifticon 상태 유지: {g['status']}"
        refunds = fetch_refunds(order_id)
        assert len(refunds) == 1
        assert refunds[0]["status"] == "FAILED"
    finally:
        teardown_test_data(order_id, gifticon_id)


# ── T04: 30일 경과 → 환불 대상 (cutoff 기준 7일보다 이전) ───────────────────
def test_30_days_processed():
    order_id, gifticon_id = setup_test_data(days_ago=30)
    try:
        with patch("core.scheduler._payletter_cancel", return_value=True):
            auto_refund_unregistered_gifts()
        g = fetch_gifticon(gifticon_id)
        assert g["status"] == "CANCELED"
    finally:
        teardown_test_data(order_id, gifticon_id)


# ── T05: COMPLETED 환불이 이미 존재하면 재처리 안 함 ─────────────────────────
def test_skip_already_refunded():
    order_id, gifticon_id = setup_test_data(days_ago=8)
    # 이미 COMPLETED 환불 삽입
    conn = new_conn()
    cur = conn.cursor()
    cur.execute("SET FOREIGN_KEY_CHECKS=0")
    cur.execute("""
        INSERT INTO refund (order_id, refund_type, amount, status, refunded_at)
        VALUES (%s, 'PURCHASER', 5000, 'COMPLETED', NOW())
    """, (order_id,))
    conn.commit()
    cur.execute("SET FOREIGN_KEY_CHECKS=1")
    conn.commit()
    conn.close()
    try:
        with patch("core.scheduler._payletter_cancel", return_value=True) as mock_cancel:
            auto_refund_unregistered_gifts()
        mock_cancel.assert_not_called()
    finally:
        teardown_test_data(order_id, gifticon_id)


# ── T06: FAILED 재시도 → 성공 시 기존 refund 레코드 COMPLETED ───────────────
def test_retry_failed_refund():
    order_id, gifticon_id = setup_test_data(days_ago=8)
    # FAILED 환불 레코드 선삽입
    conn = new_conn()
    cur = conn.cursor()
    cur.execute("SET FOREIGN_KEY_CHECKS=0")
    cur.execute("""
        INSERT INTO refund (order_id, refund_type, amount, status, refunded_at)
        VALUES (%s, 'PURCHASER', 5000, 'FAILED', NOW())
    """, (order_id,))
    conn.commit()
    cur.execute("SET FOREIGN_KEY_CHECKS=1")
    conn.commit()
    conn.close()
    try:
        with patch("core.scheduler._payletter_cancel", return_value=True):
            auto_refund_unregistered_gifts()
        refunds = fetch_refunds(order_id)
        # 새 레코드 추가 없이 기존 FAILED → COMPLETED
        assert len(refunds) == 1, f"레코드 개수: {len(refunds)}"
        assert refunds[0]["status"] == "COMPLETED"
    finally:
        teardown_test_data(order_id, gifticon_id)


# ── T07: freeze_time으로 경계값 검증 (정확히 7일 전) ─────────────────────────
def test_freeze_time_boundary_exactly_7_days():
    """clock.now() 기준 정확히 7일 전 created_at → cutoff = now-7d → created_at < cutoff 아님 → 미처리"""
    fixed_now = datetime(2026, 1, 20, 12, 0, 0, tzinfo=KST)
    exactly_7d_ago = fixed_now - timedelta(days=7)

    order_id, gifticon_id = setup_test_data(days_ago=0)
    conn = new_conn()
    cur = conn.cursor()
    cur.execute("UPDATE orders SET created_at = %s WHERE id = %s", (exactly_7d_ago, order_id))
    conn.commit()
    conn.close()
    try:
        with clock.freeze_time(fixed_now):
            with patch("core.scheduler._payletter_cancel", return_value=True):
                auto_refund_unregistered_gifts()
        g = fetch_gifticon(gifticon_id)
        # created_at = now - 7d, cutoff = now - 7d → created_at < cutoff 는 False (같음)
        assert g["status"] == "UNUSED", f"정확히 7일 전은 처리 안 됨: {g['status']}"
    finally:
        teardown_test_data(order_id, gifticon_id)


# ── T08: freeze_time으로 경계값 검증 (7일+1초 경과) ─────────────────────────
def test_freeze_time_boundary_just_over_7_days():
    """7일 + 1초 경과 → 처리 대상"""
    fixed_now = datetime(2026, 1, 20, 12, 0, 0, tzinfo=KST)
    just_over_7d = fixed_now - timedelta(days=7, seconds=1)

    order_id, gifticon_id = setup_test_data(days_ago=0)
    conn = new_conn()
    cur = conn.cursor()
    cur.execute("UPDATE orders SET created_at = %s WHERE id = %s", (just_over_7d, order_id))
    conn.commit()
    conn.close()
    try:
        with clock.freeze_time(fixed_now):
            with patch("core.scheduler._payletter_cancel", return_value=True):
                auto_refund_unregistered_gifts()
        g = fetch_gifticon(gifticon_id)
        assert g["status"] == "CANCELED", f"7일+1초 초과 → CANCELED: {g['status']}"
    finally:
        teardown_test_data(order_id, gifticon_id)


# ── T09: receiver_id 있는 경우 → 처리 안 함 ──────────────────────────────────
def test_skip_registered_receiver():
    order_id, gifticon_id = setup_test_data(days_ago=8)
    conn = new_conn()
    cur = conn.cursor()
    cur.execute("UPDATE gifticon SET receiver_id = 99999 WHERE id = %s", (gifticon_id,))
    conn.commit()
    conn.close()
    try:
        with patch("core.scheduler._payletter_cancel", return_value=True) as mock_cancel:
            auto_refund_unregistered_gifts()
        mock_cancel.assert_not_called()
        g = fetch_gifticon(gifticon_id)
        assert g["status"] == "UNUSED"
    finally:
        teardown_test_data(order_id, gifticon_id)


# ── T10: type=1 (일반 구매) → 처리 안 함 ────────────────────────────────────
def test_skip_non_gift_type():
    order_id, gifticon_id = setup_test_data(days_ago=8)
    conn = new_conn()
    cur = conn.cursor()
    cur.execute("UPDATE gifticon SET type = 1 WHERE id = %s", (gifticon_id,))
    conn.commit()
    conn.close()
    try:
        with patch("core.scheduler._payletter_cancel", return_value=True) as mock_cancel:
            auto_refund_unregistered_gifts()
        mock_cancel.assert_not_called()
        g = fetch_gifticon(gifticon_id)
        assert g["status"] == "UNUSED"
    finally:
        teardown_test_data(order_id, gifticon_id)


# ── T11: ENV=test 환경에서 1분 interval 등록 확인 ────────────────────────────
def test_scheduler_interval_in_test_env():
    os.environ["ENV"] = "test"
    try:
        from core.scheduler import create_scheduler
        sched = create_scheduler()
        job = sched.get_job("auto_refund_unregistered_gifts")
        assert job is not None, "auto_refund_unregistered_gifts 잡 등록 필요"
        trigger_type = type(job.trigger).__name__
        assert trigger_type == "IntervalTrigger", f"trigger type: {trigger_type}"
        try:
            sched.shutdown(wait=False)
        except Exception:
            pass
    finally:
        os.environ["ENV"] = "dev"


# ── 실행 ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("GNB-173: 미등록 선물 기프티콘 7일 자동 환불 배치 테스트")
    print("=" * 60)

    run("T01: 6일 경과 → 환불 대상 아님", test_not_yet_7_days)
    run("T02: 7일 경과 + 페이레터 성공 → CANCELED+REFUNDED", test_7_days_payletter_success)
    run("T03: 7일 경과 + 페이레터 실패 → UNUSED 유지+FAILED", test_7_days_payletter_failure)
    run("T04: 30일 경과 → 처리 대상", test_30_days_processed)
    run("T05: COMPLETED 환불 존재 → 재처리 안 함", test_skip_already_refunded)
    run("T06: FAILED 재시도 → 기존 레코드 COMPLETED", test_retry_failed_refund)
    run("T07: freeze_time 경계값 정확히 7일 → 미처리", test_freeze_time_boundary_exactly_7_days)
    run("T08: freeze_time 경계값 7일+1초 → 처리", test_freeze_time_boundary_just_over_7_days)
    run("T09: receiver_id 있는 경우 → 미처리", test_skip_registered_receiver)
    run("T10: type=1 일반 구매 → 미처리", test_skip_non_gift_type)
    run("T11: ENV=test 1분 interval 등록 확인", test_scheduler_interval_in_test_env)

    print("=" * 60)
    passed = sum(1 for ok, _ in results if ok)
    print(f"결과: {passed}/{len(results)} 통과")
    if passed < len(results):
        print("실패:")
        for ok, name in results:
            if not ok:
                print(f"  - {name}")
        sys.exit(1)
