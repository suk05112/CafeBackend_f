import http.client
import json
import os
import pymysql
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import timedelta
from loguru import logger

from core import clock
from core.config import settings
from db.session import get_db_connection, close_db_connection
from app.system_logger import log_scheduler_error
from app.aligo_service import send_gift_auto_refund_to_sender, send_gift_auto_refund_to_receiver, send_alimtalk_log_row, get_history_detail
from crud import alimtalk as alimtalk_crud
from scripts.aggregate_daily_platform_stats import aggregate_one_day, upsert_stats, get_base_fee_rate


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
    result = {"processed": 0}

    try:
        lock_acquired = _acquire_lock(cursor, "expire_pending_orders")
        if not lock_acquired:
            result["skipped"] = "lock"
            return result

        cutoff = clock.now() - timedelta(minutes=15)
        cursor.execute(
            "SELECT id FROM orders WHERE status = 'PENDING' AND created_at <= %s",
            (cutoff,)
        )
        order_ids = [row[0] for row in cursor.fetchall()]

        if not order_ids:
            return result

        fmt = ",".join(["%s"] * len(order_ids))
        cursor.execute(f"UPDATE orders SET status = 'EXPIRED' WHERE id IN ({fmt})", order_ids)
        connection.commit()

        result["processed"] = len(order_ids)
        logger.info(f"[scheduler] expire_pending_orders: {len(order_ids)}건 만료 처리 {order_ids}")

    except Exception as e:
        connection.rollback()
        logger.error(f"[scheduler] expire_pending_orders 오류: {e}")
        log_scheduler_error("expire_pending_orders", e)
        result["error"] = str(e)
    finally:
        if lock_acquired:
            _release_lock(cursor, "expire_pending_orders")
        cursor.close()
        close_db_connection(connection)
    return result


def delete_old_records():
    """
    30일 초과된 EXPIRED orders 및 PENDING gifticon 삭제.
    MySQL GET_LOCK으로 다중 인스턴스 중복 실행 방지.
    """
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.Cursor)
    lock_acquired = False
    result = {"orders_deleted": 0, "gifticon_deleted": 0}

    try:
        lock_acquired = _acquire_lock(cursor, "delete_old_records")
        if not lock_acquired:
            result["skipped"] = "lock"
            return result

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
        result["orders_deleted"] = orders_deleted
        result["gifticon_deleted"] = gifticon_deleted
        logger.info(f"[scheduler] delete_old_records: orders {orders_deleted}건, gifticon {gifticon_deleted}건 삭제")

    except Exception as e:
        connection.rollback()
        logger.error(f"[scheduler] delete_old_records 오류: {e}")
        log_scheduler_error("delete_old_records", e)
        result["error"] = str(e)
    finally:
        if lock_acquired:
            _release_lock(cursor, "delete_old_records")
        cursor.close()
        close_db_connection(connection)
    return result


def expire_gifticons():
    """
    유효기간(validity) 이 지난 UNUSED 기프티콘을 EXPIRED로 전환.

    GNB-196: 자동환불(EXPIRY) 폐지. EXPIRED 전환 이후의 환불은
    수신자의 환불 신청 API(POST /order/refund-request/{order_id})를 통해 처리한다.

    MySQL GET_LOCK으로 다중 인스턴스 중복 실행 방지.
    """
    connection = get_db_connection()
    lock_cursor = connection.cursor(pymysql.cursors.Cursor)
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    lock_acquired = False
    result = {"processed": 0}

    try:
        lock_acquired = _acquire_lock(lock_cursor, "expire_gifticons")
        if not lock_acquired:
            result["skipped"] = "lock"
            return result

        now = clock.now()

        # 만료 대상 조회 (validity <= now, UNUSED)
        cursor.execute("""
            SELECT g.id AS gifticon_id
            FROM gifticon g
            WHERE g.status = 'UNUSED'
              AND g.validity IS NOT NULL
              AND g.validity <= %s
        """, (now.date(),))
        targets = cursor.fetchall()

        if not targets:
            return result

        gifticon_ids = [g["gifticon_id"] for g in targets]
        fmt = ",".join(["%s"] * len(gifticon_ids))
        cursor.execute(
            f"UPDATE gifticon SET status = 'EXPIRED' WHERE id IN ({fmt}) AND status = 'UNUSED'",
            gifticon_ids
        )
        connection.commit()

        result["processed"] = len(gifticon_ids)
        logger.info(f"[scheduler] expire_gifticons: {len(gifticon_ids)}건 만료 처리 {gifticon_ids}")

    except Exception as e:
        connection.rollback()
        logger.error(f"[scheduler] expire_gifticons 오류: {e}")
        log_scheduler_error("expire_gifticons", e)
        result["error"] = str(e)
    finally:
        if lock_acquired:
            _release_lock(lock_cursor, "expire_gifticons")
        lock_cursor.close()
        cursor.close()
        close_db_connection(connection)
    return result


def auto_refund_unregistered_gifts():
    """
    선물 타입(type=2) 기프티콘 중 주문일 기준 7일(당일 불포함)이 지나도
    수신자가 등록하지 않은(receiver_id IS NULL) 건을 자동 환불 처리.
    실패 건(refund.status='FAILED')도 재시도.
    MySQL GET_LOCK으로 다중 인스턴스 중복 실행 방지.
    """
    connection = get_db_connection()
    lock_cursor = connection.cursor(pymysql.cursors.Cursor)
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    lock_acquired = False
    result = {"processed": 0, "refunded": 0, "failed": 0}

    try:
        lock_acquired = _acquire_lock(lock_cursor, "auto_refund_unregistered_gifts")
        if not lock_acquired:
            result["skipped"] = "lock"
            return result

        cutoff = clock.now() - timedelta(days=7)

        # 대상: 미등록 선물 기프티콘 (UNUSED + receiver_id NULL + 7일 초과)
        # FAILED 환불 건도 포함하여 재시도
        cursor.execute("""
            SELECT
                o.id AS order_id,
                o.payment_key,
                o.amount,
                o.pgcode,
                o.user_id,
                g.id AS gifticon_id,
                g.menu_id,
                g.receiver_phone,
                g.receiver,
                g.sender,
                m.menu_name,
                u.phone AS sender_phone,
                r.id AS failed_refund_id
            FROM orders o
            JOIN gifticon g ON g.order_id = o.id
            JOIN menu m ON m.id = g.menu_id
            LEFT JOIN user u ON u.id = o.user_id
            LEFT JOIN refund r ON r.order_id = o.id AND r.status = 'FAILED'
            WHERE o.status = 'COMPLETED'
              AND o.created_at < %s
              AND g.type = 2
              AND g.receiver_id IS NULL
              AND g.status = 'UNUSED'
        """, (cutoff,))
        targets = cursor.fetchall()

        if not targets:
            return result

        result["processed"] = len(targets)
        logger.info(f"[scheduler] auto_refund_unregistered_gifts: {len(targets)}건 대상")

        for row in targets:
            order_id = row["order_id"]
            payment_key = row["payment_key"]
            amount = int(row["amount"] or 0)
            pgcode = row["pgcode"] or "creditcard"
            gifticon_id = row["gifticon_id"]
            sender_phone = row["sender_phone"]
            menu_name = row["menu_name"]
            failed_refund_id = row["failed_refund_id"]

            try:
                # 이미 COMPLETED 환불 존재하면 스킵
                cursor.execute(
                    "SELECT id FROM refund WHERE order_id=%s AND status='COMPLETED' LIMIT 1",
                    (order_id,)
                )
                if cursor.fetchone():
                    continue

                now = clock.now()

                # FAILED 재시도면 기존 레코드 재사용, 신규면 PROCESSING 선삽입
                if failed_refund_id:
                    cursor.execute(
                        "UPDATE refund SET status='PROCESSING', refunded_at=%s WHERE id=%s",
                        (now, failed_refund_id)
                    )
                    refund_id = failed_refund_id
                else:
                    cursor.execute(
                        """INSERT INTO refund (order_id, refund_type, original_amount, refunded_amount, fee_amount, status, refunded_at)
                           VALUES (%s, 'PURCHASER', %s, %s, 0, 'PROCESSING', %s)""",
                        (order_id, amount, amount, now)
                    )
                    refund_id = cursor.lastrowid
                connection.commit()

                # 페이레터 결제 취소
                success = _payletter_cancel(payment_key, row["user_id"], amount, pgcode)

                if success:
                    cursor.execute("UPDATE orders SET status='REFUNDED' WHERE id=%s", (order_id,))
                    cursor.execute("UPDATE gifticon SET status='CANCELED' WHERE id=%s", (gifticon_id,))
                    cursor.execute(
                        "UPDATE refund SET status='COMPLETED', refunded_at=%s WHERE id=%s",
                        (now, refund_id)
                    )
                    connection.commit()
                    result["refunded"] += 1
                    logger.info(f"[scheduler] auto_refund order_id={order_id} 환불 완료")
                else:
                    cursor.execute(
                        "UPDATE refund SET status='FAILED' WHERE id=%s",
                        (refund_id,)
                    )
                    connection.commit()
                    result["failed"] += 1
                    logger.warning(f"[scheduler] auto_refund order_id={order_id} 환불 실패 → FAILED 기록")

                # 발신자 알림톡 발송 (실패해도 환불은 유지)
                if success and sender_phone:
                    try:
                        send_gift_auto_refund_to_sender(
                            receiver=sender_phone,
                            menu=menu_name,
                        )
                    except Exception as e:
                        logger.error(f"[scheduler] 알림톡 발송 실패 order_id={order_id}: {e}")

                # 수신자 알림톡 발송 (실패해도 환불은 유지)
                if success and row["receiver_phone"]:
                    try:
                        send_gift_auto_refund_to_receiver(
                            receiver=row["receiver_phone"],
                            menu=menu_name,
                            recvname=row.get("receiver", ""),
                        )
                    except Exception as e:
                        logger.error(f"[scheduler] 수신자 알림톡 발송 실패 order_id={order_id}: {e}")

            except Exception as e:
                connection.rollback()
                result["failed"] += 1
                logger.error(f"[scheduler] auto_refund order_id={order_id} 실패: {e}")
                log_scheduler_error("auto_refund_unregistered_gifts", e)

    except Exception as e:
        connection.rollback()
        logger.error(f"[scheduler] auto_refund_unregistered_gifts 오류: {e}")
        log_scheduler_error("auto_refund_unregistered_gifts", e)
        result["error"] = str(e)
    finally:
        if lock_acquired:
            _release_lock(lock_cursor, "auto_refund_unregistered_gifts")
        lock_cursor.close()
        cursor.close()
        close_db_connection(connection)
    return result


def aggregate_yesterday_platform_stats():
    """
    전날(KST 기준) 플랫폼 일별 통계를 stats_daily_platform에 집계.
    scripts/aggregate_daily_platform_stats.py의 로직 재사용.
    MySQL GET_LOCK으로 다중 인스턴스 중복 실행 방지.
    """
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.Cursor)
    lock_acquired = False
    result = {}

    try:
        lock_acquired = _acquire_lock(cursor, "aggregate_daily_platform_stats")
        if not lock_acquired:
            result["skipped"] = "lock"
            return result

        target = (clock.now() - timedelta(days=1)).date()
        base_fee_rate = get_base_fee_rate(cursor)
        stats = aggregate_one_day(cursor, target, base_fee_rate)
        upsert_stats(cursor, stats)
        connection.commit()

        result["target_date"] = str(target)
        result["issued_count"] = stats["total_issued_count"]
        result["used_count"] = stats["total_used_count"]
        result["new_store_count"] = stats["new_store_count"]
        logger.info(
            f"[scheduler] aggregate_daily_platform_stats: {target} 집계 완료 "
            f"발행:{stats['total_issued_count']}건 사용:{stats['total_used_count']}건 "
            f"신규매장:{stats['new_store_count']}"
        )

    except Exception as e:
        connection.rollback()
        logger.error(f"[scheduler] aggregate_daily_platform_stats 오류: {e}")
        log_scheduler_error("aggregate_daily_platform_stats", e)
        result["error"] = str(e)
    finally:
        if lock_acquired:
            _release_lock(cursor, "aggregate_daily_platform_stats")
        cursor.close()
        close_db_connection(connection)
    return result


def generate_weekly_settlements():
    """
    종료된(period_end_date < 오늘) OPEN 상태 정산 주기에 대해 매장별 정산 데이터를 생성.
    이미 생성된 (store_id, cycle_id) 조합은 crud.stats.create_settlement_data 내부에서 skip.
    MySQL GET_LOCK으로 다중 인스턴스 중복 실행 방지.
    """
    from crud import stats as stats_crud

    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    lock_acquired = False
    result = {"cycles_processed": 0, "settlement_count": 0, "failed_count": 0}

    try:
        lock_acquired = _acquire_lock(cursor, "generate_weekly_settlements")
        if not lock_acquired:
            result["skipped"] = "lock"
            return result

        today = clock.now().date()
        cursor.execute("""
            SELECT cycle_id FROM settlement_cycles
            WHERE status = 'OPEN' AND period_end_date < %s
            ORDER BY period_start_date ASC
        """, (today,))
        cycles = cursor.fetchall()

        if not cycles:
            return result

        for cycle in cycles:
            cycle_id = cycle["cycle_id"]
            try:
                cycle_result = stats_crud.create_settlement_data(cycle_id)
                result["cycles_processed"] += 1
                result["settlement_count"] += cycle_result.get("settlement_count", 0)
                result["failed_count"] += cycle_result.get("failed_count", 0)
                logger.info(f"[scheduler] generate_weekly_settlements: cycle_id={cycle_id} 처리 완료 {cycle_result}")
            except Exception as e:
                logger.error(f"[scheduler] generate_weekly_settlements cycle_id={cycle_id} 실패: {e}")
                log_scheduler_error("generate_weekly_settlements", e)

    except Exception as e:
        logger.error(f"[scheduler] generate_weekly_settlements 오류: {e}")
        log_scheduler_error("generate_weekly_settlements", e)
        result["error"] = str(e)
    finally:
        if lock_acquired:
            _release_lock(cursor, "generate_weekly_settlements")
        cursor.close()
        close_db_connection(connection)
    return result


def send_pending_alimtalk():
    """
    1) alimtalk_log에서 PENDING 건을 조회해 알리고 발송을 요청한다.
       접수 성공(code=0, fcnt=0)이면 REQUESTED로 표시한다 (최종 발송 성공 아님).
    2) REQUESTED 건을 history/detail로 조회해 최종 결과(rslt)를 확인, SENT/FAILED로 확정한다.
       아직 결과가 나오지 않았으면 REQUESTED로 남겨두고 다음 배치에서 재확인한다.
    FAILED는 자동 재시도하지 않는다 — 관리자가 /admin/alimtalk/retry로 수동 재발송한다.
    MySQL GET_LOCK으로 다중 인스턴스 중복 실행 방지.
    """
    connection = get_db_connection()
    lock_cursor = connection.cursor(pymysql.cursors.Cursor)
    lock_acquired = False
    result = {"processed": 0, "sent": 0, "failed": 0, "requested": 0}

    try:
        lock_acquired = _acquire_lock(lock_cursor, "send_pending_alimtalk")
        if not lock_acquired:
            result["skipped"] = "lock"
            return result

        # 1) PENDING 건 발송 요청
        pending_rows = alimtalk_crud.get_pending(limit=100)
        for row in pending_rows:
            log_id = row["id"]
            try:
                send_result = send_alimtalk_log_row(row)
                info = send_result.get("info", {}) or {}
                fcnt = int(info.get("fcnt") or 0)
                if send_result.get("code") == 0 and fcnt == 0:
                    alimtalk_crud.mark_requested(log_id, info.get("mid"))
                    result["requested"] += 1
                elif send_result.get("code") == 0:
                    alimtalk_crud.mark_failed(log_id, f"수신자 접수 실패 (fcnt={fcnt})")
                    result["failed"] += 1
                else:
                    alimtalk_crud.mark_failed(log_id, str(send_result.get("message")))
                    result["failed"] += 1
            except Exception as e:
                alimtalk_crud.mark_failed(log_id, str(e))
                result["failed"] += 1
                logger.error(f"[scheduler] send_pending_alimtalk 발송 id={log_id} 실패: {e}")
                log_scheduler_error("send_pending_alimtalk", e)

        # 2) REQUESTED 건 최종 결과 확인
        requested_rows = alimtalk_crud.get_requested_for_confirm(limit=100)
        for row in requested_rows:
            log_id = row["id"]
            mid = row.get("aligo_mid")
            if not mid:
                alimtalk_crud.mark_failed(log_id, "aligo_mid 없음 (확인 불가)")
                result["failed"] += 1
                continue
            try:
                detail = get_history_detail(mid)
                items = detail.get("list") or []
                if detail.get("code") != 0 or not items:
                    continue  # 아직 결과 미확정 — 다음 배치에서 재확인
                rslt = items[0].get("rslt")
                if rslt == "U":
                    alimtalk_crud.mark_failed(log_id, items[0].get("rslt_message") or "발송 실패")
                    result["failed"] += 1
                else:
                    alimtalk_crud.mark_sent(log_id, mid, clock.now())
                    result["sent"] += 1
            except Exception as e:
                logger.error(f"[scheduler] send_pending_alimtalk 결과확인 id={log_id}: {e}")
                log_scheduler_error("send_pending_alimtalk", e)

        result["processed"] = len(pending_rows) + len(requested_rows)
        if result["processed"]:
            logger.info(f"[scheduler] send_pending_alimtalk: {result}")

    except Exception as e:
        logger.error(f"[scheduler] send_pending_alimtalk 오류: {e}")
        log_scheduler_error("send_pending_alimtalk", e)
        result["error"] = str(e)
    finally:
        if lock_acquired:
            _release_lock(lock_cursor, "send_pending_alimtalk")
        lock_cursor.close()
        close_db_connection(connection)
    return result


BATCH_JOBS = {
    "expire_pending_orders": {
        "name": "미결제 주문 만료",
        "description": "15분 이상 PENDING 상태인 주문을 EXPIRED로 전환합니다.",
        "schedule": "15분마다",
        "runnable": True,
        "requires_confirm": False,
    },
    "delete_old_records": {
        "name": "오래된 레코드 삭제",
        "description": "30일 초과된 EXPIRED 주문 및 PENDING 기프티콘을 삭제합니다.",
        "schedule": "매일 03:00",
        "runnable": True,
        "requires_confirm": False,
    },
    "expire_gifticons": {
        "name": "기프티콘 유효기간 만료",
        "description": "유효기간이 지난 미사용 기프티콘을 EXPIRED로 전환합니다. (자동환불 없음, 수신자 환불 신청으로 처리)",
        "schedule": "매일 00:01",
        "runnable": True,
        "requires_confirm": False,
    },
    "auto_refund_unregistered_gifts": {
        "name": "미등록 선물 자동환불",
        "description": "7일간 미등록된 선물 기프티콘을 자동 환불합니다. 실제 결제 취소(페이레터)가 발생합니다.",
        "schedule": "10분마다",
        "runnable": True,
        "requires_confirm": True,
    },
    "aggregate_yesterday_platform_stats": {
        "name": "전날 플랫폼 통계 집계",
        "description": "전날(KST 기준) 플랫폼 일별 통계를 집계합니다.",
        "schedule": "매일 03:40",
        "runnable": True,
        "requires_confirm": False,
    },
    "send_pending_alimtalk": {
        "name": "알림톡 발송 큐 처리",
        "description": "대기 중이거나 재시도 가능한(5회 미만 실패) 알림톡을 발송합니다.",
        "schedule": "매일 10:00",
        "runnable": True,
        "requires_confirm": False,
    },
    "generate_weekly_settlements": {
        "name": "정산 데이터 자동 생성",
        "description": "종료된 정산 주기에 대해 매장별 정산 데이터를 생성합니다. (store_id, cycle_id) 조합당 1회만 생성됩니다.",
        "schedule": "매주 일요일 03:00",
        "runnable": True,
        "requires_confirm": False,
    },
}

JOB_FUNCTIONS = {
    "expire_pending_orders": expire_pending_orders,
    "delete_old_records": delete_old_records,
    "expire_gifticons": expire_gifticons,
    "auto_refund_unregistered_gifts": auto_refund_unregistered_gifts,
    "aggregate_yesterday_platform_stats": aggregate_yesterday_platform_stats,
    "send_pending_alimtalk": send_pending_alimtalk,
    "generate_weekly_settlements": generate_weekly_settlements,
}


def create_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="Asia/Seoul")
    scheduler.add_job(expire_pending_orders, "interval", minutes=15, id="expire_pending_orders")
    scheduler.add_job(delete_old_records, "cron", hour=3, minute=0, id="delete_old_records")

    # 테스트/로컬 환경에서는 1분마다, 프로덕션에서는 매일 03:20
    if os.getenv("ENV", "dev") in ("test", "local"):
        scheduler.add_job(expire_gifticons, "interval", minutes=1, id="expire_gifticons")
        scheduler.add_job(auto_refund_unregistered_gifts, "interval", minutes=1, id="auto_refund_unregistered_gifts")
        scheduler.add_job(aggregate_yesterday_platform_stats, "interval", minutes=1, id="aggregate_daily_platform_stats")
        scheduler.add_job(send_pending_alimtalk, "interval", minutes=1, id="send_pending_alimtalk")
        scheduler.add_job(generate_weekly_settlements, "interval", minutes=1, id="generate_weekly_settlements")
    else:
        scheduler.add_job(expire_gifticons, "cron", hour=0, minute=1, id="expire_gifticons")
        # 7일 경과 여부를 매 실행마다 재계산하므로 10분 주기로도 유실 없이 처리 가능 (최대 10분 지연)
        scheduler.add_job(auto_refund_unregistered_gifts, "interval", minutes=10, id="auto_refund_unregistered_gifts")
        # GNB-202: 매일 03:40 KST 전날 통계 집계 (다른 배치와 시간대 분산)
        scheduler.add_job(aggregate_yesterday_platform_stats, "cron", hour=3, minute=40, id="aggregate_daily_platform_stats")
        # GNB-217: 알림톡 발송 큐, 매일 10:00 KST 일괄 처리
        scheduler.add_job(send_pending_alimtalk, "cron", hour=10, minute=0, id="send_pending_alimtalk")
        # GNB-220: 매주 일요일 03:00 KST 종료된 정산 주기 자동 생성
        scheduler.add_job(generate_weekly_settlements, "cron", day_of_week="sun", hour=3, minute=0, id="generate_weekly_settlements")

    return scheduler
