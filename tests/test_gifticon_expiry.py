#!/usr/bin/env python3
"""
GNB-196: 기프티콘 유효기간 만료 배치 테스트 (자동환불 폐지 이후)

실행 방법:
    cd /home/ubuntu/CafeBackend
    ENV=dev python3 tests/test_gifticon_expiry.py

사전 조건:
    - dev DB 접속 가능 상태

테스트 전략:
    - validity를 과거/현재/미래 날짜로 직접 설정한 테스트 데이터 사용
    - clock.freeze_time()으로 현재 시간 고정
    - expire_gifticons() 배치 함수를 직접 호출 (스케줄러 미경유)
    - 자동환불(페이레터 호출, refund 레코드 생성)이 없음을 검증
    - 각 테스트 후 데이터 원복 (FK_CHECKS 비활성화로 테스트 전용 데이터 관리)
"""
import sys
import os
from datetime import datetime, timedelta, date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["ENV"] = "dev"

import pymysql
from core.config import settings
from core import clock
from core.scheduler import expire_gifticons


# ── DB 헬퍼 ──────────────────────────────────────────────────────────────────

def new_conn():
    return pymysql.connect(
        host=settings.db_host, user=settings.db_user,
        password=settings.db_password, database="cafeplatform_dev",
        port=settings.db_port, charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )


def setup_test_data(validity: date, status: str = "UNUSED") -> tuple[int, int]:
    """FK 비활성화 후 테스트용 order/menu/gifticon 삽입. (order_id, gifticon_id) 반환."""
    conn = new_conn()
    cur = conn.cursor()
    cur.execute("SET FOREIGN_KEY_CHECKS=0")
    # 고정 id INSERT 금지: AUTO_INCREMENT 카운터가 점프해 실제 메뉴 id가 튀는 원인 (GNB-184)
    cur.execute("""
        INSERT INTO menu (store_id, menu_name, price, status)
        VALUES (99999, '테스트메뉴', 5000, 'ACTIVE')
    """)
    menu_id = cur.lastrowid
    cur.execute("""
        INSERT INTO orders (store_id, user_id, payment_key, amount, status, order_no, payment, pgcode)
        VALUES (99999, 99999, 'TEST_FAKE_KEY', 5000, 'COMPLETED', %s, 'card', 'creditcard')
    """, (f"TEST-{validity}-{status}-{os.getpid()}",))
    order_id = cur.lastrowid
    cur.execute("""
        INSERT INTO gifticon (user_id, type, sender, menu_id, store_id, order_id, status, validity, gift_code)
        VALUES (99999, 1, '테스트발신', %s, 99999, %s, %s, %s, %s)
    """, (menu_id, order_id, status, validity, f"TEST-GIFT-{order_id}"))
    gifticon_id = cur.lastrowid
    cur.execute("SET FOREIGN_KEY_CHECKS=1")
    conn.commit()
    cur.close(); conn.close()
    return order_id, gifticon_id


def teardown_test_data(order_id: int, gifticon_id: int):
    conn = new_conn()
    cur = conn.cursor()
    cur.execute("SET FOREIGN_KEY_CHECKS=0")
    cur.execute("DELETE FROM refund WHERE order_id = %s", (order_id,))
    cur.execute("DELETE FROM orders_gifticon WHERE order_id = %s", (order_id,))
    cur.execute("DELETE FROM menu WHERE id = (SELECT menu_id FROM gifticon WHERE id = %s)", (gifticon_id,))
    cur.execute("DELETE FROM gifticon WHERE id = %s", (gifticon_id,))
    cur.execute("DELETE FROM orders WHERE id = %s", (order_id,))
    cur.execute("SET FOREIGN_KEY_CHECKS=1")
    conn.commit()
    cur.close(); conn.close()


def get_state(order_id: int, gifticon_id: int) -> dict:
    conn = new_conn(); cur = conn.cursor()
    cur.execute("SELECT status FROM gifticon WHERE id = %s", (gifticon_id,))
    g = cur.fetchone()
    cur.execute("SELECT COUNT(*) AS cnt FROM refund WHERE order_id = %s", (order_id,))
    r = cur.fetchone()
    cur.close(); conn.close()
    return {
        "gifticon": g["status"] if g else None,
        "refund_count": r["cnt"] if r else 0,
    }


def print_result(name: str, passed: bool, detail: str = ""):
    mark = "✓" if passed else "✗"
    status = "PASS" if passed else "FAIL"
    print(f"  [{mark}] {status}: {name}" + (f" — {detail}" if detail else ""))


# ── 테스트 케이스 ─────────────────────────────────────────────────────────────

def test_not_expired_before_validity():
    """validity가 미래인 기프티콘은 UNUSED 유지."""
    future = (clock.now() + timedelta(days=1)).date()
    order_id, gid = setup_test_data(future)
    try:
        expire_gifticons()
        state = get_state(order_id, gid)
        print_result("validity 미래 → UNUSED 유지", state["gifticon"] == "UNUSED",
                     f"gifticon={state['gifticon']}")
    finally:
        teardown_test_data(order_id, gid)


def test_expired_no_auto_refund():
    """validity 당일 도래 → EXPIRED로 전환되고 refund 레코드는 생성되지 않음."""
    today = clock.now().date()
    order_id, gid = setup_test_data(today)
    try:
        expire_gifticons()
        state = get_state(order_id, gid)
        print_result("validity 당일 → gifticon EXPIRED",
                     state["gifticon"] == "EXPIRED", f"gifticon={state['gifticon']}")
        print_result("자동환불 없음 → refund 레코드 미생성",
                     state["refund_count"] == 0, f"refund_count={state['refund_count']}")
    finally:
        teardown_test_data(order_id, gid)


def test_already_expired_not_retargeted():
    """이미 EXPIRED인 기프티콘은 재대상이 아니며 그대로 유지됨."""
    today = clock.now().date()
    order_id, gid = setup_test_data(today, status="EXPIRED")
    try:
        expire_gifticons()
        state = get_state(order_id, gid)
        print_result("이미 EXPIRED → 재처리 없이 유지",
                     state["gifticon"] == "EXPIRED", f"gifticon={state['gifticon']}")
        print_result("재처리 후에도 refund 레코드 미생성",
                     state["refund_count"] == 0, f"refund_count={state['refund_count']}")
    finally:
        teardown_test_data(order_id, gid)


def test_time_boundary_freeze():
    """freeze_time으로 경계값 검증: 만료일 전날 → 유지, 당일 → 만료."""
    expiry = date(2030, 1, 10)
    order_id, gid = setup_test_data(expiry)
    try:
        # 만료 전날
        with clock.freeze_time(datetime(2030, 1, 9, 23, 59, tzinfo=clock.KST)):
            expire_gifticons()
        state = get_state(order_id, gid)
        print_result("만료일 전날 → UNUSED 유지",
                     state["gifticon"] == "UNUSED", f"gifticon={state['gifticon']}")

        # 만료일 당일
        with clock.freeze_time(datetime(2030, 1, 10, 0, 0, tzinfo=clock.KST)):
            expire_gifticons()
        state = get_state(order_id, gid)
        print_result("만료일 당일 → EXPIRED",
                     state["gifticon"] == "EXPIRED", f"gifticon={state['gifticon']}")
    finally:
        teardown_test_data(order_id, gid)


def test_scheduler_job_registered():
    """ENV=test 환경에서 expire_gifticons 잡이 1분 interval로 등록됨."""
    import os
    from unittest.mock import patch
    from core.scheduler import create_scheduler

    with patch.dict(os.environ, {"ENV": "test"}):
        sched = create_scheduler()

    job = sched.get_job("expire_gifticons")
    trigger_type = type(job.trigger).__name__ if job else "None"
    passed = job is not None and trigger_type == "IntervalTrigger" and job.trigger.interval == timedelta(minutes=1)
    print_result("ENV=test 시 1분 interval 등록", passed,
                 f"trigger={trigger_type}, interval={job.trigger.interval if job else 'N/A'}")
    try:
        sched.shutdown(wait=False)
    except Exception:
        pass


# ── 메인 ─────────────────────────────────────────────────────────────────────

def main():
    print("\n=== GNB-196: 기프티콘 만료 배치 테스트 (자동환불 폐지) ===\n")

    print("1. validity 미래 → 만료 안됨")
    test_not_expired_before_validity()

    print("\n2. validity 당일 → EXPIRED 전환, 자동환불 없음")
    test_expired_no_auto_refund()

    print("\n3. 이미 EXPIRED인 기프티콘은 재대상 아님")
    test_already_expired_not_retargeted()

    print("\n4. freeze_time 경계값 (2030-01-10 만료일)")
    test_time_boundary_freeze()

    print("\n5. 스케줄러 잡 1분 interval 등록 확인")
    test_scheduler_job_registered()

    print("\n=== 완료 ===\n")


if __name__ == "__main__":
    main()
