#!/usr/bin/env python3
"""
GNB-200: 대시보드 신규 매장 집계 KST 자정 기준 검증 테스트

배경:
    DB(RDS) 세션 타임존은 Asia/Seoul(KST)이지만, 애플리케이션 서버(EC2)는
    UTC로 동작한다. crud/admin.py의 get_dashboard_statistics()가
    datetime.now().date()(UTC 기준)로 "오늘"을 계산해 store.created_at
    (KST 기준 저장값)과 비교하면서, KST 자정~09:00 사이 생성된 store가
    "어제"로 밀려 당일 집계에서 누락되던 버그를 재현/회귀 방지.

실행 방법:
    cd /home/ubuntu/CafeBackend
    ENV=dev python3 tests/test_dashboard_kst_boundary.py

사전 조건:
    - dev DB 접속 가능 상태
    - DB 세션 타임존이 Asia/Seoul임 (확인됨: 2026-07-21 EC2 SSH 점검)

테스트 전략:
    - clock.freeze_time()으로 KST 특정 시각 고정
    - store.created_at을 KST 벽시계 값으로 직접 INSERT
      (DB 세션이 KST이므로 naive datetime을 그대로 저장하면 KST 벽시계와 일치)
    - get_dashboard_statistics()를 호출해 new_stores_today에 포함되는지 검증
"""
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["ENV"] = "dev"

import pymysql
from core.config import settings
from core import clock
from crud import admin as admin_crud

KST = clock.KST


def new_conn():
    return pymysql.connect(
        host=settings.db_host, user=settings.db_user,
        password=settings.db_password, database="cafeplatform_dev",
        port=settings.db_port, charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )


def insert_store(created_at_kst_naive: datetime) -> int:
    """created_at을 명시적으로 지정해 store 1건 삽입. store id 반환."""
    conn = new_conn()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO store (owner_id, store_name, store_address, inspection_status, created_at)
           VALUES (99999, '테스트매장-GNB200', '테스트주소', 'PENDING', %s)""",
        (created_at_kst_naive,)
    )
    store_id = cur.lastrowid
    conn.commit()
    cur.close(); conn.close()
    return store_id


def delete_store(store_id: int):
    conn = new_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM store WHERE id = %s", (store_id,))
    conn.commit()
    cur.close(); conn.close()


def count_stores_created_between(start: datetime, end: datetime) -> int:
    """DB 직접 조회로 특정 구간에 생성된 store 수 확인 (기존 데이터 간섭 배제용 보조 검증)"""
    conn = new_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) AS cnt FROM store WHERE created_at >= %s AND created_at < %s",
        (start, end)
    )
    cnt = cur.fetchone()["cnt"]
    cur.close(); conn.close()
    return cnt


def test_store_created_at_kst_midnight_counted_today():
    """KST 자정 5분 후 생성된 매장이 '오늘' 신규 매장으로 집계되는지 검증
    (수정 전에는 datetime.now()가 UTC를 반환해 이 케이스가 전날로 잘못 집계됨)"""
    fixed_now_kst = datetime(2026, 3, 15, 0, 5, 0, tzinfo=KST)
    created_at_naive = fixed_now_kst.replace(tzinfo=None)

    store_id = insert_store(created_at_naive)
    conn = new_conn()
    try:
        with clock.freeze_time(fixed_now_kst):
            result = admin_crud.get_dashboard_statistics(conn)
        day_start = datetime(2026, 3, 15, 0, 0, 0)
        day_end = day_start + timedelta(days=1)
        direct_count = count_stores_created_between(day_start, day_end)
        assert direct_count >= 1, "테스트 데이터가 실제로 오늘 구간에 존재해야 함"
        assert result["new_stores_today"] >= 1, (
            f"KST 자정 직후 생성된 매장이 '오늘' 집계에서 누락됨: {result['new_stores_today']}"
        )
    finally:
        conn.close()
        delete_store(store_id)


def test_store_created_at_kst_8am_counted_today():
    """KST 08:00 생성 매장도 '오늘' 집계에 포함 (버그 시나리오의 핵심 구간: 자정~9시)"""
    fixed_now_kst = datetime(2026, 3, 15, 12, 0, 0, tzinfo=KST)
    created_time = datetime(2026, 3, 15, 8, 0, 0, tzinfo=KST)
    created_at_naive = created_time.replace(tzinfo=None)

    store_id = insert_store(created_at_naive)
    conn = new_conn()
    try:
        with clock.freeze_time(fixed_now_kst):
            result = admin_crud.get_dashboard_statistics(conn)
        assert result["new_stores_today"] >= 1, (
            f"KST 08:00 생성된 매장이 '오늘' 집계에서 누락됨: {result['new_stores_today']}"
        )
    finally:
        conn.close()
        delete_store(store_id)


def test_store_created_at_yesterday_not_counted_today():
    """KST 기준 어제 23:59 생성 매장은 '오늘' 구간(직접 COUNT)에 포함되면 안 됨"""
    created_time = datetime(2026, 3, 14, 23, 59, 0, tzinfo=KST)
    created_at_naive = created_time.replace(tzinfo=None)

    store_id = insert_store(created_at_naive)
    try:
        day_start = datetime(2026, 3, 15, 0, 0, 0)
        day_end = day_start + timedelta(days=1)
        conn = new_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) AS cnt FROM store WHERE id = %s AND created_at >= %s AND created_at < %s",
            (store_id, day_start, day_end)
        )
        cnt = cur.fetchone()["cnt"]
        cur.close(); conn.close()
        assert cnt == 0, "어제 23:59 생성 매장이 오늘 구간에 잘못 포함됨"
    finally:
        delete_store(store_id)


if __name__ == "__main__":
    tests = [
        test_store_created_at_kst_midnight_counted_today,
        test_store_created_at_kst_8am_counted_today,
        test_store_created_at_yesterday_not_counted_today,
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
