from fastapi import APIRouter, HTTPException, status, Request, Form
from fastapi.responses import RedirectResponse
import traceback

from typing import Union, Optional
from pydantic import BaseModel
from loguru import logger

import pymysql
from db.session import get_db_connection
from datetime import datetime, timedelta, date, timezone
from core.s3_config import S3_CLIENT, BUCKET_NAME

from models.gifticon import Gifticon, PaymentResult, VALID_PGCODES
from models.store import StoreCreate
from crud import promotion as promotion_crud

import http.client
import json
import hashlib

from core.config import settings

router = APIRouter()


class RefundReceiverAccount(BaseModel):
    """수신자 환불 시 계좌정보 (7일 이후 환불일 때 필수)"""
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
    yyddd: 연중일수 (예: 2024년 1월 1일 = 24001, 12월 31일 = 24366)
    seq: 해당 날짜의 순번 (1부터 시작)
    """
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    try:
        today = get_kst_now()
        yyddd = today.strftime("%y") + str(today.timetuple().tm_yday).zfill(3)
        
        # 오늘 날짜의 주문 개수 조회하여 seq 계산 (PENDING/EXPIRED 제외)
        query = """
            SELECT COUNT(*) as cnt
            FROM orders
            WHERE DATE(created_at) = CURDATE()
            AND status NOT IN ('PENDING', 'EXPIRED')
        """
        cursor.execute(query)
        result = cursor.fetchone()
        seq = result['cnt'] + 1
        
        order_no = f"{yyddd}{seq + 5000:05d}"
        return order_no
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

# S3 설정은 app.s3_config에서 가져옴
s3 = S3_CLIENT
bucket_name = BUCKET_NAME

@router.get("/list/{user_id}")
def getOrderList(user_id: int):
    connection = get_db_connection()  # 환경에 맞는 DB 연결
    cursor = connection.cursor(pymysql.cursors.DictCursor) # DB에 접속 및 DB 객체를 가져옴
      
    try:
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
        print(f"Error during getOrderList: {e}")
        traceback.print_exc()
        logger.error(f"Error during getOrderList: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error during getOrderList: {str(e)}"
        )

    finally:        
        cursor.close()
        connection.close()

@router.post("/{user_id}")
def purchaseGifticon(user_id: int, gifticon: Gifticon):
    """
    결제 전 gifticon과 order 정보를 등록하는 API
    결제는 아직 진행되지 않았으므로 status는 PENDING으로 설정
    """
    connection = get_db_connection()  # 환경에 맞는 DB 연결
    cursor = connection.cursor(pymysql.cursors.DictCursor) # DB에 접속 및 DB 객체를 가져옴
      
    try:
        # 0. 중복 주문 체크 (결제 완료된 주문만 체크: payment_key가 있는 주문)
        # 결제 전(PENDING) 주문은 중복으로 간주하지 않음
        five_minutes_ago = get_kst_now() - timedelta(minutes=5)
        cursor.execute('''
            SELECT o.id, o.order_no, o.created_at, o.payment_key
            FROM orders o
            JOIN gifticon g ON o.id = g.order_id
            WHERE o.user_id = %s
            AND o.store_id = %s
            AND g.menu_id = %s
            AND o.amount = %s
            AND g.receiver = %s
            AND g.receiver_phone = %s
            AND o.payment_key IS NOT NULL
            AND o.created_at >= %s
            ORDER BY o.created_at DESC
            LIMIT 1
        ''', (
            user_id,
            gifticon.store_id,
            gifticon.menu_id,
            gifticon.total_price,
            gifticon.receiver,
            gifticon.receiver_phone_number,
            five_minutes_ago
        ))
        
        existing_order = cursor.fetchone()
        
        if existing_order:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="중복된 주문입니다. 최근 5분 내 동일한 결제 완료 주문이 존재합니다."
            )
        
        # 커서를 일반 cursor로 변경 (DictCursor는 조회용)
        cursor.close()
        cursor = connection.cursor()

        # 1. 주문번호 생성
        order_no = generate_order_no(connection)

        # 2~5. orders, gifticon, gift_code, orders_gifticon을 하나의 트랜잭션으로 처리
        connection.begin()

        # 2. Order 테이블에 데이터 삽입
        cursor.execute(
            """INSERT INTO `orders` (store_id, user_id, payment_key, amount, status, order_no, payment)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (gifticon.store_id, user_id, None, gifticon.total_price, 'PENDING', order_no, gifticon.payment)
        )
        order_id = cursor.lastrowid

        # 3. 구매 시점 수수료율 확정
        fee_info = promotion_crud.get_fee_info_for_order(gifticon.store_id, date.today())

        # 4. Gifticon 테이블에 데이터 삽입
        cursor.execute(
            """INSERT INTO gifticon (
                user_id, type, sender, receiver, receiver_phone, menu_id, store_id, order_id,
                base_fee_rate, applied_promo_id, applied_fee_rate
               ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                user_id, gifticon.type, gifticon.sender, gifticon.receiver,
                gifticon.receiver_phone_number, gifticon.menu_id, gifticon.store_id, order_id,
                fee_info['base_fee_rate'], fee_info['applied_promo_id'], fee_info['applied_fee_rate'],
            )
        )
        gifticon_id = cursor.lastrowid

        # 5. gift_code 생성 및 업데이트 (중복 방지 재시도)
        gift_code = None
        for retry_count in range(10):
            try:
                gift_code = generate_gift_code(connection, cursor, gifticon.store_id, user_id, gifticon_id + retry_count)
                cursor.execute(
                    "UPDATE gifticon SET gift_code = %s WHERE id = %s AND (gift_code IS NULL OR gift_code = '')",
                    (gift_code, gifticon_id)
                )
                if cursor.rowcount > 0:
                    break
                cursor.execute("SELECT gift_code FROM gifticon WHERE id = %s", (gifticon_id,))
                result = cursor.fetchone()
                if result and result[0]:
                    gift_code = result[0]
                    break
            except pymysql.IntegrityError as e:
                if "Duplicate entry" in str(e) or "gift_code" in str(e).lower():
                    if retry_count >= 9:
                        raise HTTPException(
                            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="Failed to generate unique gift code after multiple retries"
                        )
                else:
                    raise

        if not gift_code:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to generate gift code"
            )

        print(f"gifticon_id: {gifticon_id}, gift_code: {gift_code}, order_no: {order_no}")

        # 6. orders_gifticon 테이블에 데이터 삽입
        receiver_id = None if gifticon.type == 2 else user_id
        if receiver_id is not None:
            cursor.execute("UPDATE gifticon SET receiver_id = %s WHERE id = %s", (receiver_id, gifticon_id))
        cursor.execute(
            "INSERT INTO orders_gifticon (user_id, receiver_id, order_id, menu_id, gifticon_id, store_id) VALUES (%s, %s, %s, %s, %s, %s)",
            (user_id, receiver_id, order_id, gifticon.menu_id, gifticon_id, gifticon.store_id)
        )
        connection.commit()

        return {
            "message": "Order registered successfully. Please proceed with payment.",
            "order_id": order_id,
            "order_no": order_no,
            "gifticon_id": gifticon_id,
            "gift_code": gift_code
        }
    except HTTPException:
        connection.rollback()
        raise
    except Exception as e:
        connection.rollback()
        print(f"Error during purchaseGifticon: {e}")
        traceback.print_exc()
        logger.error(f"Error during purchaseGifticon: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error during purchaseGifticon: {str(e)}"
        )

    finally:        
        cursor.close()
        connection.close()

@router.post("/{user_id}/payment-url")
def requestPaymentUrl(user_id: int, gifticon: Gifticon):
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
        # 1. 중복 주문 체크
        five_minutes_ago = get_kst_now() - timedelta(minutes=5)
        cursor.execute('''
            SELECT o.id FROM orders o
            JOIN gifticon g ON o.id = g.order_id
            WHERE o.user_id = %s AND o.store_id = %s AND g.menu_id = %s
            AND o.amount = %s AND g.receiver = %s AND g.receiver_phone = %s
            AND o.payment_key IS NOT NULL AND o.created_at >= %s
            ORDER BY o.created_at DESC LIMIT 1
        ''', (user_id, gifticon.store_id, gifticon.menu_id, gifticon.total_price,
              gifticon.receiver, gifticon.receiver_phone_number, five_minutes_ago))
        if cursor.fetchone():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="중복된 주문입니다. 최근 5분 내 동일한 결제 완료 주문이 존재합니다."
            )

        cursor.close()
        cursor = connection.cursor()

        # 2. 주문번호 생성
        order_no = generate_order_no(connection)

        # 3~7. orders, gifticon, gift_code, orders_gifticon을 하나의 트랜잭션으로 처리
        connection.begin()

        # 3. orders INSERT (PENDING)
        cursor.execute(
            """INSERT INTO `orders` (store_id, user_id, payment_key, amount, status, order_no, payment)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (gifticon.store_id, user_id, None, gifticon.total_price, 'PENDING', order_no, gifticon.payment)
        )
        order_id = cursor.lastrowid

        # 4. 구매 시점 수수료율 확정 (기본 수수료율 + 프로모션 적용)
        fee_info = promotion_crud.get_fee_info_for_order(gifticon.store_id, date.today())

        # 5. gifticon INSERT
        cursor.execute(
            """INSERT INTO gifticon (user_id, type, sender, receiver, receiver_phone, menu_id, store_id, order_id,
                base_fee_rate, applied_promo_id, applied_fee_rate)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (user_id, gifticon.type, gifticon.sender, gifticon.receiver,
             gifticon.receiver_phone_number, gifticon.menu_id, gifticon.store_id, order_id,
             fee_info['base_fee_rate'], fee_info['applied_promo_id'], fee_info['applied_fee_rate'])
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

        # 8. 메뉴명 조회 (페이레터 product_name용)
        cursor.execute("SELECT menu_name FROM menu WHERE id = %s", (gifticon.menu_id,))
        menu_row = cursor.fetchone()
        product_name = menu_row["menu_name"] if menu_row else "기프티콘"

        # 9. 페이레터 결제 요청
        if gifticon.pgcode not in VALID_PGCODES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"유효하지 않은 pgcode입니다: {gifticon.pgcode}"
            )
        is_naverpay = gifticon.pgcode == "naverpay"
        pl_client_id = settings.payletter_naver_client_id if is_naverpay else settings.payletter_client_id
        pl_api_key = settings.payletter_naver_payment_api_key if is_naverpay else settings.payletter_payment_api_key

        payletter_payload = {
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
        pl_conn = http.client.HTTPSConnection(settings.payletter_api_host)
        pl_conn.request(
            "POST",
            "/v1.0/payments/request",
            json.dumps(payletter_payload, ensure_ascii=False).encode("utf-8"),
            {
                "Authorization": f"PLKEY {pl_api_key}",
                "Content-Type": "application/json; charset=utf-8",
            }
        )
        pl_res = pl_conn.getresponse()
        pl_data = json.loads(pl_res.read().decode("utf-8"))

        if pl_res.status != 200 or not pl_data.get("token"):
            logger.error(f"Payletter request failed: {pl_data}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"결제 요청 실패: {pl_data.get('message', '페이레터 오류')}"
            )

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
        logger.error(f"Error during requestPaymentUrl: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error during requestPaymentUrl: {str(e)}")
    finally:
        cursor.close()
        connection.close()


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

    # 1. payhash 검증: SHA256(user_id + amount + tid + API_Key) 대문자
    expected_hash = hashlib.sha256(
        (user_id + str(amount) + tid + settings.payletter_payment_api_key).encode("utf-8")
    ).hexdigest().upper()

    if payhash != expected_hash:
        logger.warning(f"Payletter payhash mismatch for order_no {order_no}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid payhash"
        )

    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)

    try:
        # 2. order_no로 주문 조회
        cursor.execute('''SELECT id, status FROM orders WHERE order_no=%s''', (order_no,))
        order = cursor.fetchone()

        if not order:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Order with order_no {order_no} not found"
            )

        order_id = order["id"]
        new_status = 'COMPLETED'

        # 3. order 테이블 업데이트 (tid를 payment_key에 저장)
        cursor.execute(
            "UPDATE orders SET payment_key = %s, status = %s WHERE id = %s",
            (tid, new_status, order_id)
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
        print(f"Error during updatePaymentResult: {e}")
        traceback.print_exc()
        logger.error(f"Error during updatePaymentResult: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error during updatePaymentResult: {str(e)}"
        )
    
    finally:
        cursor.close()
        connection.close()
        
@router.get("/detail/{order_id}")
def getOrderDetail(order_id: int):
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
                g.status AS gifticon_status,
                g.validity,
                g.created_at AS gifticon_created_at,
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
            # 메뉴 이미지 URL 생성
            menu_url = None
            try:
                menu_url = s3.generate_presigned_url('get_object',
                    Params={'Bucket': bucket_name,
                            'Key': f'menu/menu_{order["store_id"]}_{row["menu_id"]}.png'},
                    ExpiresIn=3600)
            except Exception as e:
                print(f"Error generating menu URL: {e}")
                menu_url = None
            
            # orders_gifticon 테이블의 receiver_id가 비어있는지 확인
            is_receiver_linked = row['orders_gifticon_receiver_id'] is not None
            
            gifticon_item = {
                "gifticon_id": row['gifticon_id'],
                "gift_code": row['gift_code'],
                "type": row['type'],
                "sender": row['sender'],
                "receiver": row['receiver'],
                "receiver_phone": row['receiver_phone'],
                "status": row['gifticon_status'],
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
        print(f"Error during getOrderDetail: {e}")
        traceback.print_exc()
        logger.error(f"Error during getOrderDetail: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error during getOrderDetail: {str(e)}"
        )
    
    finally:
        cursor.close()
        connection.close()
        
# 기프티콘 환불 (7일 이내: 구매자 환불, 7일 이후: 수신자 환불 + 계좌정보). reason 저장 (7일 전/후 공통)
@router.post("/refund/{order_id}")
def refundGifticon(request: Request, order_id: int, body: Optional[RefundRequest] = None):
    """
    주문일(created_at) 기준 7일 이내: 구매자에게 토스 결제 취소 환불.
    주문일 기준 7일 이후: 수신자 환불(계좌정보 필수), 기프티콘만 무효화.
    """
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)

    try:
        # 1. 주문 조회 (id, payment_key, amount, created_at, status)
        cursor.execute(
            """SELECT id, user_id, payment_key, amount, created_at, status FROM orders WHERE id=%s""",
            (order_id,),
        )
        order = cursor.fetchone()

        if not order:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Order with id {order_id} not found",
            )

        if order.get("status") == "REFUNDED":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Order {order_id} is already refunded",
            )

        order_created = order["created_at"]
        if hasattr(order_created, "date"):
            order_date = order_created.date()
        else:
            order_date = order_created
        today = get_kst_now().date()
        cutoff_date = order_date + timedelta(days=7)
        within_7_days = today <= cutoff_date

        amount = int(order.get("amount") or 0)

        # 2. 연결된 기프티콘 조회
        cursor.execute(
            """SELECT gifticon_id FROM orders_gifticon WHERE order_id=%s""",
            (order_id,),
        )
        gifticon_rows = cursor.fetchall()
        gifticon_ids = [r["gifticon_id"] for r in gifticon_rows]

        if within_7_days:
            # 7일 이내: 구매자 환불 (토스 결제 취소)
            payment_key = order.get("payment_key")
            if not payment_key:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Payment key not found for order {order_id}",
                )

            # 기프티콘에서 pgcode 조회 (네이버페이 키 분기용)
            refund_pgcode = ""
            if gifticon_ids:
                cursor.execute("SELECT pgcode FROM gifticon WHERE id=%s", (gifticon_ids[0],))
                g_row = cursor.fetchone()
                if g_row:
                    refund_pgcode = g_row.get("pgcode", "")

            is_naverpay_refund = refund_pgcode == "naverpay"
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

            reason = (body.reason or "")[:500] if body else None
            cursor.execute(
                """
                INSERT INTO refund (order_id, refund_type, amount, status, refunded_at, reason)
                VALUES (%s, 'PURCHASER', %s, 'COMPLETED', NOW(), %s)
                """,
                (order_id, amount, reason),
            )
            connection.commit()

            return {
                "message": "구매자에게 환불되었습니다.",
                "order_id": order_id,
                "refund_type": "PURCHASER",
                "gifticons_canceled": len(gifticon_ids),
            }
        else:
            # 7일 이후: 수신자 환불 (계좌정보 필수)
            receiver_account = body.receiver_account if body else None
            if not receiver_account:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="7일 이후 환불은 수신자 계좌정보(account_holder, bank_code, bank_name, account_number)가 필요합니다.",
                )

            # 수신자 user_id (해당 주문 기프티콘 중 하나의 user_id)
            receiver_user_id = None
            if gifticon_ids:
                cursor.execute(
                    """SELECT user_id FROM gifticon WHERE id=%s LIMIT 1""",
                    (gifticon_ids[0],),
                )
                row = cursor.fetchone()
                if row:
                    receiver_user_id = row.get("user_id")

            cursor.execute(
                """UPDATE orders SET status='REFUNDED' WHERE id=%s""",
                (order_id,),
            )
            for gid in gifticon_ids:
                cursor.execute(
                    """UPDATE gifticon SET status='CANCELED' WHERE id=%s""",
                    (gid,),
                )

            reason = (body.reason or "")[:500] if body else None
            cursor.execute(
                """
                INSERT INTO refund (
                    order_id, refund_type, amount, status, refunded_at,
                    receiver_user_id, account_holder, bank_code, bank_name, account_number, reason
                ) VALUES (%s, 'RECEIVER', %s, 'COMPLETED', NOW(), %s, %s, %s, %s, %s, %s)
                """,
                (
                    order_id,
                    amount,
                    receiver_user_id,
                    receiver_account.account_holder.strip(),
                    receiver_account.bank_code.strip(),
                    receiver_account.bank_name.strip(),
                    receiver_account.account_number.strip(),
                    reason,
                ),
            )
            connection.commit()

            return {
                "message": "수신자 계좌로 환불 예정입니다.",
                "order_id": order_id,
                "refund_type": "RECEIVER",
                "gifticons_canceled": len(gifticon_ids),
            }

    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        logger.error(f"refund gifticon: {str(e)}")
        connection.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"failed refund gifticon: {str(e)}",
        )
    finally:
        cursor.close()
        connection.close()


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
        logger.error(f"Error during expirePendingOrders: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error during expirePendingOrders: {str(e)}")
    finally:
        cursor.close()
        connection.close()