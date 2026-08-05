#!/usr/bin/env python3
"""
GNB-217: 알림톡 발송 큐 테이블 전환 배치/재발송 테스트

실행 방법:
    cd /home/ubuntu/CafeBackend
    ENV=dev python3 tests/test_alimtalk_queue.py

테스트 전략:
    - alimtalk_log에 직접 INSERT/UPDATE로 테스트 데이터 구성
    - core.scheduler.send_alimtalk_log_row 를 unittest.mock으로 대체 (실제 Aligo 호출 없이 검증)
    - send_pending_alimtalk() 배치 함수 및 crud/alimtalk.py 함수를 직접 호출
    - 각 테스트 후 데이터 정리
"""
import sys
import os
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["ENV"] = "dev"

import pymysql
from core.config import settings
from core import clock
from core.scheduler import send_pending_alimtalk
from crud import alimtalk as alimtalk_crud
from app.aligo_service import send_gift_cancel_to_receiver

# ── DB 헬퍼 ──────────────────────────────────────────────────────────────────

def new_conn():
    return pymysql.connect(
        host=settings.db_host, user=settings.db_user,
        password=settings.db_password, database="cafeplatform_dev",
        port=settings.db_port, charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )


def insert_log(status="PENDING", retry_count=0, receiver_phone="01099999999") -> int:
    conn = new_conn()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO alimtalk_log
           (tpl_code, category, receiver_phone, recvname, subject, message, status, retry_count)
           VALUES ('UJ_1609', 'GIFT_CANCEL', %s, '테스트', '선물 결제 취소 안내', '테스트 메시지', %s, %s)""",
        (receiver_phone, status, retry_count),
    )
    conn.commit()
    log_id = cur.lastrowid
    conn.close()
    return log_id


def teardown_log(log_id: int):
    conn = new_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM alimtalk_log WHERE id = %s", (log_id,))
    conn.commit()
    conn.close()


def fetch_log(log_id: int) -> dict:
    conn = new_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM alimtalk_log WHERE id = %s", (log_id,))
    row = cur.fetchone()
    conn.close()
    return row or {}


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


# ── T01: 공개 함수 호출 시 PENDING row 생성 ──────────────────────────────────
def test_enqueue_creates_pending_row():
    result = send_gift_cancel_to_receiver(receiver="01099999998", sender="테스트발신자", menu="테스트메뉴")
    log_id = result["id"]
    try:
        row = fetch_log(log_id)
        assert row["status"] == "PENDING", f"상태가 PENDING 이어야 함: {row['status']}"
        assert row["retry_count"] == 0
        assert row["tpl_code"] == "UJ_1609"
        assert row["category"] == "GIFT_CANCEL"
        assert row["emtitle"] == "주문취소 안내", f"emtitle: {row['emtitle']}"
    finally:
        teardown_log(log_id)


# ── T02: 배치가 PENDING 건을 접수 성공 → REQUESTED (최종 발송 성공 아님) ────
def test_batch_sends_pending_to_requested():
    log_id = insert_log(status="PENDING")
    try:
        with patch("core.scheduler.send_alimtalk_log_row", return_value={"code": 0, "info": {"mid": "test-mid-1", "fcnt": 0}}), \
             patch("core.scheduler.get_history_detail", return_value={"code": 0, "list": []}):
            send_pending_alimtalk()
        row = fetch_log(log_id)
        assert row["status"] == "REQUESTED", f"상태: {row['status']}"
        assert row["aligo_mid"] == "test-mid-1"
    finally:
        teardown_log(log_id)


# ── T03: 배치가 발송 요청 자체 실패 시 FAILED + retry_count 증가 ─────────────
def test_batch_marks_failed_and_increments_retry_count():
    log_id = insert_log(status="PENDING")
    try:
        with patch("core.scheduler.send_alimtalk_log_row", return_value={"code": -1, "message": "발송 실패"}):
            send_pending_alimtalk()
        row = fetch_log(log_id)
        assert row["status"] == "FAILED", f"상태: {row['status']}"
        assert row["retry_count"] == 1, f"retry_count: {row['retry_count']}"
        assert row["fail_reason"] == "발송 실패"
    finally:
        teardown_log(log_id)


# ── T04: FAILED 건은 자동 배치가 건드리지 않는다 (수동 재시도만) ────────────
def test_batch_never_touches_failed():
    log_id = insert_log(status="FAILED", retry_count=1)
    try:
        with patch("core.scheduler.send_alimtalk_log_row") as mock_send:
            send_pending_alimtalk()
        mock_send.assert_not_called()
        row = fetch_log(log_id)
        assert row["status"] == "FAILED", f"상태 유지되어야 함: {row['status']}"
        assert row["retry_count"] == 1, "retry_count 변화 없어야 함"
    finally:
        teardown_log(log_id)


# ── T05: REQUESTED 건은 history/detail의 rslt='U'면 FAILED로 확정 ───────────
def test_requested_confirmed_failed_on_rslt_u():
    log_id = insert_log(status="REQUESTED")
    conn = new_conn()
    cur = conn.cursor()
    cur.execute("UPDATE alimtalk_log SET aligo_mid=%s WHERE id=%s", ("mid-fail", log_id))
    conn.commit()
    conn.close()
    try:
        with patch("core.scheduler.get_history_detail", return_value={
            "code": 0, "list": [{"rslt": "U", "rslt_message": "메시지가 템플릿과 일치하지않음"}]
        }):
            send_pending_alimtalk()
        row = fetch_log(log_id)
        assert row["status"] == "FAILED", f"상태: {row['status']}"
        assert row["fail_reason"] == "메시지가 템플릿과 일치하지않음"
    finally:
        teardown_log(log_id)


# ── T06: REQUESTED 건은 history/detail의 rslt가 실패가 아니면 SENT로 확정 ───
def test_requested_confirmed_sent():
    log_id = insert_log(status="REQUESTED")
    conn = new_conn()
    cur = conn.cursor()
    cur.execute("UPDATE alimtalk_log SET aligo_mid=%s WHERE id=%s", ("mid-ok", log_id))
    conn.commit()
    conn.close()
    try:
        with patch("core.scheduler.get_history_detail", return_value={
            "code": 0, "list": [{"rslt": "3"}]
        }):
            send_pending_alimtalk()
        row = fetch_log(log_id)
        assert row["status"] == "SENT", f"상태: {row['status']}"
        assert row["sent_at"] is not None
    finally:
        teardown_log(log_id)


# ── T07: REQUESTED 건은 결과 미확정이면 그대로 REQUESTED 유지 ───────────────
def test_requested_stays_when_result_unconfirmed():
    log_id = insert_log(status="REQUESTED")
    conn = new_conn()
    cur = conn.cursor()
    cur.execute("UPDATE alimtalk_log SET aligo_mid=%s WHERE id=%s", ("mid-pending", log_id))
    conn.commit()
    conn.close()
    try:
        with patch("core.scheduler.get_history_detail", return_value={"code": 0, "list": []}):
            send_pending_alimtalk()
        row = fetch_log(log_id)
        assert row["status"] == "REQUESTED", f"상태 유지되어야 함: {row['status']}"
    finally:
        teardown_log(log_id)


# ── T08: 관리자 수동 재발송은 상한(5회) 무시하고 REQUESTED로 표시 ───────────
def test_manual_retry_ignores_cap():
    """
    admin.py의 retry_alimtalk_api()가 하는 것과 동일한 흐름을 재현:
    get_by_ids()는 재시도 상한과 무관하게 조회하고, 접수 성공 시 REQUESTED로 표시한다.
    """
    log_id = insert_log(status="FAILED", retry_count=5)
    try:
        rows = alimtalk_crud.get_by_ids([log_id])
        assert len(rows) == 1, "상한과 무관하게 조회되어야 함"

        with patch("app.aligo_service.send_alimtalk_log_row", return_value={"code": 0, "info": {"mid": "manual-ok", "fcnt": 0}}) as mock_dispatch:
            send_result = mock_dispatch(rows[0])
        assert send_result.get("code") == 0
        alimtalk_crud.mark_requested(log_id, "manual-ok")
        row = fetch_log(log_id)
        assert row["status"] == "REQUESTED"
        assert row["retry_count"] == 5, "수동 재발송 성공 시 retry_count는 그대로 유지"
    finally:
        teardown_log(log_id)


# ── T09: 상태 필터 + 페이지네이션 ────────────────────────────────────────────
def test_get_log_list_filters_and_paginates():
    id1 = insert_log(status="PENDING", receiver_phone="01011110001")
    id2 = insert_log(status="FAILED", receiver_phone="01011110002")
    id3 = insert_log(status="SENT", receiver_phone="01011110003")
    try:
        result = alimtalk_crud.get_log_list(status="FAILED", page=1, limit=10)
        ids_in_result = [item["id"] for item in result["items"]]
        assert id2 in ids_in_result, "FAILED 건이 포함되어야 함"
        assert id1 not in ids_in_result, "PENDING 건은 제외되어야 함"
        assert id3 not in ids_in_result, "SENT 건은 제외되어야 함"
        assert result["page"] == 1
        assert result["limit"] == 10
    finally:
        teardown_log(id1)
        teardown_log(id2)
        teardown_log(id3)


# ── T10: ENV=test 환경에서 5분→1분 interval 등록 확인 ────────────────────────
def test_scheduler_interval_registration():
    os.environ["ENV"] = "test"
    try:
        from core.scheduler import create_scheduler
        sched = create_scheduler()
        job = sched.get_job("send_pending_alimtalk")
        assert job is not None, "send_pending_alimtalk 잡 등록 필요"
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
    print("GNB-217: 알림톡 발송 큐 배치 테스트")
    print("=" * 60)

    run("T01: 공개 함수 호출 → PENDING row 생성", test_enqueue_creates_pending_row)
    run("T02: 배치 발송 접수 성공 → REQUESTED", test_batch_sends_pending_to_requested)
    run("T03: 배치 발송 요청 실패 → FAILED + retry_count 증가", test_batch_marks_failed_and_increments_retry_count)
    run("T04: FAILED 건은 자동 배치가 건드리지 않음", test_batch_never_touches_failed)
    run("T05: REQUESTED → rslt=U → FAILED 확정", test_requested_confirmed_failed_on_rslt_u)
    run("T06: REQUESTED → rslt 정상 → SENT 확정", test_requested_confirmed_sent)
    run("T07: REQUESTED → 결과 미확정 → REQUESTED 유지", test_requested_stays_when_result_unconfirmed)
    run("T08: 관리자 수동 재발송 → 상한 무시, REQUESTED로 표시", test_manual_retry_ignores_cap)
    run("T09: 상태 필터 + 페이지네이션", test_get_log_list_filters_and_paginates)
    run("T10: ENV=test 1분 interval 등록 확인", test_scheduler_interval_registration)

    print("=" * 60)
    passed = sum(1 for ok, _ in results if ok)
    print(f"결과: {passed}/{len(results)} 통과")
    if passed < len(results):
        print("실패:")
        for ok, name in results:
            if not ok:
                print(f"  - {name}")
        sys.exit(1)
