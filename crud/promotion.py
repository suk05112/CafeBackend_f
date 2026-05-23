"""
Promotion CRUD 로직
"""
import pymysql
from typing import List, Dict, Optional
from datetime import date, datetime, timedelta

from db.session import get_db_connection, close_db_connection


def create_fee_promotion(store_ids: List[int], promo_fee_rate: float, start_date: date, end_date: date) -> int:
    """수수료 프로모션 생성 (복수 매장 적용 가능)"""
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        if start_date >= end_date:
            raise ValueError("시작일은 종료일보다 이전이어야 합니다.")

        if (end_date - start_date).days > 30:
            raise ValueError("프로모션 기간은 최대 30일입니다.")

        cursor.execute(
            "INSERT INTO fee_promotions (promo_fee_rate, start_date, end_date, is_active) VALUES (%s, %s, %s, TRUE)",
            (promo_fee_rate, start_date, end_date)
        )
        promo_id = cursor.lastrowid

        cursor.executemany(
            "INSERT INTO fee_promotion_stores (promo_id, store_id) VALUES (%s, %s)",
            [(promo_id, sid) for sid in store_ids]
        )

        connection.commit()
        return promo_id
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
                fp.promo_id,
                fp.promo_fee_rate,
                fp.start_date,
                fp.end_date,
                fp.is_active,
                fp.created_at,
                fp.updated_at
            FROM fee_promotions fp
            JOIN fee_promotion_stores fps ON fp.promo_id = fps.promo_id
            WHERE fps.store_id = %s
            ORDER BY fp.start_date DESC
        """, (store_id,))

        result = []
        for promo in cursor.fetchall():
            result.append({
                'promo_id': promo['promo_id'],
                'store_id': store_id,
                'promo_fee_rate': float(promo['promo_fee_rate']),
                'start_date': promo['start_date'].isoformat() if promo['start_date'] else None,
                'end_date': promo['end_date'].isoformat() if promo['end_date'] else None,
                'is_active': bool(promo['is_active']),
                'created_at': promo['created_at'].isoformat() if promo.get('created_at') else None,
                'updated_at': promo['updated_at'].isoformat() if promo.get('updated_at') else None,
            })
        return result
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
        cursor.execute("SELECT base_fee_rate FROM platform_config WHERE config_id = 1")
        config = cursor.fetchone()
        base_fee_rate = float(config['base_fee_rate']) if config else 3.00

        cursor.execute("""
            SELECT fp.promo_id, fp.promo_fee_rate
            FROM fee_promotions fp
            JOIN fee_promotion_stores fps ON fp.promo_id = fps.promo_id
            WHERE fps.store_id = %s
              AND fp.is_active = TRUE
              AND fp.start_date <= %s
              AND fp.end_date >= %s
            ORDER BY fp.start_date ASC
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

        cursor.execute(f"UPDATE fee_promotions SET {', '.join(updates)} WHERE promo_id = %s", params)
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
