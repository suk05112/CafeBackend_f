from fastapi import APIRouter, HTTPException, status, Request, Form, Depends
from app.auth.auth_dependency import verify_firebase_token
from fastapi.responses import RedirectResponse
import traceback

from typing import Union, Optional
from pydantic import BaseModel
from loguru import logger
from app.system_logger import log_external_api_error

import pymysql
from db.session import get_db_connection, close_db_connection
from datetime import datetime, timedelta, date, timezone
from core.s3_config import S3_CLIENT, BUCKET_NAME, get_s3_public_url

from models.gifticon import Gifticon, PaymentResult, VALID_PGCODES
from models.store import StoreCreate

import http.client
import json
import hashlib

from core.config import settings
from core.exceptions import InternalError
from app.aligo_service import send_gift_cancel_to_receiver

router = APIRouter()


class RefundReceiverAccount(BaseModel):
    """수신자 환불 시 계좌정보 (60일 이후 환불일 때 필수)"""
    account_holder: str
    bank_code: str
    bank_name: str
    account_number: str


class RefundRequest(BaseModel):
    """환불 요청 본문 (수신자 계좌 + 환불 사유)"""
    receiver_account: Optional[RefundReceiverAccount] = None
    reason: Optional[str] = None

# 한국 시간대 (KST, UTC+9)
KST = timezone(timedelta(hours=9))

def get_kst_now():
    """한국 시간(KST)을 반환하는 헬퍼 함수"""
    return datetime.now(KST)

def generate_order_no(connection) -> str:
    """
    주문번호 생성: yyddd + seq + 5000
    GET_LOCK으로 동시 요청 시 중복 주문번호 방지.
    """
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    try:
        cursor.execute("SELECT GET_LOCK('order_no_gen', 5) AS locked")
        if not cursor.fetchone()['locked']:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="주문번호 생성 잠금 획득 실패. 잠시 후 다시 시도해주세요."
            )
        try:
            today = get_kst_now()
            yyddd = today.strftime("%y") + str(today.timetuple().tm_yday).zfill(3)
            cursor.execute(
                "SELECT COUNT(*) as cnt FROM orders WHERE DATE(created_at) = CURDATE()"
            )
            seq = cursor.fetchone()['cnt'] + 1
            while True:
                order_no = f"{yyddd}{seq + 5000:05d}"
                cursor.execute("SELECT 1 FROM orders WHERE order_no = %s", (order_no,))
                if not cursor.fetchone():
                    return order_no
                seq += 1
        finally:
            cursor.execute("SELECT RELEASE_LOCK('order_no_gen')")
    finally:
        cursor.close()

def generate_gift_code(connection, cursor, store_id: int, user_id: int, gifticon_id: int) -> str:
    """
    기프티콘 번호 생성: yymm + storeid%10000 + (userid+5000)%10000 + seq
    형식: 4-4-4-4 (예: 2412-1234-5678-0001)
    
    중복 방지: gifticon_id를 seq로 사용하여 고유성 보장
    """
    today = get_kst_now()
    yymm = today.strftime("%y%m")
    
    store_part = store_id % 10000
    user_part = (user_id + 5000) % 10000
    
    # seq는 gifticon_id를 사용하여 고유성 보장
    # 같은 년월, 같은 store, 같은 user에서도 gifticon_id가 다르면 다른 번호
    seq = gifticon_id % 10000
    
    gift_code = f"{yymm}{store_part:04d}{user_part:04d}{seq:04d}"
    
    # 4-4-4-4 형식으로 포맷팅
    formatted_code = f"{gift_code[:4]}-{gift_code[4:8]}-{gift_code[8:12]}-{gift_code[12:16]}"
    return formatted_code

def _request_payletter_url(gifticon, user_id: int, order_no: str) -> dict:
    """페이레터에 결제 URL 발급 요청. 성공 시 pl_data 반환, 실패 시 HTTPException."""
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    try:
        cursor.execute("SELECT menu_name FROM menu WHERE id = %s", (gifticon.menu_id,))
        row = cursor.fetchone()
        product_name = row["menu_name"] if row else "기프티콘"
    finally:
        cursor.close()
        close_db_connection(connection)

    if gifticon.pgcode not in VALID_PGCODES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"유효하지 않은 pgcode입니다: {gifticon.pgcode}"
        )
    is_naverpay = gifticon.pgcode == "naverpay"
    pl_client_id = settings.payletter_naver_client_id if is_naverpay else settings.payletter_client_id
    pl_api_key = settings.payletter_naver_payment_api_key if is_naverpay else settings.payletter_payment_api_key

    payload = {
        "pgcode": gifticon.pgcode,
        "client_id": pl_client_id,
        "user_id": str(user_id),
        "user_name": gifticon.sender,
        "order_no": order_no,
        "amount": gifticon.total_price,
        "product_name": product_name,
        "service_name": "gifnut",
        "return_url": settings.payletter_return_url,
        "callback_url": settings.payletter_callback_url,
        "cancel_url": settings.payletter_cancel_url,
    }
    pl_conn = http.client.HTTPSConnection(settings.payletter_api_host, timeout=10)
    try:
        pl_conn.request(
            "POST", "/v1.0/payments/request",
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            {"Authorization": f"PLKEY {pl_api_key}", "Content-Type": "application/json; charset=utf-8"}
        )
        pl_res = pl_conn.getresponse()
        pl_data = json.loads(pl_res.read().decode("utf-8"))
    except (TimeoutError, OSError) as e:
        logger.error(f"Payletter request timeout/network error: {e}")
        log_external_api_error("Payletter", "결제 URL 요청 타임아웃/네트워크 오류", e)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="결제 요청 시간이 초과되었습니다. 잠시 후 다시 시도해주세요."
        )
    finally:
        pl_conn.close()

    if pl_res.status != 200 or not pl_data.get("token"):
        logger.error(f"Payletter request failed: {pl_data}")
        log_external_api_error("Payletter", f"결제 URL 발급 실패: {pl_data.get('message', '')}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"결제 요청 실패: {pl_data.get('message', '페이레터 오류')}"
        )
    return pl_data


# S3 설정은 app.s3_config에서 가져옴
s3 = S3_CLIENT
bucket_name = BUCKET_NAME

@router.get("/list/{user_id}")
def getOrderList(user_id: int, user=Depends(verify_firebase_token)):
    connection = get_db_connection()  # 환경에 맞는 DB 연결
    cursor = connection.cursor(pymysql.cursors.DictCursor) # DB에 접속 및 DB 객체를 가져옴

    try:
        if user is not None:
            uid = user.get("uid")
            cursor.execute("SELECT id FROM user WHERE uid = %s LIMIT 1", (uid,))
            db_user = cursor.fetchone()
            if not db_user or db_user["id"] != user_id:
                raise HTTPException(status_code=403, detail="Forbidden")
        # orders 테이블과 store, gifticon, menu를 조인하여 주문 목록 조회
        # status가 COMPLETED 또는 REFUNDED인 것만 조회
        query = """
            SELECT DISTINCT
                o.id AS order_id,
                o.store_id,
                o.order_no AS order_number,
                g.sender,
                o.created_at AS created_time,
                o.amount AS price,
                s.store_name AS name,
                o.status,
                o.payment,
                m.menu_name
            FROM orders o
            JOIN store s ON o.store_id = s.id
            LEFT JOIN orders_gifticon og ON o.id = og.order_id
            LEFT JOIN gifticon g ON og.gifticon_id = g.id
            LEFT JOIN menu m ON g.menu_id = m.id
            WHERE o.user_id = %s
            AND o.status IN ('COMPLETED', 'REFUNDED')
            ORDER BY o.created_at DESC
        """
        
        cursor.execute(query, (user_id,))
        rows = cursor.fetchall()
        
        order_list = []
        for row in rows:
            order = {
                "order_id": row['order_id'],
                "store_id": row['store_id'],
                "order_number": row['order_number'],
                "sender": row['sender'] if row['sender'] else "",
                "price": row['price'] if row['price'] else 0,
                "menu_name": row['menu_name'] if row['menu_name'] else "",
                "payment": row['payment'] if row['payment'] else "",
                "status": row['status'] if row['status'] else "",
                "created_time": row['created_time'].isoformat() if row['created_time'] else None

            }
            order_list.append(order)
        print("order_list", order_list)
        
        return {"order_list": order_list}
        
    except Exception as e:
        traceback.print_exc()
        raise InternalError(e, "getOrderList")

    finally:        
        cursor.close()
        close_db_connection(connection)


@router.post("/{user_id}/payment-url")
def requestPaymentUrl(user_id: int, gifticon: Gifticon, user=Depends(verify_firebase_token)):
    """
    주문 등록 후 페이레터 결제 요청 URL을 발급하는 API.
    1. 주문/기프티콘 DB 등록 (PENDING)
    2. 페이레터 /v1.0/payments/request 호출
    3. 결제 URL(online_url, app_scheme) 반환
    페이레터 요청 실패 시 생성된 주문/기프티콘 rollback.
    """
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)

    order_id = None

    try:
        if user is not None:
            uid = user.get("uid")
            cursor.execute("SELECT id FROM user WHERE uid = %s LIMIT 1", (uid,))
            db_user = cursor.fetchone()
            if not db_user or db_user["id"] != user_id:
                raise HTTPException(status_code=403, detail="Forbidden")

        # 1. idempotency_key 기반 중복 체크
        if gifticon.idempotency_key:
            cursor.execute("""
                SELECT o.id, o.order_no, o.status, og.gifticon_id
                FROM orders o
                LEFT JOIN orders_gifticon og ON o.id = og.order_id
                WHERE o.idempotency_key = %s
                LIMIT 1
            """, (gifticon.idempotency_key,))
            existing = cursor.fetchone()
            if existing:
                if existing['status'] == 'COMPLETED':
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="이미 결제 완료된 주문입니다."
                    )
                if existing['status'] == 'EXPIRED':
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="만료된 주문입니다. 새로 주문해 주세요."
                    )
                # PENDING: 결제수단이 바뀌었을 수 있으므로 pgcode/payment 갱신 후 페이레터 URL 재발급
                cursor.execute(
                    "UPDATE orders SET pgcode = %s, payment = %s WHERE id = %s",
                    (gifticon.pgcode, gifticon.payment, existing['id'])
                )
                connection.commit()

                pl_data = _request_payletter_url(
                    gifticon, user_id, existing['order_no']
                )
                return {
                    "order_id": existing['id'],
                    "order_no": existing['order_no'],
                    "gifticon_id": existing['gifticon_id'],
                    "online_url": pl_data.get("online_url"),
                    "mobile_url": pl_data.get("mobile_url"),
                    "token": pl_data.get("token"),
                }

        cursor.close()
        cursor = connection.cursor()

        # 2. 주문번호 생성
        order_no = generate_order_no(connection)

        # 3~7. orders, gifticon, gift_code, orders_gifticon을 하나의 트랜잭션으로 처리
        connection.begin()

        # 3. orders INSERT (PENDING)
        cursor.execute(
            """INSERT INTO `orders` (store_id, user_id, payment_key, amount, status, order_no, payment, pgcode, idempotency_key)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (gifticon.store_id, user_id, None, gifticon.total_price, 'PENDING', order_no, gifticon.payment,
             gifticon.pgcode, gifticon.idempotency_key)
        )
        order_id = cursor.lastrowid

        # 4. 발급 시점 메뉴 정보 스냅샷 조회
        cursor.execute(
            "SELECT menu_name, price, description, image_key FROM menu WHERE id = %s",
            (gifticon.menu_id,)
        )
        menu_row = cursor.fetchone()
        if not menu_row:
            connection.rollback()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Menu not found"
            )
        menu_name_snapshot = menu_row['menu_name']
        price_snapshot = menu_row['price']
        description_snapshot = menu_row['description']
        image_key_snapshot = menu_row['image_key']

        # 5. gifticon INSERT (status='PENDING': 결제 완료 콜백에서 UNUSED로 전환)
        # purchaser_refund_deadline: 구매자 100% 환불 마감일을 발급 시점 정책(60일)으로 고정 저장
        purchaser_refund_deadline = (get_kst_now() + timedelta(days=60)).date()
        cursor.execute(
            """INSERT INTO gifticon (user_id, type, sender, receiver, receiver_phone, menu_id, store_id, order_id, status,
                                      menu_name_snapshot, price_snapshot, description_snapshot, image_key_snapshot, purchaser_refund_deadline)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'PENDING', %s, %s, %s, %s, %s)""",
            (user_id, gifticon.type, gifticon.sender, gifticon.receiver,
             gifticon.receiver_phone_number, gifticon.menu_id, gifticon.store_id, order_id,
             menu_name_snapshot, price_snapshot, description_snapshot, image_key_snapshot, purchaser_refund_deadline)
        )
        gifticon_id = cursor.lastrowid

        # 6. gift_code 생성 (중복 방지 재시도)
        gift_code = None
        for retry in range(10):
            try:
                gift_code = generate_gift_code(connection, cursor, gifticon.store_id, user_id, gifticon_id + retry)
                cursor.execute(
                    "UPDATE gifticon SET gift_code = %s WHERE id = %s AND (gift_code IS NULL OR gift_code = '')",
                    (gift_code, gifticon_id)
                )
                if cursor.rowcount > 0:
                    break
                cursor.execute("SELECT gift_code FROM gifticon WHERE id = %s", (gifticon_id,))
                row = cursor.fetchone()
                if row and row[0]:
                    gift_code = row[0]
                    break
            except pymysql.IntegrityError:
                if retry >= 9:
                    raise HTTPException(status_code=500, detail="Failed to generate unique gift code")

        if not gift_code:
            raise HTTPException(status_code=500, detail="Failed to generate gift code")

        # 7. orders_gifticon INSERT
        receiver_id = None if gifticon.type == 2 else user_id
        if receiver_id is not None:
            cursor.execute("UPDATE gifticon SET receiver_id = %s WHERE id = %s", (receiver_id, gifticon_id))
        cursor.execute(
            "INSERT INTO orders_gifticon (user_id, receiver_id, order_id, menu_id, gifticon_id, store_id) VALUES (%s, %s, %s, %s, %s, %s)",
            (user_id, receiver_id, order_id, gifticon.menu_id, gifticon_id, gifticon.store_id)
        )
        connection.commit()

        # 8. 페이레터 결제 URL 발급
        pl_data = _request_payletter_url(gifticon, user_id, order_no)

        return {
            "order_id": order_id,
            "order_no": order_no,
            "gifticon_id": gifticon_id,
            "online_url": pl_data.get("online_url"),
            "mobile_url": pl_data.get("mobile_url"),
            "token": pl_data.get("token"),
        }

    except HTTPException:
        connection.rollback()
        raise
    except Exception as e:
        connection.rollback()
        traceback.print_exc()
        raise InternalError(e, "requestPaymentUrl")
    finally:
        cursor.close()
        close_db_connection(connection)


@router.api_route("/payment/return", methods=["GET", "POST"])
def paymentReturn(request: Request):
    """
    페이레터 결제 완료/실패 후 리다이렉트 엔드포인트.
    쿼리파라미터를 그대로 앱 딥링크로 포워딩.
    """
    params = str(request.query_params)
    return RedirectResponse(url=f"gifnut://payment/result?{params}", status_code=302)


@router.api_route("/payment/cancel", methods=["GET", "POST"])
def paymentCancel(request: Request):
    """
    페이레터 결제 취소 후 리다이렉트 엔드포인트.
    쿼리파라미터를 그대로 앱 딥링크로 포워딩.
    """
    params = str(request.query_params)
    return RedirectResponse(url=f"gifnut://payment/cancel?{params}", status_code=302)


@router.post("/payment/result")
async def updatePaymentResult(request: Request):
    """
    페이레터 결제 결과 콜백 API
    payhash 검증 후 주문 상태를 COMPLETED로 업데이트
    성공 시 {"code": 0, "message": "success"} 반환 (페이레터 규격)
    """
    data = await request.json()
    user_id = data.get("user_id", "")
    amount = data.get("amount", 0)
    tid = data.get("tid", "")
    order_no = data.get("order_no", "")
    payhash = data.get("payhash", "")
    pay_info = data.get("pay_info", "")

    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)

    try:
        # 1. order_no로 주문 조회 (pgcode 포함)
        cursor.execute('''SELECT id, status, pgcode FROM orders WHERE order_no=%s''', (order_no,))
        order = cursor.fetchone()

        if not order:
            return {"code": 0, "message": "success"}

        # 2. payhash 검증: pgcode에 따라 올바른 API 키 선택
        is_naverpay = order.get("pgcode") == "naverpay"
        api_key = settings.payletter_naver_payment_api_key if is_naverpay else settings.payletter_payment_api_key
        expected_hash = hashlib.sha256(
            (user_id + str(amount) + tid + api_key).encode("utf-8")
        ).hexdigest().upper()

        if payhash != expected_hash:
            logger.warning(f"Payletter payhash mismatch for order_no {order_no}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid payhash"
            )

        if order["status"] == "COMPLETED":
            return {"code": 0, "message": "success"}

        order_id = order["id"]
        new_status = 'COMPLETED'

        # 3. order 테이블 업데이트 (tid를 payment_key에, 실제 결제수단을 payment에 저장)
        cursor.execute(
            "UPDATE orders SET payment_key = %s, status = %s, payment = %s WHERE id = %s",
            (tid, new_status, pay_info, order_id)
        )

        # 4. 연결된 gifticon validity를 1년 후로 설정하고 status를 UNUSED로 변경
        cursor.execute('''
            SELECT gifticon_id
            FROM orders_gifticon
            WHERE order_id = %s
        ''', (order_id,))
        gifticon_rows = cursor.fetchall()

        validity_date = (get_kst_now() + timedelta(days=365)).date()
        for row in gifticon_rows:
            cursor.execute('''
                UPDATE gifticon
                SET validity = %s, status = 'UNUSED'
                WHERE id = %s
            ''', (validity_date, row['gifticon_id']))

        connection.commit()

        return {"code": 0, "message": "success"}

    except HTTPException:
        raise
    except Exception as e:
        connection.rollback()
        traceback.print_exc()
        raise InternalError(e, "updatePaymentResult")
    
    finally:
        cursor.close()
        close_db_connection(connection)


@router.get("/{order_id}/status")
def getOrderStatus(order_id: int, user=Depends(verify_firebase_token)):
    """
    order_id로 주문의 결제 상태(status)만 조회하는 경량 API.
    앱이 결제 웹뷰 복귀 후 결제 성공(COMPLETED) 여부를 폴링하는 용도.
    """
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)

    try:
        cursor.execute("SELECT id, user_id, status FROM orders WHERE id = %s", (order_id,))
        order = cursor.fetchone()

        if not order:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Order with id {order_id} not found"
            )

        # 소유자 검증
        if user is not None:
            uid = user.get("uid")
            cursor.execute("SELECT id FROM user WHERE uid = %s LIMIT 1", (uid,))
            db_user = cursor.fetchone()
            if not db_user or db_user["id"] != order["user_id"]:
                raise HTTPException(status_code=403, detail="Forbidden")

        return {"order_id": order["id"], "status": order["status"]}

    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise InternalError(e, "getOrderStatus")

    finally:
        cursor.close()
        close_db_connection(connection)


@router.get("/detail/{order_id}")
def getOrderDetail(order_id: int, user=Depends(verify_firebase_token)):
    """
    order_id로 주문 상세내역을 조회하는 API
    주문 정보, 매장 정보, 주문에 포함된 기프티콘 목록을 반환
    """
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        # 1. 주문 기본 정보 조회 (orders, store 조인)
        order_query = """
            SELECT 
                o.id AS order_id,
                o.order_no,
                o.user_id,
                o.store_id,
                o.amount,
                o.status,
                o.payment,
                o.payment_key,
                o.created_at,
                s.store_name,
                s.store_address,
                s.store_telephone
            FROM orders o
            JOIN store s ON o.store_id = s.id
            WHERE o.id = %s
        """
        cursor.execute(order_query, (order_id,))
        order = cursor.fetchone()
        
        if not order:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Order with id {order_id} not found"
            )
        
        # 2. 주문에 포함된 기프티콘 목록 조회
        gifticon_query = """
            SELECT 
                g.id AS gifticon_id,
                g.gift_code,
                g.type,
                g.sender,
                g.receiver,
                g.receiver_phone,
                g.validity,
                g.created_at AS gifticon_created_at,
                g.image_key_snapshot,
                m.id AS menu_id,
                m.menu_name,
                m.price AS menu_price,
                og.menu_id,
                og.receiver_id AS orders_gifticon_receiver_id
            FROM orders_gifticon og
            JOIN gifticon g ON og.gifticon_id = g.id
            JOIN menu m ON g.menu_id = m.id
            WHERE og.order_id = %s
            ORDER BY g.created_at ASC
        """
        cursor.execute(gifticon_query, (order_id,))
        gifticon_rows = cursor.fetchall()
        
        print("gifticon_rows", gifticon_rows)
        # 3. 기프티콘 목록 구성
        gifticon_list = []
        for row in gifticon_rows:
            # 메뉴 이미지 URL 생성 (발급 시점 스냅샷 사용)
            image_key = row.get('image_key_snapshot') or ''
            menu_url = get_s3_public_url(bucket_name, image_key) if image_key else ''
            
            # orders_gifticon 테이블의 receiver_id가 비어있는지 확인
            is_receiver_linked = row['orders_gifticon_receiver_id'] is not None
            
            gifticon_item = {
                "gifticon_id": row['gifticon_id'],
                "gift_code": row['gift_code'],
                "type": row['type'],
                "sender": row['sender'],
                "receiver": row['receiver'],
                "receiver_phone": row['receiver_phone'],
                # 구매자 응답에는 기프티콘 개별 상태(사용여부/환불진행상태)를 노출하지 않음
                "validity": row['validity'].isoformat() if row['validity'] else None,
                "menu_id": row['menu_id'],
                "menu_name": row['menu_name'],
                "menu_price": row['menu_price'] if row['menu_price'] else 0,
                "menu_url": menu_url,
                "created_at": row['gifticon_created_at'].isoformat() if row['gifticon_created_at'] else None,
                "is_receiver_linked": is_receiver_linked
            }
            gifticon_list.append(gifticon_item)
        
        # 4. 응답 데이터 구성
        order_detail = {
            "order_id": order['order_id'],
            "order_no": order['order_no'],
            "user_id": order['user_id'],
            "store_id": order['store_id'],
            "store_name": order['store_name'],
            "store_address": order['store_address'],
            "store_telephone": order['store_telephone'],
            "amount": order['amount'],
            "status": order['status'],
            "payment": order['payment'],
            "created_at": order['created_at'].isoformat() if order['created_at'] else None,
            "gifticons": gifticon_list,
            "gifticon_count": len(gifticon_list)
        }
        
        return {"order_detail": order_detail}
        
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise InternalError(e, "getOrderDetail")
    
    finally:
        cursor.close()
        close_db_connection(connection)
        
# 기프티콘 환불 (60일 이내: 구매자 환불, 60일 이후: 수신자 환불 + 계좌정보). reason 저장 (60일 전/후 공통)
@router.post("/refund/{order_id}")
def refundGifticon(request: Request, order_id: int, body: Optional[RefundRequest] = None, user=Depends(verify_firebase_token)):
    """
    주문일(created_at) 기준 60일 이내: 구매자에게 토스 결제 취소 환불.
    주문일 기준 60일 이후: 수신자 환불(계좌정보 필수), 기프티콘만 무효화.
    """
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)

    try:
        # 1. 주문 조회 (id, payment_key, amount, created_at, status)
        cursor.execute(
            """SELECT id, user_id, payment_key, amount, created_at, status, pgcode FROM orders WHERE id=%s""",
            (order_id,),
        )
        order = cursor.fetchone()

        if not order:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Order with id {order_id} not found",
            )

        if user is not None:
            uid = user.get("uid")
            cursor.execute("SELECT id FROM user WHERE uid = %s LIMIT 1", (uid,))
            db_user = cursor.fetchone()
            if not db_user or db_user["id"] != order.get("user_id"):
                raise HTTPException(status_code=403, detail="Forbidden")

        if order.get("status") == "REFUNDED":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Order {order_id} is already refunded",
            )

        amount = int(order.get("amount") or 0)

        # 2. 연결된 기프티콘 조회
        cursor.execute(
            """SELECT gifticon_id FROM orders_gifticon WHERE order_id=%s""",
            (order_id,),
        )
        gifticon_rows = cursor.fetchall()
        gifticon_ids = [r["gifticon_id"] for r in gifticon_rows]

        # GNB-93: 이미 사용된(USED) 기프티콘이 있으면 환불 불가. 동시에 purchaser_refund_deadline 조회.
        gifticons = []
        if gifticon_ids:
            cursor.execute(
                "SELECT id, status, purchaser_refund_deadline FROM gifticon WHERE id IN ({})".format(
                    ','.join(['%s'] * len(gifticon_ids))
                ),
                gifticon_ids,
            )
            gifticons = cursor.fetchall()
            used_count = sum(1 for g in gifticons if g["status"] == "USED")
            if used_count > 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="이미 사용된 기프티콘이 포함되어 있어 환불할 수 없습니다.",
                )

        # GNB-195: 발급 시점에 저장된 purchaser_refund_deadline(gifticon)을 기준으로 판정.
        # NULL이 하나라도 있으면 환불 정책 자체가 없는 상품이므로 즉시 차단.
        if any(g["purchaser_refund_deadline"] is None for g in gifticons):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="이 상품은 환불이 불가능합니다.",
            )
        today = get_kst_now().date()
        purchaser_refund_deadline = gifticons[0]["purchaser_refund_deadline"] if gifticons else None
        # purchaser_refund_deadline = 발급일 + 60일(당일 미포함 cutoff). today가 이 날짜보다 이르면 구매자 환불 구간.
        within_purchaser_refund_period = purchaser_refund_deadline is not None and today < purchaser_refund_deadline

        if within_purchaser_refund_period:
            # 60일 이내: 구매자 환불 (페이레터 결제 취소)
            payment_key = order.get("payment_key")
            if not payment_key:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Payment key not found for order {order_id}",
                )

            # GNB-20: 중복 환불 차단
            # PROCESSING은 5분 이내인 경우만 유효로 간주 (크래시로 인한 영구 잠김 방지)
            cursor.execute(
                """
                SELECT id, status FROM refund
                WHERE order_id=%s
                  AND (status = 'COMPLETED'
                       OR (status = 'PROCESSING' AND created_at > NOW() - INTERVAL 5 MINUTE))
                LIMIT 1
                """,
                (order_id,),
            )
            existing_refund = cursor.fetchone()
            if existing_refund:
                existing_status = existing_refund.get("status")
                if existing_status == "PROCESSING":
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail="환불이 진행 중입니다. 잠시 후 다시 확인해주세요.",
                    )
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="이미 환불 완료된 주문입니다.",
                )

            # GNB-20: 페이레터 API 호출 전 PROCESSING 레코드 선삽입 (멱등성 키)
            reason = (body.reason or "")[:500] if body else None
            cursor.execute(
                """
                INSERT INTO refund (order_id, refund_type, original_amount, refunded_amount, fee_amount, status, refunded_at, reason)
                VALUES (%s, 'PURCHASER', %s, %s, 0, 'PROCESSING', NOW(), %s)
                """,
                (order_id, amount, amount, reason),
            )
            refund_id = cursor.lastrowid
            connection.commit()

            # orders.pgcode로 네이버페이 여부 판단
            is_naverpay_refund = order.get("pgcode") == "naverpay"
            refund_client_id = settings.payletter_naver_client_id if is_naverpay_refund else settings.payletter_client_id
            refund_api_key = settings.payletter_naver_payment_api_key if is_naverpay_refund else settings.payletter_payment_api_key

            # 페이레터 결제 취소 API 호출
            conn = http.client.HTTPSConnection(settings.payletter_api_host)
            client_ip = request.headers.get("X-Forwarded-For", request.client.host)
            payload_dict = {
                "client_id": refund_client_id,
                "tid": payment_key,
                "user_id": str(order.get("user_id")),
                "ip_addr": client_ip,
            }
            payload = json.dumps(payload_dict, ensure_ascii=False).encode("utf-8")
            headers = {
                "Authorization": f"PLKEY {refund_api_key}",
                "Content-Type": "application/json; charset=utf-8",
            }
            conn.request("POST", "/v1.0/payments/cancel", payload, headers)
            res = conn.getresponse()
            response_data = res.read().decode("utf-8")

            if res.status != 200:
                logger.error(f"Payletter cancel failed: {response_data}")
                # GNB-20: API 실패 시 FAILED로 기록하여 수동 처리 가능하도록 남김
                cursor.execute(
                    "UPDATE refund SET status='FAILED' WHERE id=%s",
                    (refund_id,),
                )
                connection.commit()
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Payment cancel failed: {response_data}",
                )

            cursor.execute(
                """UPDATE orders SET status='REFUNDED' WHERE id=%s""",
                (order_id,),
            )
            for gid in gifticon_ids:
                cursor.execute(
                    """UPDATE gifticon SET status='CANCELED' WHERE id=%s""",
                    (gid,),
                )
            cursor.execute(
                "UPDATE refund SET status='COMPLETED', refunded_at=NOW() WHERE id=%s",
                (refund_id,),
            )
            connection.commit()

            # 수신자 알림톡 발송 (커밋 완료 후, 실패해도 환불은 유지)
            if gifticon_ids:
                try:
                    cursor.execute(
                        """
                        SELECT g.receiver_phone, g.sender, m.menu_name, g.receiver
                        FROM gifticon g
                        JOIN menu m ON g.menu_id = m.id
                        WHERE g.id = %s
                        LIMIT 1
                        """,
                        (gifticon_ids[0],),
                    )
                    gift_info = cursor.fetchone()
                    if gift_info and gift_info.get("receiver_phone"):
                        send_gift_cancel_to_receiver(
                            receiver=gift_info["receiver_phone"],
                            sender=gift_info["sender"],
                            menu=gift_info["menu_name"],
                            recvname=gift_info.get("receiver", ""),
                        )
                except Exception as e:
                    logger.error(f"[알림톡] 선물 취소 알림톡 발송 실패 order_id={order_id}: {e}")

            return {
                "message": "구매자에게 환불되었습니다.",
                "order_id": order_id,
                "refund_type": "PURCHASER",
                "gifticons_canceled": len(gifticon_ids),
            }
        else:
            # 60일 경과: 구매자 환불 불가. 수신자가 /order/refund-request/{order_id}로 신청해야 함
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="환불 가능 기간(60일)이 지났습니다.",
            )

    except HTTPException:
        raise
    except Exception as e:
        connection.rollback()
        traceback.print_exc()
        raise InternalError(e, "refundGifticon")
    finally:
        cursor.close()
        close_db_connection(connection)


# 수신자 환불 신청 (60일 경과 후: 계좌정보 입력해 신청 접수, 관리자 수동 승인 후 완료)
@router.post("/refund-request/{order_id}")
def requestReceiverRefund(order_id: int, body: RefundRequest, user=Depends(verify_firebase_token)):
    """
    주문일(created_at) 기준 60일 경과 후, 기프티콘의 수신자(gifticon.user_id)가 계좌정보를 입력해
    환불을 신청하는 API. 나에게 선물하기(자가구매)의 경우 구매자 본인이 곧 수신자이므로 동일하게 호출한다.
    신청 시점에는 관리자 승인 대기 상태(REQUESTED)로만 접수되며, 실제 계좌이체는 관리자가 수동 처리한다.
    구매자에게는 신청~완료 전 구간 동안 orders.status가 그대로 유지되어 결제완료로만 보인다.
    """
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)

    try:
        cursor.execute(
            """SELECT id, user_id, amount, created_at, status FROM orders WHERE id=%s""",
            (order_id,),
        )
        order = cursor.fetchone()

        if not order:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Order with id {order_id} not found",
            )

        # 2. 연결된 기프티콘 조회
        cursor.execute(
            """SELECT gifticon_id FROM orders_gifticon WHERE order_id=%s""",
            (order_id,),
        )
        gifticon_rows = cursor.fetchall()
        gifticon_ids = [r["gifticon_id"] for r in gifticon_rows]

        if not gifticon_ids:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Order {order_id}에 연결된 기프티콘이 없습니다.",
            )

        # 3. 권한 검증: 호출자가 수신자(gifticon.receiver_id)인지 확인
        # 나에게 선물하기(자가구매)는 발신자=수신자이므로 이 조건을 그대로 통과한다.
        # 타인에게 선물한 경우에만 수신자(gifticon.receiver_id가 아닌 사람)가 걸러진다.
        cursor.execute(
            """SELECT id, receiver_id, status, purchaser_refund_deadline FROM gifticon WHERE id IN ({}) """.format(
                ','.join(['%s'] * len(gifticon_ids))
            ),
            gifticon_ids,
        )
        gifticons = cursor.fetchall()

        caller_id = None
        if user is not None:
            uid = user.get("uid")
            cursor.execute("SELECT id FROM user WHERE uid = %s LIMIT 1", (uid,))
            db_user = cursor.fetchone()
            caller_id = db_user["id"] if db_user else None

            if not caller_id or any(g["receiver_id"] != caller_id for g in gifticons):
                raise HTTPException(status_code=403, detail="Forbidden")

        # 4. 발급 시점에 저장된 purchaser_refund_deadline(gifticon) 기준으로 판정 (구매자 환불과 동일 기준)
        if any(g["purchaser_refund_deadline"] is None for g in gifticons):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="이 상품은 환불이 불가능합니다.",
            )
        today = get_kst_now().date()
        purchaser_refund_deadline = gifticons[0]["purchaser_refund_deadline"]
        within_purchaser_refund_period = today < purchaser_refund_deadline
        if within_purchaser_refund_period:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="아직 구매자 환불 가능 기간입니다. 60일이 지난 후 신청해주세요.",
            )

        # 5. 이미 사용된(USED) 기프티콘이 있으면 환불 불가
        if any(g["status"] == "USED" for g in gifticons):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="이미 사용된 기프티콘이 포함되어 있어 환불할 수 없습니다.",
            )

        # 6. 계좌정보 필수
        receiver_account = body.receiver_account if body else None
        if not receiver_account:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="환불 신청은 수신자 계좌정보(account_holder, bank_code, bank_name, account_number)가 필요합니다.",
            )

        # 7. 중복 신청/완료 방지. 기존 FAILED 건은 재사용(UNIQUE(order_id) 제약)
        cursor.execute(
            "SELECT id, status FROM refund WHERE order_id=%s LIMIT 1",
            (order_id,),
        )
        existing_refund = cursor.fetchone()
        if existing_refund and existing_refund["status"] in ("REQUESTED", "COMPLETED"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="이미 환불 신청이 접수되었거나 완료된 주문입니다.",
            )

        # 8. 금액 계산 (원금의 90% 지급, 10% 수수료 차감)
        original_amount = int(order.get("amount") or 0)
        refunded_amount = int(original_amount * 0.9)
        fee_amount = original_amount - refunded_amount
        reason = (body.reason or "")[:500] if body else None
        receiver_user_id = caller_id

        if existing_refund:
            # FAILED 건 재신청: 기존 레코드 재사용
            cursor.execute(
                """
                UPDATE refund SET
                    refund_type='RECEIVER', original_amount=%s, refunded_amount=%s, fee_amount=%s,
                    status='REQUESTED', refunded_at=NOW(), receiver_user_id=%s,
                    account_holder=%s, bank_code=%s, bank_name=%s, account_number=%s, reason=%s
                WHERE id=%s
                """,
                (
                    original_amount, refunded_amount, fee_amount, receiver_user_id,
                    receiver_account.account_holder.strip(),
                    receiver_account.bank_code.strip(),
                    receiver_account.bank_name.strip(),
                    receiver_account.account_number.strip(),
                    reason,
                    existing_refund["id"],
                ),
            )
        else:
            cursor.execute(
                """
                INSERT INTO refund (
                    order_id, refund_type, original_amount, refunded_amount, fee_amount, status, refunded_at,
                    receiver_user_id, account_holder, bank_code, bank_name, account_number, reason
                ) VALUES (%s, 'RECEIVER', %s, %s, %s, 'REQUESTED', NOW(), %s, %s, %s, %s, %s, %s)
                """,
                (
                    order_id, original_amount, refunded_amount, fee_amount, receiver_user_id,
                    receiver_account.account_holder.strip(),
                    receiver_account.bank_code.strip(),
                    receiver_account.bank_name.strip(),
                    receiver_account.account_number.strip(),
                    reason,
                ),
            )

        # orders.status는 변경하지 않는다 - 구매자에게는 계속 결제완료로 보여야 함
        for gid in gifticon_ids:
            cursor.execute(
                "UPDATE gifticon SET status='REFUND_REQUESTED' WHERE id=%s",
                (gid,),
            )
        connection.commit()

        return {
            "message": "환불 신청이 접수되었습니다.",
            "order_id": order_id,
            "refund_type": "RECEIVER",
            "status": "REQUESTED",
        }

    except HTTPException:
        raise
    except Exception as e:
        connection.rollback()
        traceback.print_exc()
        raise InternalError(e, "requestReceiverRefund")
    finally:
        cursor.close()
        close_db_connection(connection)


@router.post("/expire-pending")
def expirePendingOrders():
    """
    15분 이상 PENDING 상태인 주문을 EXPIRED로 전환하는 배치 엔드포인트.
    스케줄러 또는 관리자가 주기적으로 호출.
    """
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)

    try:
        cutoff = get_kst_now() - timedelta(minutes=15)
        cursor.execute(
            "SELECT id FROM orders WHERE status = 'PENDING' AND created_at <= %s",
            (cutoff,)
        )
        rows = cursor.fetchall()
        order_ids = [r["id"] for r in rows]

        if not order_ids:
            return {"expired_count": 0, "order_ids": []}

        fmt = ",".join(["%s"] * len(order_ids))
        cursor.execute(f"UPDATE orders SET status = 'EXPIRED' WHERE id IN ({fmt})", order_ids)
        connection.commit()

        logger.info(f"Expired {len(order_ids)} pending orders: {order_ids}")
        return {"expired_count": len(order_ids), "order_ids": order_ids}

    except Exception as e:
        connection.rollback()
        raise InternalError(e, "expirePendingOrders")
    finally:
        cursor.close()
        close_db_connection(connection)