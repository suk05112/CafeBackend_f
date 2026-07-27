"""Alimtalk CRUD (카카오 알림톡 발송 큐/이력)"""
import json
import pymysql
from typing import List, Dict, Optional
from db.session import get_db_connection, close_db_connection

MAX_AUTO_RETRY = 5  # 자동 배치 재시도 상한 (5회 실패 후 자동 픽업 제외)


def enqueue(
    tpl_code: str,
    category: str,
    receiver_phone: str,
    subject: str,
    message: str,
    recvname: str = "",
    button: Optional[dict] = None,
    ref_type: Optional[str] = None,
    ref_id: Optional[int] = None,
) -> Dict:
    """PENDING 상태로 알림톡 큐에 적재"""
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    try:
        cursor.execute(
            """INSERT INTO alimtalk_log
               (tpl_code, category, receiver_phone, recvname, subject, message, button_json, ref_type, ref_id, status)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'PENDING')""",
            (
                tpl_code, category, receiver_phone, recvname, subject, message,
                json.dumps(button, ensure_ascii=False) if button else None,
                ref_type, ref_id,
            ),
        )
        connection.commit()
        return {"id": cursor.lastrowid, "status": "QUEUED"}
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        close_db_connection(connection)


def get_pending_and_retryable(limit: int = 100) -> List[Dict]:
    """PENDING 전체 + retry_count < MAX_AUTO_RETRY인 FAILED, 오래된 순 (자동 배치 전용)"""
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    try:
        cursor.execute(
            """SELECT * FROM alimtalk_log
               WHERE status = 'PENDING'
                  OR (status = 'FAILED' AND retry_count < %s)
               ORDER BY created_at ASC
               LIMIT %s""",
            (MAX_AUTO_RETRY, limit),
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        close_db_connection(connection)


def get_by_ids(ids: List[int]) -> List[Dict]:
    """관리자 수동 재발송 대상 조회 (재시도 상한 무시)"""
    if not ids:
        return []
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    try:
        fmt = ",".join(["%s"] * len(ids))
        cursor.execute(f"SELECT * FROM alimtalk_log WHERE id IN ({fmt})", ids)
        return cursor.fetchall()
    finally:
        cursor.close()
        close_db_connection(connection)


def mark_sent(log_id: int, aligo_mid: Optional[str], sent_at) -> None:
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    try:
        cursor.execute(
            """UPDATE alimtalk_log
               SET status='SENT', aligo_mid=%s, sent_at=%s, fail_reason=NULL
               WHERE id=%s""",
            (aligo_mid, sent_at, log_id),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        close_db_connection(connection)


def mark_failed(log_id: int, fail_reason: Optional[str]) -> None:
    """실패 시 status=FAILED + retry_count 증가 (자동/수동 공통, 상한 적용은 조회 단계에서 처리)"""
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    try:
        cursor.execute(
            """UPDATE alimtalk_log
               SET status='FAILED', retry_count = retry_count + 1, fail_reason=%s
               WHERE id=%s""",
            (fail_reason[:255] if fail_reason else None, log_id),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        close_db_connection(connection)


def get_log_list(status: Optional[str] = None, page: int = 1, limit: int = 20) -> Dict:
    """관리자 알림톡 로그 리스트 (상태 필터 + 페이지네이션)"""
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    try:
        count_sql = "SELECT COUNT(*) as total FROM alimtalk_log WHERE 1=1"
        list_sql = """
            SELECT id, tpl_code, category, receiver_phone, recvname, subject,
                   ref_type, ref_id, status, retry_count, aligo_mid, fail_reason,
                   sent_at, created_at
            FROM alimtalk_log
            WHERE 1=1
        """
        params: list = []
        if status:
            count_sql += " AND status = %s"
            list_sql += " AND status = %s"
            params.append(status)

        cursor.execute(count_sql, params)
        total = cursor.fetchone()["total"] or 0

        list_sql += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
        params_list = params + [limit, (page - 1) * limit]
        cursor.execute(list_sql, params_list)
        rows = cursor.fetchall()

        items = []
        for row in rows:
            items.append({
                "id": row["id"],
                "tpl_code": row["tpl_code"],
                "category": row["category"],
                "receiver_phone": row["receiver_phone"],
                "recvname": row.get("recvname"),
                "subject": row["subject"],
                "ref_type": row.get("ref_type"),
                "ref_id": row.get("ref_id"),
                "status": row["status"],
                "retry_count": row["retry_count"],
                "aligo_mid": row.get("aligo_mid"),
                "fail_reason": row.get("fail_reason"),
                "sent_at": row["sent_at"].isoformat() if row.get("sent_at") else None,
                "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
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
