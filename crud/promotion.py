"""
Promotion CRUD 로직
"""
import pymysql
from typing import List, Dict, Optional
from datetime import date, datetime, timedelta

from db.session import get_db_connection, close_db_connection


PROMO_TYPE_FIXED = 'FIXED_PERIOD'
PROMO_TYPE_PER_STORE = 'PER_STORE_PERIOD'
ALLOWED_PROMO_TYPES = (PROMO_TYPE_FIXED, PROMO_TYPE_PER_STORE)


def create_fee_promotion(
    store_ids: List[int],
    promo_fee_rate: float,
    title: str,
    promo_type: str = PROMO_TYPE_FIXED,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> int:
    """수수료 프로모션 생성

    - FIXED_PERIOD: start_date, end_date 필수. 매장 등록 시 프로모션 기간이 그대로 적용됨.
    - PER_STORE_PERIOD: start_date, end_date는 무시. 매장 등록 시 매장별로 기간을 지정.
    """
    if promo_type not in ALLOWED_PROMO_TYPES:
        raise ValueError(f"promo_type은 {ALLOWED_PROMO_TYPES} 중 하나여야 합니다.")

    if promo_type == PROMO_TYPE_FIXED:
        if not start_date or not end_date:
            raise ValueError("FIXED_PERIOD는 시작일과 종료일이 필수입니다.")
        if start_date >= end_date:
            raise ValueError("시작일은 종료일보다 이전이어야 합니다.")
    else:
        start_date = None
        end_date = None

    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            INSERT INTO fee_promotions
                (title, promo_type, promo_fee_rate, start_date, end_date, is_active, active_store_count)
            VALUES (%s, %s, %s, %s, %s, TRUE, 0)
            """,
            (title, promo_type, promo_fee_rate, start_date, end_date)
        )
        promo_id = cursor.lastrowid

        # 생성 시점에 매장 지정은 FIXED_PERIOD만 지원 (PER_STORE_PERIOD는 개별 apply로만)
        if store_ids and promo_type == PROMO_TYPE_FIXED:
            cursor.executemany(
                """
                INSERT INTO fee_promotion_stores (promo_id, store_id, start_date, end_date)
                VALUES (%s, %s, %s, %s)
                """,
                [(promo_id, sid, start_date, end_date) for sid in store_ids]
            )
            cursor.execute(
                "UPDATE fee_promotions SET active_store_count = %s WHERE promo_id = %s",
                (len(store_ids), promo_id)
            )

        connection.commit()
        return promo_id
    except Exception as e:
        connection.rollback()
        raise e
    finally:
        cursor.close()
        close_db_connection(connection)


def get_all_fee_promotions(active_only: bool = False) -> List[Dict]:
    """전체 프로모션 리스트 조회"""
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)

    try:
        where = "WHERE is_active = TRUE" if active_only else ""
        cursor.execute(f"""
            SELECT
                promo_id,
                title,
                promo_type,
                promo_fee_rate,
                start_date,
                end_date,
                is_active,
                active_store_count,
                created_at
            FROM fee_promotions
            {where}
            ORDER BY created_at DESC
        """)

        result = []
        for promo in cursor.fetchall():
            result.append({
                'promo_id': promo['promo_id'],
                'title': promo['title'],
                'promo_type': promo['promo_type'],
                'promo_fee_rate': float(promo['promo_fee_rate']),
                'start_date': promo['start_date'].isoformat() if promo['start_date'] else None,
                'end_date': promo['end_date'].isoformat() if promo['end_date'] else None,
                'is_active': bool(promo['is_active']),
                'store_count': int(promo['active_store_count']),
                'active_store_count': int(promo['active_store_count']),
                'created_at': promo['created_at'].isoformat() if promo.get('created_at') else None,
            })
        return result
    finally:
        cursor.close()
        close_db_connection(connection)


def get_fee_promotion_detail(promo_id: int) -> Optional[Dict]:
    """프로모션 상세 조회 (적용 매장 목록 포함, 활성 매장만)"""
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)

    try:
        cursor.execute("""
            SELECT
                promo_id, title, promo_type, promo_fee_rate,
                start_date, end_date, is_active, active_store_count, created_at
            FROM fee_promotions
            WHERE promo_id = %s
        """, (promo_id,))
        promo = cursor.fetchone()
        if not promo:
            return None

        cursor.execute("""
            SELECT
                s.id AS store_id,
                s.store_name,
                fps.start_date,
                fps.end_date,
                fps.applied_at
            FROM fee_promotion_stores fps
            JOIN store s ON fps.store_id = s.id
            WHERE fps.promo_id = %s AND fps.removed_at IS NULL
            ORDER BY fps.applied_at DESC
        """, (promo_id,))
        stores = cursor.fetchall()

        return {
            'promo_id': promo['promo_id'],
            'title': promo['title'],
            'promo_type': promo['promo_type'],
            'promo_fee_rate': float(promo['promo_fee_rate']),
            'start_date': promo['start_date'].isoformat() if promo['start_date'] else None,
            'end_date': promo['end_date'].isoformat() if promo['end_date'] else None,
            'is_active': bool(promo['is_active']),
            'active_store_count': int(promo['active_store_count']),
            'created_at': promo['created_at'].isoformat() if promo.get('created_at') else None,
            'stores': [
                {
                    'store_id': s['store_id'],
                    'store_name': s['store_name'],
                    'start_date': s['start_date'].isoformat() if s['start_date'] else None,
                    'end_date': s['end_date'].isoformat() if s['end_date'] else None,
                    'applied_at': s['applied_at'].isoformat() if s['applied_at'] else None,
                }
                for s in stores
            ],
        }
    finally:
        cursor.close()
        close_db_connection(connection)


def get_promotions_by_store(store_id: int) -> List[Dict]:
    """매장별 프로모션 목록 조회 (활성 + 이력, 최신순)"""
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)

    try:
        cursor.execute("""
            SELECT
                fps.id AS mapping_id,
                fp.promo_id,
                fp.title,
                fp.promo_type,
                fp.promo_fee_rate,
                fps.start_date,
                fps.end_date,
                fps.applied_at,
                fps.removed_at
            FROM fee_promotion_stores fps
            JOIN fee_promotions fp ON fps.promo_id = fp.promo_id
            WHERE fps.store_id = %s
            ORDER BY fps.applied_at DESC
        """, (store_id,))

        result = []
        for row in cursor.fetchall():
            result.append({
                'mapping_id': row['mapping_id'],
                'promo_id': row['promo_id'],
                'title': row['title'],
                'promo_type': row['promo_type'],
                'promo_fee_rate': float(row['promo_fee_rate']),
                'start_date': row['start_date'].isoformat() if row['start_date'] else None,
                'end_date': row['end_date'].isoformat() if row['end_date'] else None,
                'applied_at': row['applied_at'].isoformat() if row['applied_at'] else None,
                'removed_at': row['removed_at'].isoformat() if row['removed_at'] else None,
                'status': 'active' if row['removed_at'] is None else 'removed',
            })
        return result
    finally:
        cursor.close()
        close_db_connection(connection)


def get_fee_promotions_by_store(store_id: int, page: int = 1, limit: int = 5) -> Dict:
    """매장별 프로모션 이력 페이지네이션 (하위 호환)"""
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)

    try:
        cursor.execute("""
            SELECT COUNT(*) AS total
            FROM fee_promotions fp
            JOIN fee_promotion_stores fps ON fp.promo_id = fps.promo_id
            WHERE fps.store_id = %s
        """, (store_id,))
        total = cursor.fetchone()['total']

        offset = (page - 1) * limit
        cursor.execute("""
            SELECT
                fp.promo_id,
                fp.title,
                fp.promo_type,
                fp.promo_fee_rate,
                fps.start_date,
                fps.end_date,
                fps.applied_at,
                fps.removed_at,
                fp.is_active,
                fp.created_at,
                fp.updated_at
            FROM fee_promotions fp
            JOIN fee_promotion_stores fps ON fp.promo_id = fps.promo_id
            WHERE fps.store_id = %s
            ORDER BY fps.applied_at DESC
            LIMIT %s OFFSET %s
        """, (store_id, limit, offset))

        items = []
        for promo in cursor.fetchall():
            items.append({
                'promo_id': promo['promo_id'],
                'title': promo['title'],
                'promo_type': promo['promo_type'],
                'store_id': store_id,
                'promo_fee_rate': float(promo['promo_fee_rate']),
                'start_date': promo['start_date'].isoformat() if promo['start_date'] else None,
                'end_date': promo['end_date'].isoformat() if promo['end_date'] else None,
                'applied_at': promo['applied_at'].isoformat() if promo['applied_at'] else None,
                'removed_at': promo['removed_at'].isoformat() if promo['removed_at'] else None,
                'is_active': bool(promo['is_active']),
                'status': 'active' if promo['removed_at'] is None else 'removed',
                'created_at': promo['created_at'].isoformat() if promo.get('created_at') else None,
                'updated_at': promo['updated_at'].isoformat() if promo.get('updated_at') else None,
            })

        import math
        return {
            'promotions': items,
            'pagination': {
                'total': total,
                'page': page,
                'limit': limit,
                'total_pages': math.ceil(total / limit) if total > 0 else 1,
            }
        }
    finally:
        cursor.close()
        close_db_connection(connection)


def get_fee_info_for_settlement(store_id: int, payout_date: date) -> dict:
    """정산 지급 예정일 기준 수수료 정보 조회

    FIXED_PERIOD, PER_STORE_PERIOD 모두 fee_promotion_stores의 start_date/end_date로 판정.
    - FIXED_PERIOD는 등록 시점에 프로모션 기간을 매장 매핑에 복사해두므로 통일된 조회 가능.
    - PER_STORE_PERIOD는 매장 등록 시 매장별로 지정한 기간 사용.
    - removed_at IS NULL 조건으로 활성 매핑만 조회.
    """
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)

    try:
        cursor.execute("SELECT base_fee_rate FROM platform_config WHERE config_id = 1")
        config = cursor.fetchone()
        base_fee_rate = float(config['base_fee_rate']) if config else 3.00

        cursor.execute("""
            SELECT fp.promo_id, fp.promo_fee_rate, fp.title
            FROM fee_promotions fp
            JOIN fee_promotion_stores fps ON fp.promo_id = fps.promo_id
            WHERE fps.store_id = %s
              AND fp.is_active = TRUE
              AND fps.removed_at IS NULL
              AND fps.start_date IS NOT NULL
              AND fps.end_date IS NOT NULL
              AND fps.start_date <= %s
              AND fps.end_date >= %s
            ORDER BY fps.start_date ASC
            LIMIT 1
        """, (store_id, payout_date, payout_date))

        promo = cursor.fetchone()

        if promo:
            return {
                'base_fee_rate': base_fee_rate,
                'applied_fee_rate': float(promo['promo_fee_rate']),
                'applied_promo_id': int(promo['promo_id']),
                'applied_promo_title': promo.get('title'),
            }

        return {
            'base_fee_rate': base_fee_rate,
            'applied_fee_rate': base_fee_rate,
            'applied_promo_id': None,
            'applied_promo_title': None,
        }
    finally:
        cursor.close()
        close_db_connection(connection)


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
        close_db_connection(connection)


def apply_promotion_to_store(
    promo_id: int,
    store_id: int,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> bool:
    """매장에 프로모션 등록

    - FIXED_PERIOD: 프로모션 자체 기간이 매장 매핑에 복사됨. 호출자가 넘긴 날짜는 무시.
    - PER_STORE_PERIOD: 호출자가 start_date, end_date 필수.
    - 이미 활성(removed_at IS NULL) 매핑이 있으면 ValueError.
    - active_store_count +1.
    """
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)

    try:
        cursor.execute(
            "SELECT promo_type, start_date, end_date FROM fee_promotions WHERE promo_id = %s",
            (promo_id,)
        )
        promo = cursor.fetchone()
        if not promo:
            raise ValueError("프로모션을 찾을 수 없습니다.")

        promo_type = promo['promo_type']

        if promo_type == PROMO_TYPE_FIXED:
            eff_start = promo['start_date']
            eff_end = promo['end_date']
        else:
            if not start_date or not end_date:
                raise ValueError("PER_STORE_PERIOD 프로모션은 시작일과 종료일이 필수입니다.")
            if start_date >= end_date:
                raise ValueError("시작일은 종료일보다 이전이어야 합니다.")
            eff_start = start_date
            eff_end = end_date

        cursor.execute(
            """
            SELECT id FROM fee_promotion_stores
            WHERE promo_id = %s AND store_id = %s AND removed_at IS NULL
            """,
            (promo_id, store_id)
        )
        if cursor.fetchone():
            raise ValueError("이미 활성 상태로 등록된 프로모션입니다.")

        cursor.execute(
            """
            INSERT INTO fee_promotion_stores (promo_id, store_id, start_date, end_date)
            VALUES (%s, %s, %s, %s)
            """,
            (promo_id, store_id, eff_start, eff_end)
        )

        cursor.execute(
            "UPDATE fee_promotions SET active_store_count = active_store_count + 1 WHERE promo_id = %s",
            (promo_id,)
        )

        connection.commit()
        return True
    except Exception as e:
        connection.rollback()
        raise e
    finally:
        cursor.close()
        close_db_connection(connection)


def remove_promotion_from_store(promo_id: int, store_id: int) -> bool:
    """매장의 프로모션 등록 해제 (soft delete)

    - removed_at을 NOW()로 설정.
    - active_store_count -1.
    - 활성 매핑이 없으면 False 반환.
    """
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            UPDATE fee_promotion_stores
            SET removed_at = NOW()
            WHERE promo_id = %s AND store_id = %s AND removed_at IS NULL
            """,
            (promo_id, store_id)
        )
        if cursor.rowcount == 0:
            connection.rollback()
            return False

        cursor.execute(
            """
            UPDATE fee_promotions
            SET active_store_count = GREATEST(active_store_count - 1, 0)
            WHERE promo_id = %s
            """,
            (promo_id,)
        )

        connection.commit()
        return True
    except Exception as e:
        connection.rollback()
        raise e
    finally:
        cursor.close()
        close_db_connection(connection)


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
        close_db_connection(connection)
