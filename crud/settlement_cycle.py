"""
Settlement Cycle CRUD 로직
"""
import pymysql
from typing import List, Dict, Optional
from datetime import date, datetime, timedelta

from db.session import get_db_connection, close_db_connection


def get_settlement_cycles(status: Optional[str] = None) -> List[Dict]:
    """정산 주기 리스트 조회"""
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        if status:
            query = """
                SELECT 
                    cycle_id,
                    period_start_date,
                    period_end_date,
                    payout_date,
                    status
                FROM settlement_cycles
                WHERE status = %s
                ORDER BY period_start_date ASC
            """
            cursor.execute(query, (status,))
        else:
            query = """
                SELECT 
                    cycle_id,
                    period_start_date,
                    period_end_date,
                    payout_date,
                    status
                FROM settlement_cycles
                ORDER BY period_start_date ASC
            """
            cursor.execute(query)
        
        cycles = cursor.fetchall()
        result = []
        
        for cycle in cycles:
            result.append({
                'cycle_id': cycle['cycle_id'],
                'period_start_date': cycle['period_start_date'].isoformat() if cycle['period_start_date'] else None,
                'period_end_date': cycle['period_end_date'].isoformat() if cycle['period_end_date'] else None,
                'payout_date': cycle['payout_date'].isoformat() if cycle['payout_date'] else None,
                'status': cycle['status']
            })
        
        return result
    finally:
        cursor.close()
        connection.close()


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
        connection.close()


def is_business_day(target_date: date) -> bool:
    """영업일 여부 확인 (토요일, 일요일 제외)"""
    # 0 = 월요일, 6 = 일요일
    weekday = target_date.weekday()
    return weekday < 5  # 월~금만 영업일


def get_next_business_day(target_date: date) -> date:
    """다음 영업일 반환"""
    next_day = target_date + timedelta(days=1)
    while not is_business_day(next_day):
        next_day += timedelta(days=1)
    return next_day


def generate_settlement_cycles(start_date: date, months: int = 12) -> int:
    """정산 주기 데이터 생성 (1년치)
    
    Args:
        start_date: 시작 날짜
        months: 생성할 개월 수 (기본 12개월)
    
    Returns:
        생성된 주기 개수
    """
    connection = get_db_connection()
    cursor = connection.cursor()
    
    try:
        # 정산 주기 설정 (5일)
        cycle_days = 5
        payout_delay_days = 10  # 정산 주기 종료일 + 10일
        
        current_date = start_date
        end_date = start_date + timedelta(days=months * 30)  # 대략적인 종료일
        created_count = 0
        
        while current_date < end_date:
            # 정산 기간: 시작일 ~ 종료일 (5일)
            period_start = current_date
            period_end = current_date + timedelta(days=cycle_days - 1)
            
            # 정산일: 종료일 + 10일 (영업일 기준)
            payout_date = period_end + timedelta(days=payout_delay_days)
            
            # 영업일이 아니면 다음 영업일로 조정
            if not is_business_day(payout_date):
                payout_date = get_next_business_day(payout_date)
            
            # 중복 확인
            cursor.execute("""
                SELECT cycle_id FROM settlement_cycles
                WHERE period_start_date = %s AND period_end_date = %s
            """, (period_start, period_end))
            
            if cursor.fetchone():
                # 이미 존재하면 건너뛰기
                current_date = period_end + timedelta(days=1)
                continue
            
            # 정산 주기 데이터 삽입
            cursor.execute("""
                INSERT INTO settlement_cycles (
                    period_start_date, period_end_date, payout_date, status
                ) VALUES (%s, %s, %s, 'OPEN')
            """, (period_start, period_end, payout_date))
            
            created_count += 1
            
            # 다음 주기 시작일
            current_date = period_end + timedelta(days=1)
        
        connection.commit()
        return created_count
        
    except Exception as e:
        connection.rollback()
        raise e
    finally:
        cursor.close()
        connection.close()


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
        connection.close()
