"""
Settlement Cycle CRUD 로직
"""
import pymysql
import holidays
from typing import List, Dict, Optional
from datetime import date, datetime, timedelta

from db.session import get_db_connection, close_db_connection


def get_settlement_cycles(
    status: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> List[Dict]:
    """정산 주기 리스트 조회 (매장 수 포함, 최신순)"""
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)

    try:
        conditions = []
        params = []

        if status:
            conditions.append("sc.status = %s")
            params.append(status)
        if start_date:
            conditions.append("sc.period_end_date >= %s")
            params.append(start_date)
        if end_date:
            conditions.append("sc.period_start_date <= %s")
            params.append(end_date)

        where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        query = f"""
            SELECT
                sc.cycle_id,
                sc.period_start_date,
                sc.period_end_date,
                sc.payout_date,
                sc.status,
                COUNT(s.settlement_id) AS store_count
            FROM settlement_cycles sc
            LEFT JOIN settlement s ON sc.cycle_id = s.cycle_id
            {where_clause}
            GROUP BY sc.cycle_id
            ORDER BY sc.period_start_date DESC
        """
        cursor.execute(query, params)

        cycles = cursor.fetchall()
        result = []

        for cycle in cycles:
            result.append({
                'cycle_id': cycle['cycle_id'],
                'period_start_date': cycle['period_start_date'].isoformat() if cycle['period_start_date'] else None,
                'period_end_date': cycle['period_end_date'].isoformat() if cycle['period_end_date'] else None,
                'payout_date': cycle['payout_date'].isoformat() if cycle['payout_date'] else None,
                'status': cycle['status'],
                'store_count': int(cycle['store_count'] or 0),
            })

        return result
    finally:
        cursor.close()
        close_db_connection(connection)


def get_settlement_cycle_by_id(cycle_id: int) -> Optional[Dict]:
    """정산 주기 상세 조회"""
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        cursor.execute("""
            SELECT 
                cycle_id,
                period_start_date,
                period_end_date,
                payout_date,
                status
            FROM settlement_cycles
            WHERE cycle_id = %s
        """, (cycle_id,))
        
        cycle = cursor.fetchone()
        
        if cycle:
            return {
                'cycle_id': cycle['cycle_id'],
                'period_start_date': cycle['period_start_date'].isoformat() if cycle['period_start_date'] else None,
                'period_end_date': cycle['period_end_date'].isoformat() if cycle['period_end_date'] else None,
                'payout_date': cycle['payout_date'].isoformat() if cycle['payout_date'] else None,
                'status': cycle['status']
            }
        
        return None
    finally:
        cursor.close()
        close_db_connection(connection)


def is_business_day(target_date: date) -> bool:
    """영업일 여부 확인 (토요일, 일요일, 대한민국 공휴일 제외)"""
    # 0 = 월요일, 6 = 일요일
    if target_date.weekday() >= 5:
        return False
    kr_holidays = holidays.KR(years=target_date.year)
    return target_date not in kr_holidays


def get_next_business_day(target_date: date) -> date:
    """다음 영업일 반환"""
    next_day = target_date + timedelta(days=1)
    while not is_business_day(next_day):
        next_day += timedelta(days=1)
    return next_day


def get_next_tuesday(target_date: date) -> date:
    """target_date 이후(포함) 가장 가까운 화요일 반환"""
    # 0=월, 1=화, 2=수, 3=목, 4=금, 5=토, 6=일
    days_until_tuesday = (1 - target_date.weekday()) % 7
    return target_date + timedelta(days=days_until_tuesday)


def generate_settlement_cycles(start_date: date, end_date: date) -> int:
    """정산 주기 데이터 생성 (일~토 7일 주기)

    Args:
        start_date: 생성 시작 날짜 (해당 주의 일요일로 맞춤)
        end_date: 생성 종료 날짜

    Returns:
        생성된 주기 개수
    """
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        # start_date를 해당 주 일요일로 맞춤 (Python weekday: 0=월 ... 6=일)
        days_since_sunday = (start_date.weekday() + 1) % 7
        current_sunday = start_date - timedelta(days=days_since_sunday)


        created_count = 0

        while current_sunday <= end_date:
            period_start = current_sunday          # 일요일
            period_end = current_sunday + timedelta(days=6)  # 토요일

            # payout_date: 종료일(토) 기준 3주 후 화요일 (공휴일이면 다음 영업일)
            three_weeks_later = period_end + timedelta(weeks=3)
            payout_date = get_next_tuesday(three_weeks_later)
            if not is_business_day(payout_date):
                payout_date = get_next_business_day(payout_date - timedelta(days=1))

            # 중복 확인
            cursor.execute("""
                SELECT cycle_id FROM settlement_cycles
                WHERE period_start_date = %s AND period_end_date = %s
            """, (period_start, period_end))

            if cursor.fetchone():
                current_sunday += timedelta(weeks=1)
                continue

            cursor.execute("""
                INSERT INTO settlement_cycles (
                    period_start_date, period_end_date, payout_date, status
                ) VALUES (%s, %s, %s, 'OPEN')
            """, (period_start, period_end, payout_date))

            created_count += 1
            current_sunday += timedelta(weeks=1)

        connection.commit()
        return created_count

    except Exception as e:
        connection.rollback()
        raise e
    finally:
        cursor.close()
        close_db_connection(connection)


def close_settlement_cycle(cycle_id: int) -> bool:
    """정산 주기 마감"""
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute("""
            UPDATE settlement_cycles
            SET status = 'CLOSED'
            WHERE cycle_id = %s
        """, (cycle_id,))

        connection.commit()
        return cursor.rowcount > 0
    except Exception as e:
        connection.rollback()
        raise e
    finally:
        cursor.close()
        close_db_connection(connection)


def update_settlement_cycle_status(cycle_id: int, new_status: str) -> Optional[str]:
    """정산 주기 상태 변경. 변경 후 새 status 반환, 없으면 None."""
    if new_status not in ('OPEN', 'CLOSED'):
        raise ValueError(f"Invalid status: {new_status}")
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            "UPDATE settlement_cycles SET status = %s WHERE cycle_id = %s",
            (new_status, cycle_id),
        )
        connection.commit()
        if cursor.rowcount == 0:
            return None
        return new_status
    except Exception as e:
        connection.rollback()
        raise e
    finally:
        cursor.close()
        close_db_connection(connection)
