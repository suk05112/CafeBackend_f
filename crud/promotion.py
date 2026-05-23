"""
Promotion CRUD 로직
"""
import pymysql
from typing import List, Dict, Optional
from datetime import date, datetime, timedelta

from db.session import get_db_connection, close_db_connection


def create_fee_promotion(store_id: int, promo_fee_rate: float, start_date: date, end_date: date) -> int:
    """수수료 프로모션 생성"""
    connection = get_db_connection()
    cursor = connection.cursor()
    
    try:
        # 기간 검증: 시작일이 종료일보다 이전이어야 함
        if start_date >= end_date:
            raise ValueError("시작일은 종료일보다 이전이어야 합니다.")
        
        # 기간 검증: 최대 30일
        if (end_date - start_date).days > 30:
            raise ValueError("프로모션 기간은 최대 30일입니다.")
        
        query = """
            INSERT INTO fee_promotions (store_id, promo_fee_rate, start_date, end_date, is_active)
            VALUES (%s, %s, %s, %s, TRUE)
        """
        cursor.execute(query, (store_id, promo_fee_rate, start_date, end_date))
        connection.commit()
        return cursor.lastrowid
    except Exception as e:
        connection.rollback()
        raise e
    finally:
        cursor.close()
        connection.close()


def get_fee_promotions_by_store(store_id: int) -> List[Dict]:
    """매장별 프로모션 리스트 조회"""
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        cursor.execute("""
            SELECT 
                promo_id,
                store_id,
                promo_fee_rate,
                start_date,
                end_date,
                is_active,
                created_at,
                updated_at
            FROM fee_promotions
            WHERE store_id = %s
            ORDER BY start_date DESC
        """, (store_id,))
        
        promotions = cursor.fetchall()
        result = []
        
        for promo in promotions:
            result.append({
                'promo_id': promo['promo_id'],
                'store_id': promo['store_id'],
                'promo_fee_rate': float(promo['promo_fee_rate']),
                'start_date': promo['start_date'].isoformat() if promo['start_date'] else None,
                'end_date': promo['end_date'].isoformat() if promo['end_date'] else None,
                'is_active': bool(promo['is_active']),
                'created_at': promo['created_at'].isoformat() if promo.get('created_at') else None,
                'updated_at': promo['updated_at'].isoformat() if promo.get('updated_at') else None
            })
        
        return result
    finally:
        cursor.close()
        connection.close()


def get_active_fee_promotion(store_id: int, target_date: date = None) -> Optional[Dict]:
    """매장의 활성 프로모션 조회 (특정 날짜 기준)"""
    if target_date is None:
        target_date = date.today()
    
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        cursor.execute("""
            SELECT 
                promo_id,
                store_id,
                promo_fee_rate,
                start_date,
                end_date
            FROM fee_promotions
            WHERE store_id = %s
            AND is_active = TRUE
            AND start_date <= %s
            AND end_date >= %s
            ORDER BY start_date DESC
            LIMIT 1
        """, (store_id, target_date, target_date))
        
        promo = cursor.fetchone()
        
        if promo:
            return {
                'promo_id': promo['promo_id'],
                'store_id': promo['store_id'],
                'promo_fee_rate': float(promo['promo_fee_rate']),
                'start_date': promo['start_date'].isoformat() if promo['start_date'] else None,
                'end_date': promo['end_date'].isoformat() if promo['end_date'] else None
            }
        
        return None
    finally:
        cursor.close()
        connection.close()


def get_fee_info_for_order(store_id: int, order_date: date) -> dict:
    """구매 시점 기준 수수료 정보 조회

    Returns:
        {
            'base_fee_rate': float,       # 플랫폼 기본 수수료율
            'applied_fee_rate': float,    # 최종 적용 수수료율 (프로모션 적용 후)
            'applied_promo_id': int|None, # 적용된 프로모션 ID (없으면 None)
        }
    """
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)

    try:
        # 1. 플랫폼 기본 수수료율 조회
        cursor.execute("SELECT base_fee_rate FROM platform_config WHERE config_id = 1")
        config = cursor.fetchone()
        base_fee_rate = float(config['base_fee_rate']) if config else 3.00

        # 2. 구매일 기준 활성 프로모션 조회 (구매일이 프로모션 기간 내에 있는 것)
        cursor.execute("""
            SELECT promo_id, promo_fee_rate
            FROM fee_promotions
            WHERE store_id = %s
            AND is_active = TRUE
            AND start_date <= %s
            AND end_date >= %s
            ORDER BY start_date ASC
            LIMIT 1
        """, (store_id, order_date, order_date))

        promo = cursor.fetchone()

        if promo:
            return {
                'base_fee_rate': base_fee_rate,
                'applied_fee_rate': float(promo['promo_fee_rate']),
                'applied_promo_id': int(promo['promo_id']),
            }

        return {
            'base_fee_rate': base_fee_rate,
            'applied_fee_rate': base_fee_rate,
            'applied_promo_id': None,
        }
    finally:
        cursor.close()
        connection.close()


def update_fee_promotion(promo_id: int, promo_fee_rate: Optional[float] = None, 
                        start_date: Optional[date] = None, end_date: Optional[date] = None,
                        is_active: Optional[bool] = None) -> bool:
    """프로모션 수정"""
    connection = get_db_connection()
    cursor = connection.cursor()
    
    try:
        updates = []
        params = []
        
        if promo_fee_rate is not None:
            updates.append("promo_fee_rate = %s")
            params.append(promo_fee_rate)
        
        if start_date is not None:
            updates.append("start_date = %s")
            params.append(start_date)
        
        if end_date is not None:
            updates.append("end_date = %s")
            params.append(end_date)
        
        if is_active is not None:
            updates.append("is_active = %s")
            params.append(int(is_active))
        
        if not updates:
            return False
        
        updates.append("updated_at = NOW()")
        params.append(promo_id)
        
        query = f"UPDATE fee_promotions SET {', '.join(updates)} WHERE promo_id = %s"
        cursor.execute(query, params)
        connection.commit()
        return cursor.rowcount > 0
    except Exception as e:
        connection.rollback()
        raise e
    finally:
        cursor.close()
        connection.close()


def delete_fee_promotion(promo_id: int) -> bool:
    """프로모션 삭제"""
    connection = get_db_connection()
    cursor = connection.cursor()
    
    try:
        cursor.execute("DELETE FROM fee_promotions WHERE promo_id = %s", (promo_id,))
        connection.commit()
        return cursor.rowcount > 0
    except Exception as e:
        connection.rollback()
        raise e
    finally:
        cursor.close()
        connection.close()
