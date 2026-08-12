from fastapi import APIRouter, HTTPException, status, Query, Depends
from fastapi import FastAPI
from app.auth.auth_dependency import verify_firebase_token, verify_firebase_token_any
import traceback
import os

from typing import Union, Optional
from pydantic import BaseModel
from loguru import logger

import re
import math
import pymysql
from db.session import get_db_connection, close_db_connection
from datetime import datetime, timezone, timedelta
from core.s3_config import S3_CLIENT, BUCKET_NAME, get_s3_public_url

from models.gifticon import Gifticon
from models.store import StoreCreate

import http.client
from core.exceptions import InternalError

router = APIRouter()

# 한국 시간대 (KST, UTC+9)
KST = timezone(timedelta(hours=9))

def get_kst_now():
    """한국 시간(KST)을 반환하는 헬퍼 함수"""
    return datetime.now(KST)

# S3 설정은 app.s3_config에서 가져옴
s3 = S3_CLIENT
bucket_name = BUCKET_NAME

@router.get("/list/{user_id}")
def getGifticonList(user_id: int, user=Depends(verify_firebase_token)):
    connection = get_db_connection()  # 환경에 맞는 DB 연결
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    gifticonList = []
       
    try:
        # gifticon 테이블을 기준으로 조회하여 모든 기프티콘을 가져옴 (메뉴 정보는 발급 시점 스냅샷 사용)
        cursor.execute('''
            SELECT
                g.id as gifticon_id,
                g.user_id,
                g.order_id,
                g.type,
                g.sender,
                g.receiver,
                g.receiver_phone,
                g.validity,
                g.status,
                g.gift_code,
                g.menu_id,
                g.store_id,
                g.created_at,
                g.menu_name_snapshot,
                g.price_snapshot,
                g.description_snapshot,
                g.image_key_snapshot,
                g.product_type,
                s.store_name
            FROM gifticon g
            LEFT JOIN store s ON g.store_id = s.id
            WHERE g.receiver_id = %s AND g.status NOT IN ('PENDING', 'UNKNOWN')
            ORDER BY g.id DESC
        ''', (user_id,))

        rows = cursor.fetchall()
        print("sql 실행 결과:", len(rows), "개")

        for row in rows:
            image_key = row.get('image_key_snapshot') or ''
            menu_url = get_s3_public_url(bucket_name, image_key) if image_key else ''
            product_type = row.get('product_type') or 'MENU'
            gifticon = {
                "gifticon_id": row['gifticon_id'],
                "name": row.get('menu_name_snapshot') or '',
                "price": row.get('price_snapshot') or 0,
                "description": row.get('description_snapshot') or '',
                "product_type": product_type,
                "validity": row['validity'],
                "sender": row['sender'],
                "receiver": row['receiver'],
                "status": row['status'],
                "gift_code": row.get('gift_code'),
                "menu_url": menu_url,
                # 금액권은 사용처가 정해지지 않았으므로 매장명을 노출하지 않는다
                "store_name": '' if product_type == 'VOUCHER' else (row.get('store_name') or '')
            }

            gifticonList.append(gifticon)
    
        print("gifticonList", len(gifticonList), "개")
    
        return {'gifticonList': gifticonList}
        
    except Exception as e:
        raise InternalError(e, "getGifticonList")

    finally:        
        cursor.close()
        close_db_connection(connection)

@router.get("/{gifticon_id}")
def getGifticon(gifticon_id: int, user=Depends(verify_firebase_token)):
    connection = get_db_connection()  # 환경에 맞는 DB 연결
    cursor = connection.cursor(pymysql.cursors.DictCursor)
       
    try:
        cursor.execute('''SELECT * FROM gifticon
            WHERE id=%s ;''', gifticon_id)
                    
        gifticon = cursor.fetchone()

        if not gifticon:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Gifticon not found"
            )

        # 결제가 완료되지 않은(PENDING) 기프티콘은 유효하지 않은 것으로 처리 (안전망)
        if gifticon.get('status') == 'PENDING':
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Gifticon not found"
            )

        print("읽어온 기프티콘", gifticon)

        # order_id 조회 (gifticon 테이블에 order_id가 있으면 직접 사용, 없으면 orders_gifticon에서 조회)
        order_id_value = gifticon.get('order_id')
        if not order_id_value:
            cursor.execute('''SELECT order_id
            FROM orders_gifticon
            WHERE gifticon_id=%s ;''', (gifticon['id'],))
            order_id_result = cursor.fetchone()
            order_id_value = order_id_result['order_id'] if order_id_result else None

        product_type = gifticon.get('product_type') or 'MENU'
        is_voucher = product_type == 'VOUCHER'

        image_key = gifticon.get('image_key_snapshot') or ''
        menu_url = get_s3_public_url(bucket_name, image_key) if image_key else ''
        gifticon_response = {
            "gifticon_id": gifticon['id'],
            "gift_code": gifticon['gift_code'],
            "order_id": order_id_value,
            "product_type": product_type,
            "validity": gifticon['validity'],
            "purchaser_refund_deadline": gifticon.get('purchaser_refund_deadline'),
            "sender": gifticon['sender'],
            "type": gifticon['type'],
            "name": gifticon.get('menu_name_snapshot') or '',
            "status": gifticon.get('status'),
            "menu_url" : menu_url,
            "msg" : gifticon.get('msg'),
            "created_time" : gifticon['created_at'],
        }

        # 금액권은 입점 매장 어디서나 사용 가능하므로 특정 매장 정보를 내려주지 않는다
        if not is_voucher:
            cursor.execute('''SELECT store_lat, store_lng, store_name, store_address
            FROM store
            WHERE id=%s ;''', (gifticon['store_id'],))

            store_info = cursor.fetchone()

            if not store_info:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Store not found"
                )

            gifticon_response.update({
                "store_id": gifticon['store_id'],
                "store_lat": store_info["store_lat"],
                "store_lng": store_info["store_lng"],
                "store_name": store_info["store_name"],
                "store_address": store_info["store_address"],
            })
    
        print("\ngifticon", gifticon_response)
    
        return {'gifticon': gifticon_response}
        
    except HTTPException:
        raise
    except Exception as e:
        raise InternalError(e, "getGifticon")

    finally:        
        cursor.close()
        close_db_connection(connection)

class UseGifticonRequest(BaseModel):
    """사용처리 요청. store_id는 사용처리하는 매장 (금액권 필수, 메뉴권 선택)"""
    store_id: Optional[int] = None


def _verify_owner_store(cursor, user, store_id: int) -> Optional[dict]:
    """사용처리 요청 매장이 요청자(사장님) 소유이고 영업 가능 상태인지 검증.

    금액권은 사용처가 곧 정산처이므로 클라이언트가 보낸 store_id를 그대로 신뢰할 수 없다.
    owner 토큰의 uid로 소유권을 확인한다. 검증 실패 시 None 반환.
    """
    cursor.execute(
        "SELECT id, owner_id, inspection_status, contract_completed FROM store WHERE id = %s",
        (store_id,)
    )
    store = cursor.fetchone()
    if not store:
        return None

    # 검수/계약 미완료 매장은 정산 대상이 아니므로 사용처리 불가
    if store['inspection_status'] != 'APPROVED' or store['contract_completed'] != 'COMPLETED':
        return None

    # user가 None인 경우는 인증 우회 IP(내부 테스트)이므로 소유권 검증을 건너뛴다
    if user is None:
        return store

    uid = user.get("uid")
    cursor.execute("SELECT id FROM owner WHERE uid = %s LIMIT 1", (uid,))
    owner = cursor.fetchone()
    if not owner or store['owner_id'] != owner['id']:
        return None

    return store


@router.patch("/use/{gifticon_id}")
def useGifticon(gifticon_id: int, body: Optional[UseGifticonRequest] = None, user=Depends(verify_firebase_token_any)):
    connection = get_db_connection()  # 환경에 맞는 DB 연결
    cursor = connection.cursor(pymysql.cursors.DictCursor)

    try:

        if gifticon_id == 9999:
            return {'result': 0}

        cursor.execute(
            """SELECT g.status, g.validity, g.product_type, g.store_id, o.amount AS total_price
               FROM gifticon g
               JOIN orders o ON g.order_id = o.id
               WHERE g.id = %s""",
            (gifticon_id,)
        )
        gifticon = cursor.fetchone()

        if not gifticon:
            return {'result': 3}  # 기프티콘 찾을 수 없음

        if gifticon['status'] in ('USED', 'CANCELED'):
            return {'result': 1}  # 이미 사용/취소된 기프티콘

        validity = gifticon['validity']
        if hasattr(validity, 'date'):
            validity = validity.date()
        if validity and validity < get_kst_now().date():
            return {'result': 2}  # 유효기간 만료

        # 사용 매장 검증
        # 금액권은 사용처가 곧 정산처이므로 store_id 필수. 메뉴권은 선택(미전송 시 기존 동작 유지).
        is_voucher = (gifticon.get('product_type') or 'MENU') == 'VOUCHER'
        request_store_id = body.store_id if body else None
        used_store_id = None

        if request_store_id is not None:
            store = _verify_owner_store(cursor, user, request_store_id)
            if store is None:
                return {'result': 4}  # 매장 검증 실패 (본인 매장 아님/미계약/없음)
            used_store_id = request_store_id
            # 메뉴권은 발행 매장과 사용 매장이 일치해야 함
            if not is_voucher and gifticon['store_id'] != request_store_id:
                return {'result': 5}  # 다른 매장의 기프티콘
        elif is_voucher:
            return {'result': 4}  # 금액권은 store_id 없이 사용처리 불가

        sales_amount = int(gifticon['total_price'])

        connection.begin()

        # 원자적 상태 전환: UNUSED인 경우에만 UPDATE
        cursor.execute(
            "UPDATE gifticon SET status='USED', used_at=NOW(), used_store_id=%s WHERE id=%s AND status='UNUSED'",
            (used_store_id, gifticon_id)
        )
        if cursor.rowcount == 0:
            connection.rollback()
            return {'result': 1}  # 동시 요청으로 이미 사용 처리됨

        # settlement_details: 개별 기프티콘 매출액 + 기본(프로모션 미적용) 수수료 기록
        # 프로모션 적용 최종 정산액은 settlement 테이블에서만 산정
        cursor.execute("SELECT base_fee_rate FROM platform_config WHERE config_id = 1")
        fee_rate = float(cursor.fetchone()['base_fee_rate'])

        fee_supply = math.floor(sales_amount * fee_rate / 100)
        fee_vat = round(fee_supply * 0.1)
        fee_amount = fee_supply + fee_vat
        settlement_amount = sales_amount - fee_amount

        cursor.execute(
            """INSERT INTO settlement_details
               (settlement_id, gifticon_id, sales_amount, fee_rate, fee_supply, fee_vat, fee_amount, settlement_amount)
               VALUES (NULL, %s, %s, %s, %s, %s, %s, %s)""",
            (gifticon_id, sales_amount, fee_rate, fee_supply, fee_vat, fee_amount, settlement_amount)
        )

        connection.commit()

        return {'result': 0}
        
    except Exception as e:
        connection.rollback()
        traceback.print_exc()
        raise InternalError(e, "useGifticon")

    finally:
        cursor.close()
        close_db_connection(connection)

@router.get("/used/{store_id}")
def getTodayUsedGifticon(store_id: int):
    connection = get_db_connection()  # 환경에 맞는 DB 연결
    cursor = connection.cursor(pymysql.cursors.DictCursor)  # DB에 접속 및 DB 객체를 가져옴

    try:
        # 메뉴 정보는 발급 시점 스냅샷 우선 사용 (메뉴 변경/삭제와 무관하게 사용 당시 내역 유지)
        cursor.execute('''
        SELECT
            g.id,
            g.used_at AS used_time,
            COALESCE(g.menu_name_snapshot, m.menu_name, '') AS menu_name,
            COALESCE(g.price_snapshot, m.price, 0) AS price
        FROM gifticon g
        LEFT JOIN menu m ON g.menu_id = m.id
        WHERE g.store_id = %s
          AND g.status = 'USED'
          AND g.used_at IS NOT NULL
          AND DATE(g.used_at) = CURDATE()
        ORDER BY g.used_at DESC
        ''', (store_id,))

        rows = cursor.fetchall()
        gifticonList = [
            {
                "id": row['id'],
                "used_time": row['used_time'],
                "menu_name": row['menu_name'],
                "price": row['price'],
            }
            for row in rows
        ]

        return {"gifticonList": gifticonList}
    
    except Exception as e:
        traceback.print_exc()
        raise InternalError(e, "getTodayUsedGifticon")
    finally:
        cursor.close()
        close_db_connection(connection)

@router.patch("/{gifticon_id}/user/{user_id}")
def updateGifticonUser(gifticon_id: int, user_id: int, user=Depends(verify_firebase_token)):
    """
    기프티콘의 user_id를 업데이트하는 API
    gifticon_id에 해당하는 기프티콘의 user_id를 새로운 user_id로 변경
    """
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)

    try:
        if user is not None:
            uid = user.get("uid")
            cursor.execute("SELECT id FROM user WHERE uid = %s LIMIT 1", (uid,))
            db_user = cursor.fetchone()
            if not db_user or db_user["id"] != user_id:
                raise HTTPException(status_code=403, detail="Forbidden")

        # 1. 기프티콘 존재 여부 확인
        cursor.execute('SELECT id FROM gifticon WHERE id = %s', (gifticon_id,))
        gifticon = cursor.fetchone()

        if not gifticon:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Gifticon with id {gifticon_id} not found"
            )
        
        # 2. user_id 업데이트
        cursor.execute('''
            UPDATE gifticon 
            SET user_id = %s 
            WHERE id = %s
        ''', (user_id, gifticon_id))
        
        connection.commit()
        
        logger.info(f"Gifticon {gifticon_id} user_id updated to {user_id}")
        
        return {
            "message": "Gifticon user_id updated successfully",
            "gifticon_id": gifticon_id,
            "user_id": user_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        connection.rollback()
        traceback.print_exc()
        raise InternalError(e, "updateGifticonUser")
    finally:
        cursor.close()
        close_db_connection(connection)

def normalize_phone(phone: str) -> str:
    phone = re.sub(r'[\s\-()]', '', phone)
    if phone.startswith('+82'):
        phone = '0' + phone[3:]
    return phone

class LinkGifticonRequest(BaseModel):
    user_id: int
    gifticon_id: int
    receiver_phone: str

@router.post("/link")
def linkGifticonToUser(request: LinkGifticonRequest):
    """
    receiver_phone으로 기프티콘을 사용자 계정에 연결하는 API
    user_id, gifticon_id, receiver_phone을 받아서
    gifticon 테이블의 receiver_phone이 일치하면 user_id를 업데이트
    """
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        # 1. 기프티콘 존재 여부 및 receiver_phone 확인
        cursor.execute('''
            SELECT id, receiver_phone, user_id, receiver_id, status
            FROM gifticon
            WHERE id = %s
        ''', (request.gifticon_id,))

        gifticon = cursor.fetchone()

        if not gifticon:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Gifticon with id {request.gifticon_id} not found"
            )

        # 1-1. 결제가 완료되지 않은(PENDING) 기프티콘은 연결 불가
        if gifticon['status'] == 'PENDING':
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Gifticon is not ready"
            )

        # 2. receiver_phone 일치 여부 확인
        if normalize_phone(gifticon['receiver_phone']) != normalize_phone(request.receiver_phone):
            print(f"receiver_phone does not match: {gifticon['receiver_phone']} != {request.receiver_phone}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Receiver phone number does not match"
            )
        
        # 3. 이미 다른 user_id가 설정되어 있는지 확인
        # receiver_id가 None이 아니고, 요청한 user_id와 다를 때만 에러 발생
        if gifticon['receiver_id'] and gifticon['receiver_id'] != request.user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Gifticon is already linked to another user. Current: {gifticon['receiver_id']}, Requested: {request.user_id}"
            )
        
        # 4. gifticon 테이블의 user_id 업데이트
        cursor.execute('''
            UPDATE gifticon 
            SET receiver_id = %s 
            WHERE id = %s
        ''', (request.user_id, request.gifticon_id))
        
        # 5. orders_gifticon 테이블의 receiver_id 업데이트
        cursor.execute('''
            UPDATE orders_gifticon 
            SET receiver_id = %s 
            WHERE gifticon_id = %s
        ''', (request.user_id, request.gifticon_id))
        
        connection.commit()
        
        logger.info(f"Gifticon {request.gifticon_id} linked to user {request.user_id}")
        
        return {
            "message": "Gifticon linked to user successfully",
            "gifticon_id": request.gifticon_id,
            "user_id": request.user_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        connection.rollback()
        traceback.print_exc()
        raise InternalError(e, "linkGifticonToUser")
    finally:
        cursor.close()
        close_db_connection(connection)
