#!/usr/bin/env python3
"""
GNB-201: 대시보드 "정산 주기별 매출 이력"에 오늘 포함 진행중 주기 표시 검증

배경:
    get_dashboard_settlement_cycles()에 period_end_date <= today 필터가 있어
    오늘 날짜를 포함하거나 그 이후에 끝나는(=아직 진행 중인) 정산 주기가
    리스트에서 누락되던 문제. 정산이 아직 생성되지 않은 주기도(관련 데이터는
    0으로) 화면에 노출되어야 한다는 요구사항에 따라 필터 제거.

실행 방법:
    cd /home/ubuntu/CafeBackend
    ENV=dev python3 tests/test_dashboard_settlement_cycles.py

사전 조건:
    - dev DB 접속 가능 상태

테스트 전략:
    - 오늘을 포함하는(미래에 끝나는) settlement_cycles row를 직접 INSERT
    - get_dashboard_settlement_cycles()가 이 주기를 결과에 포함하는지 검증
    - 정산(settlement) 데이터가 없어도(0으로) 포함되는지 함께 확인
"""
import sys
import os
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["ENV"] = "dev"

import pymysql
from core.config import settings
from crud import stats as stats_crud


def new_conn():
    return pymysql.connect(
        host=settings.db_host, user=settings.db_user,
        password=settings.db_password, database="cafeplatform_dev",
        port=settings.db_port, charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )


def insert_cycle(period_start: date, period_end: date, payout_date: date, status: str = "OPEN") -> int:
    conn = new_conn()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO settlement_cycles (period_start_date, period_end_date, payout_date, status)
           VALUES (%s, %s, %s, %s)""",
        (period_start, period_end, payout_date, status)
    )
    cycle_id = cur.lastrowid
    conn.commit()
    cur.close(); conn.close()
    return cycle_id


def delete_cycle(cycle_id: int):
    conn = new_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM settlement WHERE cycle_id = %s", (cycle_id,))
    cur.execute("DELETE FROM settlement_cycles WHERE cycle_id = %s", (cycle_id,))
    conn.commit()
    cur.close(); conn.close()


def find_cycle_across_pages(cycle_id: int, size: int = 100, max_pages: int = 10):
    """기존에 미리 생성된 주기가 많아 대상 cycle이 뒤 페이지에 있을 수 있으므로
    여러 페이지를 순회하며 찾는다."""
    for page in range(1, max_pages + 1):
        result = stats_crud.get_dashboard_settlement_cycles(page=page, size=size)
        matched = [item for item in result["items"] if item["cycle_id"] == cycle_id]
        if matched:
            return matched[0]
        if page * size >= result["total"]:
            break
    return None


def test_today_included_cycle_appears():
    """오늘을 포함하는(정산 미생성) 진행 중 주기가 결과에 포함되는지 검증"""
    today = date.today()
    period_start = today - timedelta(days=2)
    period_end = today + timedelta(days=4)
    payout_date = period_end + timedelta(days=14)

    cycle_id = insert_cycle(period_start, period_end, payout_date)
    try:
        matched = find_cycle_across_pages(cycle_id)
        assert matched, f"오늘 포함 진행중 주기(cycle_id={cycle_id})가 결과에서 누락됨"
        assert matched["total_settlement_amount"] == 0, "정산 미생성 주기는 금액이 0이어야 함"
    finally:
        delete_cycle(cycle_id)


def test_future_only_cycle_appears():
    """완전히 미래(아직 시작도 안 한)인 주기도 결과에 포함되는지 검증
    (기존 데이터에 이미 2027년까지 다수 주기가 있으므로, 그보다 더 먼 미래로 생성해
    period_start_date DESC 정렬 시 가장 먼저 나오는지로 검증)"""
    today = date.today()
    period_start = today + timedelta(days=365 * 5)
    period_end = period_start + timedelta(days=6)
    payout_date = period_end + timedelta(days=14)

    cycle_id = insert_cycle(period_start, period_end, payout_date)
    try:
        result = stats_crud.get_dashboard_settlement_cycles(page=1, size=1)
        assert result["items"] and result["items"][0]["cycle_id"] == cycle_id, (
            f"가장 먼 미래 주기(cycle_id={cycle_id})가 1페이지 최상단에 없음: {result['items']}"
        )
    finally:
        delete_cycle(cycle_id)


if __name__ == "__main__":
    tests = [
        test_today_included_cycle_appears,
        test_future_only_cycle_appears,
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
