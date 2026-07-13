import pymysql
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import timedelta
from loguru import logger

from core import clock
from core.config import settings
from db.session import get_db_connection, close_db_connection
from app.system_logger import log_scheduler_error

import http.client
import json


def _acquire_lock(cursor, lock_name: str) -> bool:
    """MySQL GET_LOCK으로 분산 락 획득. 이미 다른 인스턴스가 실행 중이면 False 반환."""
    cursor.execute("SELECT GET_LOCK(%s, 0)", (lock_name,))
    result = cursor.fetchone()
    return bool(result[0])


def _release_lock(cursor, lock_name: str):
    cursor.execute("SELECT RELEASE_LOCK(%s)", (lock_name,))
    cursor.fetchone()


def _payletter_cancel(payment_key: str, user_id: int, amount: int, pgcode: str) -> bool:
    """페이레터 결제 취소 API 호출. 성공 시 True, 실패 시 False 반환."""
    is_naverpay = pgcode == "naverpay"
    client_id = settings.payletter_naver_client_id if is_naverpay else settings.payletter_client_id
    api_key = settings.payletter_naver_payment_api_key if is_naverpay else settings.payletter_payment_api_key

    payload = json.dumps({
        "client_id": client_id,
        "tid": payment_key,
        "user_id": str(user_id),
        "ip_addr": "127.0.0.1",
    }, ensure_ascii=False).encode("utf-8")
    headers = {
        "Authorization": f"PLKEY {api_key}",
        "Content-Type": "application/json; charset=utf-8",
    }
    try:
        conn = http.client.HTTPSConnection(settings.payletter_api_host, timeout=15)
        conn.request("POST", "/v1.0/payments/cancel", payload, headers)
        res = conn.getresponse()
        body = res.read().decode("utf-8")
        if res.status != 200:
            logger.error(f"[scheduler] 페이레터 취소 실패 tid={payment_key}: {body}")
            return False
        return True
    except Exception as e:
        logger.error(f"[scheduler] 페이레터 취소 오류 tid={payment_key}: {e}")
        return False
    finally:
        conn.close()


def expire_pending_orders():
    """
    15분 이상 PENDING 상태인 orders를 EXPIRED로 전환.
    연결된 gifticon은 PENDING 유지 (30일 후 배치 삭제).
    MySQL GET_LOCK으로 다중 인스턴스 중복 실행 방지.
    """
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.Cursor)
    lock_acquired = False

    try:
        lock_acquired = _acquire_lock(cursor, "expire_pending_orders")
        if not lock_acquired:
            return

        cutoff = clock.now() - timedelta(minutes=15)
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
        log_scheduler_error("expire_pending_orders", e)
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
    cursor = connection.cursor(pymysql.cursors.Cursor)
    lock_acquired = False

    try:
        lock_acquired = _acquire_lock(cursor, "delete_old_records")
        if not lock_acquired:
            return

        cutoff = clock.now() - timedelta(days=30)

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
        log_scheduler_error("delete_old_records", e)
    finally:
        if lock_acquired:
            _release_lock(cursor, "delete_old_records")
        cursor.close()
        close_db_connection(connection)


def expire_gifticons():
    """
    유효기간(validity) 이 지난 UNUSED 기프티콘을 EXPIRED로 전환 후 90% 환불 처리.

    처리 순서:
    1. validity <= clock.now() 인 UNUSED 기프티콘 조회
    2. gifticon.status = 'EXPIRED' 업데이트
    3. 페이레터 결제 취소 API 호출 (90% 환불)
    4. 성공: refund 레코드 COMPLETED, gifticon.status = 'REFUNDED'
    5. 실패: refund 레코드 FAILED (다음 배치에서 재시도)
    6. 알림톡 발송 (구매자에게 만료/환불 안내)

    MySQL GET_LOCK으로 다중 인스턴스 중복 실행 방지.
    """
    connection = get_db_connection()
    lock_cursor = connection.cursor(pymysql.cursors.Cursor)
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    lock_acquired = False

    try:
        lock_acquired = _acquire_lock(lock_cursor, "expire_gifticons")
        if not lock_acquired:
            return

        now = clock.now()

        # 1. 만료 대상 조회 (validity <= now, UNUSED)
        # FAILED 환불 재시도 포함: EXPIRED 상태인데 COMPLETED refund 없는 것도 포함
        cursor.execute("""
            SELECT
                g.id AS gifticon_id,
                g.user_id,
                g.menu_id,
                g.store_id,
                g.validity,
                o.id AS order_id,
                o.payment_key,
                o.pgcode,
                o.amount,
                m.menu_name,
                u.phone AS user_phone
            FROM gifticon g
            JOIN orders o ON g.order_id = o.id
            JOIN menu m ON g.menu_id = m.id
            LEFT JOIN user u ON g.user_id = u.id
            WHERE g.status IN ('UNUSED', 'EXPIRED')
              AND g.validity IS NOT NULL
              AND g.validity <= %s
              AND NOT EXISTS (
                  SELECT 1 FROM refund r
                  WHERE r.order_id = o.id AND r.status = 'COMPLETED'
              )
        """, (now.date(),))
        targets = cursor.fetchall()

        if not targets:
            return

        logger.info(f"[scheduler] expire_gifticons: {len(targets)}건 만료 처리 시작")

        for g in targets:
            gid = g["gifticon_id"]
            order_id = g["order_id"]
            payment_key = g["payment_key"]
            pgcode = g["pgcode"] or "creditcard"
            user_id = g["user_id"]
            original_amount = int(g["amount"] or 0)
            refund_amount = int(original_amount * 0.9)
            menu_name = g["menu_name"] or "기프티콘"
            user_phone = g["user_phone"]

            try:
                # 2. EXPIRED로 상태 변경
                cursor.execute(
                    "UPDATE gifticon SET status = 'EXPIRED' WHERE id = %s AND status IN ('UNUSED', 'EXPIRED')",
                    (gid,)
                )

                # 3. refund 레코드 선삽입 (PROCESSING)
                cursor.execute("""
                    INSERT INTO refund (order_id, refund_type, amount, status, refunded_at, reason)
                    VALUES (%s, 'EXPIRY', %s, 'PROCESSING', %s, '유효기간 만료 자동 환불')
                """, (order_id, refund_amount, now))
                refund_id = cursor.lastrowid

                connection.commit()

                # 4. 페이레터 환불 API 호출
                success = _payletter_cancel(payment_key, user_id, refund_amount, pgcode)

                if success:
                    cursor.execute(
                        "UPDATE gifticon SET status = 'REFUNDED' WHERE id = %s",
                        (gid,)
                    )
                    cursor.execute(
                        "UPDATE orders SET status = 'REFUNDED' WHERE id = %s",
                        (order_id,)
                    )
                    if refund_id:
                        cursor.execute(
                            "UPDATE refund SET status = 'COMPLETED', refunded_at = %s WHERE id = %s",
                            (now, refund_id)
                        )
                    connection.commit()
                    logger.info(f"[scheduler] expire_gifticons: gifticon_id={gid} 환불 완료 {refund_amount}원")

                else:
                    if refund_id:
                        cursor.execute(
                            "UPDATE refund SET status = 'FAILED' WHERE id = %s",
                            (refund_id,)
                        )
                    connection.commit()
                    logger.warning(f"[scheduler] expire_gifticons: gifticon_id={gid} 환불 실패 → FAILED 기록")

            except Exception as e:
                connection.rollback()
                logger.error(f"[scheduler] expire_gifticons gifticon_id={gid} 처리 오류: {e}")
                log_scheduler_error("expire_gifticons", e)

    except Exception as e:
        connection.rollback()
        logger.error(f"[scheduler] expire_gifticons 전체 오류: {e}")
        log_scheduler_error("expire_gifticons", e)
    finally:
        if lock_acquired:
            _release_lock(lock_cursor, "expire_gifticons")
        lock_cursor.close()
        cursor.close()
        close_db_connection(connection)


def create_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="Asia/Seoul")
    scheduler.add_job(expire_pending_orders, "interval", minutes=15, id="expire_pending_orders")
    scheduler.add_job(delete_old_records, "cron", hour=3, minute=0, id="delete_old_records")

    # 테스트/로컬 환경에서는 1분마다, 프로덕션에서는 매일 03:20
    import os
    if os.getenv("ENV", "dev") in ("test", "local"):
        scheduler.add_job(expire_gifticons, "interval", minutes=1, id="expire_gifticons")
    else:
        scheduler.add_job(expire_gifticons, "cron", hour=3, minute=20, id="expire_gifticons")

    return scheduler
