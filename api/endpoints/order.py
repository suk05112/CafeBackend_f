from fastapi import APIRouter, HTTPException, status
from fastapi import FastAPI
import traceback

from typing import Union, Optional
from pydantic import BaseModel
from loguru import logger

import pymysql
from db.session import get_db_connection
from datetime import datetime, timedelta, date, timezone
from core.s3_config import S3_CLIENT, BUCKET_NAME

from models.gifticon import Gifticon, PaymentResult
from models.store import StoreCreate
from crud import settlement as settlement_crud
from crud import promotion as promotion_crud

import http.client
import json

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
        
        # 오늘 날짜의 주문 개수 조회하여 seq 계산
        query = """
            SELECT COUNT(*) as cnt 
            FROM orders 
            WHERE DATE(created_at) = CURDATE()
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
        
        # 2. Order 테이블에 데이터 삽입 (결제 전이므로 payment_key는 NULL, status는 PENDING)
        order_query = """
            INSERT INTO `orders` (
                store_id, user_id, payment_key, amount, status, order_no, payment
            ) VALUES (%s, %s, %s, %s, %s, %s, %s);
        """
        cursor.execute(
            order_query,
            (
                gifticon.store_id,
                user_id,
                None,  # 결제 전이므로 payment_key는 NULL
                gifticon.total_price,
                'PENDING',  # 결제 전이므로 PENDING 상태
                order_no,
                gifticon.payment  # gifticon.payment 값 저장
            )
        )
        connection.commit()
        order_id = cursor.lastrowid

        # 3. 현재 수수료율 조회 (기본 수수료율, 프로모션은 사용 시점에 적용)
        # 생성 시점에는 기본 수수료율 저장
        current_fee_rate = 3.00  # 기본값
        try:
            cursor.execute("SELECT base_fee_rate FROM platform_config WHERE config_id = 1")
            config = cursor.fetchone()
            if config:
                current_fee_rate = float(config['base_fee_rate'])
        except Exception as e:
            # platform_config 테이블이 없으면 기본값 사용
            logger.warning(f"platform_config 테이블 조회 실패, 기본 수수료율 사용: {str(e)}")
            current_fee_rate = 3.00
        
        # 4. Gifticon 테이블에 데이터 삽입 (order_id 포함, gift_code는 나중에 업데이트, applied_fee_rate 저장)
        # gifticon 테이블에는 total_price 컬럼이 없으므로 제외
        query = """
            INSERT INTO gifticon (
                user_id, type, sender, receiver, receiver_phone, menu_id, store_id, order_id, applied_fee_rate
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s);
        """
        cursor.execute(
            query,
            (
                user_id,
                gifticon.type,
                gifticon.sender,
                gifticon.receiver,
                gifticon.receiver_phone_number,
                gifticon.menu_id,
                gifticon.store_id,
                order_id,  # order_id 추가
                current_fee_rate,  # applied_fee_rate 저장
            )
        )
        connection.commit()
        gifticon_id = cursor.lastrowid
        
        # 4. 기프티콘 번호 생성 및 업데이트 (중복 방지 로직 포함)
        max_retries = 10
        retry_count = 0
        gift_code = None
        
        while retry_count < max_retries:
            try:
                # 기프티콘 번호 생성
                gift_code = generate_gift_code(connection, cursor, gifticon.store_id, user_id, gifticon_id + retry_count)
                
                # gift_code 업데이트 시도
                update_query = """
                    UPDATE gifticon 
                    SET gift_code = %s 
                    WHERE id = %s AND (gift_code IS NULL OR gift_code = '')
                """
                cursor.execute(update_query, (gift_code, gifticon_id))
                
                if cursor.rowcount > 0:
                    connection.commit()
                    break
                else:
                    # 이미 gift_code가 설정되어 있으면 조회
                    check_query = "SELECT gift_code FROM gifticon WHERE id = %s"
                    cursor.execute(check_query, (gifticon_id,))
                    result = cursor.fetchone()
                    if result and result[0]:
                        gift_code = result[0]
                        break
                    
                    # 재시도
                    retry_count += 1
                    
            except pymysql.IntegrityError as e:
                # UNIQUE 제약조건 위반 시 재시도
                if "Duplicate entry" in str(e) or "gift_code" in str(e).lower():
                    retry_count += 1
                    if retry_count >= max_retries:
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

        # 5. Order_Gifticon 테이블에 데이터 삽입
        # user_id는 항상 설정, type이 2이면 receiver_id를 NULL로 설정 (선물하기인 경우)
        receiver_id = None if gifticon.type == 2 else user_id
        
        # receiver_id가 user_id로 설정되는 경우 (type != 2), gifticon 테이블의 receiver_id도 업데이트
        if receiver_id is not None:
            update_gifticon_query = """
                UPDATE gifticon 
                SET receiver_id = %s 
                WHERE id = %s
            """
            cursor.execute(update_gifticon_query, (receiver_id, gifticon_id))
        
        order_gifticon_query = """
            INSERT INTO orders_gifticon (
                user_id, receiver_id, order_id, menu_id, gifticon_id
            ) VALUES (%s, %s, %s, %s, %s);
        """
        cursor.execute(
            order_gifticon_query,
            (
                user_id,
                receiver_id,
                order_id,
                gifticon.menu_id,
                gifticon_id,
            )
        )
        connection.commit()
        
        # 6. 정산 정보 생성/업데이트 (건별 + 월별)
        try:
            order_datetime = get_kst_now()  # 주문 일시 (한국 시간)
            settlement_crud.update_settlement_on_order(
                connection=connection,
                order_id=order_id,
                store_id=gifticon.store_id,
                order_amount=float(gifticon.total_price),
                order_date=order_datetime,
                commission_rate=6.9  # 수수료율 6.9%
            )
        except Exception as settlement_error:
            # 정산 정보 생성 실패해도 주문은 성공한 것으로 처리
            logger.warning(f"Failed to create settlement info for order {order_id}: {str(settlement_error)}")

        return {
            "message": "Order registered successfully. Please proceed with payment.",
            "order_id": order_id,
            "order_no": order_no,
            "gifticon_id": gifticon_id,
            "gift_code": gift_code
        }
    except Exception as e:
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

@router.post("/payment/result")
def updatePaymentResult(payment_result: PaymentResult):
    """
    결제 결과를 받아서 order의 payment_key와 status를 업데이트하는 API
    결제 성공 시: status = COMPLETED
    결제 실패 시: status = UNKNOWN
    """
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        # 1. order_id로 주문 정보 확인
        cursor.execute('''SELECT id, status FROM orders WHERE id=%s''', (payment_result.order_id,))
        order = cursor.fetchone()
        
        if not order:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Order with id {payment_result.order_id} not found"
            )
        
        # 2. 결제 결과에 따라 status 설정
        if payment_result.is_success:
            new_status = 'COMPLETED'
        else:
            new_status = 'UNKNOWN'
        
        # 3. order 테이블 업데이트 (payment_key와 status)
        update_query = """
            UPDATE orders 
            SET payment_key = %s, status = %s 
            WHERE id = %s
        """
        cursor.execute(
            update_query,
            (
                payment_result.payment_key,
                new_status,
                payment_result.order_id
            )
        )
        connection.commit()
        
        # 4. 결제 성공 시 해당 주문과 연결된 gifticon의 validity를 1년 후로 설정하고 status를 USED로 변경
        if payment_result.is_success:
            # order_id로 연결된 gifticon_id 조회
            cursor.execute('''
                SELECT gifticon_id 
                FROM orders_gifticon 
                WHERE order_id = %s
            ''', (payment_result.order_id,))
            gifticon_rows = cursor.fetchall()
            
            # 오늘로부터 1년 후 날짜 계산 (시간 제외, 날짜만) - 한국 시간 기준
            validity_date = (get_kst_now() + timedelta(days=365)).date()
            
            # 각 gifticon의 validity와 status 업데이트
            for row in gifticon_rows:
                gifticon_id = row['gifticon_id']
                cursor.execute('''
                    UPDATE gifticon 
                    SET validity = %s, status = 'UNUSED'
                    WHERE id = %s
                ''', (validity_date, gifticon_id))
            
            connection.commit()
            
            # 5. 결제 성공 시 정산 정보도 업데이트 (주문 상태가 COMPLETED로 변경되므로)
            try:
                # 주문 정보 조회
                cursor.execute('''SELECT store_id, amount, created_at FROM orders WHERE id = %s''', (payment_result.order_id,))
                order_info = cursor.fetchone()
                if order_info:
                    order_datetime = order_info['created_at'] if order_info.get('created_at') else get_kst_now()
                    settlement_crud.update_settlement_on_order(
                        connection=connection,
                        order_id=payment_result.order_id,
                        store_id=order_info['store_id'],
                        order_amount=float(order_info['amount'] or 0),
                        order_date=order_datetime,
                        commission_rate=6.9  # 수수료율 6.9%
                    )
            except Exception as settlement_error:
                # 정산 정보 업데이트 실패해도 결제 결과 업데이트는 성공한 것으로 처리
                logger.warning(f"Failed to update settlement info for order {payment_result.order_id}: {str(settlement_error)}")
        
        return {
            "message": f"Payment result updated successfully",
            "order_id": payment_result.order_id,
            "status": new_status,
            "payment_key": payment_result.payment_key
        }
        
    except HTTPException:
        raise
    except Exception as e:
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
def refundGifticon(order_id: int, body: Optional[RefundRequest] = None):
    """
    주문일(created_at) 기준 7일 이내: 구매자에게 토스 결제 취소 환불.
    주문일 기준 7일 이후: 수신자 환불(계좌정보 필수), 기프티콘만 무효화.
    """
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)

    try:
        # 1. 주문 조회 (id, payment_key, amount, created_at, status)
        cursor.execute(
            """SELECT id, payment_key, amount, created_at, status FROM orders WHERE id=%s""",
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

            conn = http.client.HTTPSConnection("api.tosspayments.com")
            payload_dict = {"cancelReason": "구매자 변심"}
            payload = json.dumps(payload_dict, ensure_ascii=False).encode("utf-8")
            headers = {
                "Authorization": "Basic dGVzdF9za196WExrS0V5cE5BcldtbzUwblgzbG1lYXhZRzVSOg==",
                "Content-Type": "application/json; charset=utf-8",
            }
            conn.request("POST", f"/v1/payments/{payment_key}/cancel", payload, headers)
            res = conn.getresponse()
            response_data = res.read().decode("utf-8")

            if res.status != 200:
                logger.error(f"Toss Payments cancel failed: {response_data}")
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