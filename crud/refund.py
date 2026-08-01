"""Refund CRUD (관리자: 환불 리스트, 상태 변경)"""
import pymysql
from typing import List, Dict, Optional
from db.session import get_db_connection, close_db_connection


def get_refund_list(
    page: int = 1,
    limit: int = 20,
    refund_type: Optional[str] = None,
    status: Optional[str] = None,
) -> Dict:
    """환불 리스트 (구매날짜=orders.created_at, 환불요청날짜=refunded_at, 환불타입, 예금주, 계좌번호, 지급상태)"""
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    try:
        count_sql = """
            SELECT COUNT(*) as total
            FROM refund r
            LEFT JOIN orders o ON r.order_id = o.id
            WHERE 1=1
        """
        list_sql = """
            SELECT
                r.id,
                r.order_id,
                r.refund_type,
                r.original_amount,
                r.refunded_amount,
                r.fee_amount,
                r.status,
                r.refunded_at,
                r.account_holder,
                r.bank_code,
                r.bank_name,
                r.account_number,
                r.reason,
                r.receiver_user_id,
                o.created_at AS order_created_at
            FROM refund r
            LEFT JOIN orders o ON r.order_id = o.id
            WHERE 1=1
        """
        params = []
        if refund_type:
            count_sql += " AND r.refund_type = %s"
            list_sql += " AND r.refund_type = %s"
            params.append(refund_type)
        if status:
            count_sql += " AND r.status = %s"
            list_sql += " AND r.status = %s"
            params.append(status)

        cursor.execute(count_sql, params)
        total = cursor.fetchone()["total"] or 0

        list_sql += " ORDER BY r.refunded_at DESC LIMIT %s OFFSET %s"
        params.extend([limit, (page - 1) * limit])
        cursor.execute(list_sql, params)
        rows = cursor.fetchall()

        items = []
        for row in rows:
            items.append({
                "id": row["id"],
                "order_id": row["order_id"],
                "order_created_at": row["order_created_at"].isoformat() if row.get("order_created_at") else None,
                "refunded_at": row["refunded_at"].isoformat() if row.get("refunded_at") else None,
                "refund_type": row["refund_type"],
                "original_amount": int(row["original_amount"] or 0),
                "refunded_amount": int(row["refunded_amount"] or 0),
                "fee_amount": int(row["fee_amount"] or 0),
                "status": row["status"],
                "account_holder": row.get("account_holder"),
                "bank_code": row.get("bank_code"),
                "bank_name": row.get("bank_name"),
                "account_number": row.get("account_number"),
                "reason": row.get("reason"),
                "receiver_user_id": row.get("receiver_user_id"),
            })
        total_pages = (total + limit - 1) // limit if total else 1
        return {
            "items": items,
            "total": total,
            "page": page,
            "limit": limit,
            "total_pages": total_pages,
        }
    finally:
        cursor.close()
        close_db_connection(connection)


def update_refund_status(refund_id: int, status: str) -> Optional[Dict]:
    """환불 상태 변경. 허용 값: REQUESTED, COMPLETED, FAILED.
    RECEIVER(수신자) 환불이 COMPLETED/FAILED로 전이될 때는 gifticon.status를 동반 처리한다.
    - COMPLETED: 기프티콘 최종 취소(CANCELED)
    - FAILED: 기프티콘을 UNUSED로 복원하여 재신청 가능하도록 함
    """
    allowed = ("REQUESTED", "COMPLETED", "FAILED")
    if status not in allowed:
        return None
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    try:
        cursor.execute(
            "SELECT order_id, refund_type FROM refund WHERE id = %s",
            (refund_id,),
        )
        existing = cursor.fetchone()
        if not existing:
            return None

        cursor.execute(
            "UPDATE refund SET status = %s, updated_at = NOW() WHERE id = %s",
            (status, refund_id),
        )

        if existing["refund_type"] == "RECEIVER" and status in ("COMPLETED", "FAILED"):
            gifticon_status = "CANCELED" if status == "COMPLETED" else "UNUSED"
            cursor.execute(
                """
                UPDATE gifticon g
                JOIN orders_gifticon og ON og.gifticon_id = g.id
                SET g.status = %s
                WHERE og.order_id = %s AND g.status = 'REFUND_REQUESTED'
                """,
                (gifticon_status, existing["order_id"]),
            )

        connection.commit()

        cursor.execute(
            "SELECT id, order_id, refund_type, status, refunded_at FROM refund WHERE id = %s",
            (refund_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "order_id": row["order_id"],
            "refund_type": row["refund_type"],
            "status": row["status"],
            "refunded_at": row["refunded_at"].isoformat() if row.get("refunded_at") else None,
        }
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        close_db_connection(connection)
