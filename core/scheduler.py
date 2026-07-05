from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timezone, timedelta
from loguru import logger

from db.session import get_db_connection, close_db_connection

KST = timezone(timedelta(hours=9))


def _acquire_lock(cursor, lock_name: str) -> bool:
    """MySQL GET_LOCK으로 분산 락 획득. 이미 다른 인스턴스가 실행 중이면 False 반환."""
    cursor.execute("SELECT GET_LOCK(%s, 0)", (lock_name,))
    result = cursor.fetchone()
    return bool(result[0])


def _release_lock(cursor, lock_name: str):
    cursor.execute("SELECT RELEASE_LOCK(%s)", (lock_name,))
    cursor.fetchone()


def expire_pending_orders():
    """
    15분 이상 PENDING 상태인 orders를 EXPIRED로 전환.
    연결된 gifticon은 PENDING 유지 (30일 후 배치 삭제).
    MySQL GET_LOCK으로 다중 인스턴스 중복 실행 방지.
    """
    connection = get_db_connection()
    cursor = connection.cursor()
    lock_acquired = False

    try:
        lock_acquired = _acquire_lock(cursor, "expire_pending_orders")
        if not lock_acquired:
            return

        cutoff = datetime.now(KST) - timedelta(minutes=15)
        cursor.execute(
            "SELECT id FROM orders WHERE status = 'PENDING' AND created_at <= %s",
            (cutoff,)
        )
        order_ids = [row[0] for row in cursor.fetchall()]

        if not order_ids:
            return

        fmt = ",".join(["%s"] * len(order_ids))
        cursor.execute(f"UPDATE orders SET status = 'EXPIRED' WHERE id IN ({fmt})", order_ids)
        connection.commit()

        logger.info(f"[scheduler] expire_pending_orders: {len(order_ids)}건 만료 처리 {order_ids}")

    except Exception as e:
        connection.rollback()
        logger.error(f"[scheduler] expire_pending_orders 오류: {e}")
    finally:
        if lock_acquired:
            _release_lock(cursor, "expire_pending_orders")
        cursor.close()
        close_db_connection(connection)


def delete_old_records():
    """
    30일 초과된 EXPIRED orders 및 PENDING gifticon 삭제.
    MySQL GET_LOCK으로 다중 인스턴스 중복 실행 방지.
    """
    connection = get_db_connection()
    cursor = connection.cursor()
    lock_acquired = False

    try:
        lock_acquired = _acquire_lock(cursor, "delete_old_records")
        if not lock_acquired:
            return

        cutoff = datetime.now(KST) - timedelta(days=30)

        # PENDING gifticon 중 30일 초과 → 삭제 (EXPIRED orders에 연결된 것)
        cursor.execute("""
            DELETE g FROM gifticon g
            JOIN orders o ON g.order_id = o.id
            WHERE g.status = 'PENDING'
              AND o.status = 'EXPIRED'
              AND o.created_at <= %s
        """, (cutoff,))
        gifticon_deleted = cursor.rowcount

        # EXPIRED orders 중 30일 초과 → 삭제
        cursor.execute("""
            DELETE FROM orders
            WHERE status = 'EXPIRED'
              AND created_at <= %s
        """, (cutoff,))
        orders_deleted = cursor.rowcount

        connection.commit()
        logger.info(f"[scheduler] delete_old_records: orders {orders_deleted}건, gifticon {gifticon_deleted}건 삭제")

    except Exception as e:
        connection.rollback()
        logger.error(f"[scheduler] delete_old_records 오류: {e}")
    finally:
        if lock_acquired:
            _release_lock(cursor, "delete_old_records")
        cursor.close()
        close_db_connection(connection)


def create_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="Asia/Seoul")
    scheduler.add_job(expire_pending_orders, "interval", minutes=15, id="expire_pending_orders")
    scheduler.add_job(delete_old_records, "cron", hour=3, minute=0, id="delete_old_records")
    return scheduler
