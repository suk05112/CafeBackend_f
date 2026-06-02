from fastapi import APIRouter, HTTPException, status, Query
from fastapi import FastAPI
import traceback
import os

from typing import Union
from pydantic import BaseModel
from loguru import logger

import pymysql
from db.session import get_db_connection
from datetime import datetime, timezone, timedelta
from core.s3_config import S3_CLIENT, BUCKET_NAME

from models.gifticon import Gifticon
from models.store import StoreCreate

import http.client

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
def getGifticonList(user_id: int):
    connection = get_db_connection()  # 환경에 맞는 DB 연결
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    gifticonList = []
       
    try:
        # gifticon 테이블을 기준으로 조회하여 모든 기프티콘을 가져옴
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
                m.menu_name,
                m.price,
                m.description
            FROM gifticon g
            LEFT JOIN menu m ON g.menu_id = m.id
            WHERE g.receiver_id = %s AND g.status != 'UNKNOWN'
            ORDER BY g.id DESC
        ''', (user_id,))
                    
        rows = cursor.fetchall()
        print("sql 실행 결과:", len(rows), "개")

        for row in rows:
            store_id = row['store_id']
            menu_id = row['menu_id']
            menu_url = s3.generate_presigned_url('get_object',
                                    Params={'Bucket': bucket_name,
                                            'Key': f'menu/menu_{store_id}_{menu_id}.png',
                                            },
                                    ExpiresIn=3600)
            gifticon = {
                "gifticon_id": row['gifticon_id'],
                "name": row.get('menu_name') or '',
                "price": row.get('price') or 0,
                "description": row.get('description') or '',
                "validity": row['validity'],
                "sender": row['sender'],
                "receiver": row['receiver'],
                "status": row['status'],
                "gift_code": row.get('gift_code'),
                "menu_url": menu_url
            }

            gifticonList.append(gifticon)
    
        print("gifticonList", len(gifticonList), "개")
    
        return {'gifticonList': gifticonList}
        
    except Exception as e:
        print(e)
        logger.error(f"서버 오류 발생: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="failed get gifticon list"
        )

    finally:        
        cursor.close()
        connection.close()

@router.get("/{gifticon_id}")
def getGifticon(gifticon_id: int):
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

        print("읽어온 기프티콘", gifticon)

        # order_id 조회 (gifticon 테이블에 order_id가 있으면 직접 사용, 없으면 orders_gifticon에서 조회)
        order_id_value = gifticon.get('order_id')
        if not order_id_value:
            cursor.execute('''SELECT order_id
            FROM orders_gifticon
            WHERE gifticon_id=%s ;''', (gifticon['id'],))
            order_id_result = cursor.fetchone()
            order_id_value = order_id_result['order_id'] if order_id_result else None

        cursor.execute('''SELECT store_lat, store_lng, store_name, store_address
        FROM store
        WHERE id=%s ;''', (gifticon['store_id'],))
        
        store_info = cursor.fetchone()
        
        if not store_info:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Store not found"
            )
        
        cursor.execute('''SELECT menu_name
        FROM menu
        WHERE id=%s ;''', (gifticon['menu_id'],))
        
        menu_result = cursor.fetchone()
        
        if not menu_result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Menu not found"
            )
        
        store_id = gifticon['store_id']
        menu_id = gifticon['menu_id']
        menu_url = s3.generate_presigned_url('get_object',
                                Params={'Bucket': bucket_name,
                                        'Key': f'menu/menu_{store_id}_{menu_id}.png',
                                        },
                                ExpiresIn=3600)
        gifticon_response = {
            "gifticon_id": gifticon['id'],
            "gift_code": gifticon['gift_code'],
            "order_id": order_id_value,
            "validity": gifticon['validity'],
            "sender": gifticon['sender'],
            "type": gifticon['type'],
            "name": menu_result.get('menu_name') or menu_result.get('name'),
            "status": gifticon.get('status'),
            "menu_url" : menu_url,
            "msg" : gifticon.get('msg'),
            "created_time" : gifticon['created_at'],
            "store_id" : gifticon['store_id'],
            "store_lat" : store_info["store_lat"],
            "store_lng" : store_info["store_lng"],
            "store_name" : store_info["store_name"],
            "store_address" : store_info["store_address"]

        }
    
        print("\ngifticon", gifticon_response)
    
        return {'gifticon': gifticon_response}
        
    except HTTPException:
        raise
    except Exception as e:
        print(e)
        logger.error(f"서버 오류 발생: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="failed get gifticon"
        )

    finally:        
        cursor.close()
        connection.close()

@router.patch("/use/{gifticon_id}")
def useGifticon(gifticon_id: int):
    connection = get_db_connection()  # 환경에 맞는 DB 연결
    cursor = connection.cursor(pymysql.cursors.DictCursor)
       
    try:
        cursor.execute(
            """SELECT g.status, g.validity, g.store_id, g.order_id,
                      g.base_fee_rate, g.applied_fee_rate, g.applied_promo_id,
                      o.amount AS total_price
               FROM gifticon g
               JOIN orders o ON g.order_id = o.id
               WHERE g.id = %s""",
            (gifticon_id,)
        )

        gifticon = cursor.fetchone()

        result = 0 #사용 성공

        if gifticon:
            if gifticon['status'] == 'USED' or gifticon['status'] == 'CANCELED':
                result = 1 # 이미 사용된 기프티콘 또는 취소된 기프티콘
            elif gifticon['validity'] and gifticon['validity'].replace(tzinfo=KST) < get_kst_now():
                result = 2 # 기프티콘 유효기간 만료
        else:
            result = 3 #기프티콘 찾을 수 없음

        if result == 0:
            import math
            sales_amount = int(gifticon['total_price'])
            applied_fee_rate = float(gifticon['applied_fee_rate']) if gifticon['applied_fee_rate'] else 0.0
            fee_supply = math.floor(sales_amount * applied_fee_rate / 100)
            fee_vat = round(fee_supply * 0.1)
            fee_amount = fee_supply + fee_vat
            settlement_amount = sales_amount - fee_amount

            connection.begin()

            cursor.execute(
                "UPDATE gifticon SET status='USED', used_at=NOW() WHERE id=%s",
                (gifticon_id,)
            )

            cursor.execute("""
                INSERT INTO settlement_details
                    (settlement_id, gifticon_id, sales_amount, fee_amount, settlement_amount,
                     base_fee_rate, applied_promo_id, applied_fee_rate, fee_supply, fee_vat)
                VALUES (NULL, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                gifticon_id, sales_amount, fee_amount, settlement_amount,
                gifticon['base_fee_rate'], gifticon['applied_promo_id'],
                gifticon['applied_fee_rate'], fee_supply, fee_vat
            ))

            connection.commit()

        return {
            'result': result,
        }
        
    except Exception as e:
        connection.rollback()
        print(e)
        traceback.print_exc()
        logger.error(f"failed use gifticon::  {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"failed use gifticon: {str(e)}"
        )

    finally:
        cursor.close()
        connection.close()

@router.get("/used/{store_id}")
def getTodayUsedGifticon(store_id: int):
    connection = get_db_connection()  # 환경에 맞는 DB 연결
    cursor = connection.cursor(pymysql.cursors.DictCursor)  # DB에 접속 및 DB 객체를 가져옴

    try:
        cursor.execute('''
        SELECT
            id, 
            used_time, 
            menu_id
        FROM gifticon
        Where store_id =%s
        AND DATE(used_time) = CURDATE()
        ''', (store_id))
        
        # DB에서 데이터를 가져오기
        rows = cursor.fetchall()
        gifticonList = []
        
        for row in rows:
            print(row)
            menu_id = row['menu_id']
            
            menu_query = '''
            SELECT
                name,
                price
            FROM menu
            Where id = %s
            '''
    
            cursor.execute(menu_query, (menu_id))
    
            # DB에서 데이터를 가져오기
            menu = cursor.fetchone()
            
            # store 데이터를 구성
            gificon = {
                "id": row['id'],
                "used_time": row['used_time'],
                "menu_name": menu['name'],
                "price": menu['price']      
            }
            gifticonList.append(gificon)

        return {"gifticonList": gifticonList}
    
    except Exception as e:
        print(f"getTodayUsedGifticon:: {str(e)}")
        traceback.print_exc() 
        logger.error(f"getTodayUsedGifticon::  {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"getTodayUsedGifticon: {str(e)}"
        )
    finally:
        cursor.close()
        connection.close()

@router.patch("/{gifticon_id}/user/{user_id}")
def updateGifticonUser(gifticon_id: int, user_id: int):
    """
    기프티콘의 user_id를 업데이트하는 API
    gifticon_id에 해당하는 기프티콘의 user_id를 새로운 user_id로 변경
    """
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
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
        print(f"Error during updateGifticonUser: {e}")
        traceback.print_exc()
        logger.error(f"Error during updateGifticonUser: {str(e)}")
        connection.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error during updateGifticonUser: {str(e)}"
        )
    finally:
        cursor.close()
        connection.close()

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
            SELECT id, receiver_phone, user_id, receiver_id
            FROM gifticon 
            WHERE id = %s
        ''', (request.gifticon_id,))
        
        gifticon = cursor.fetchone()
        
        if not gifticon:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Gifticon with id {request.gifticon_id} not found"
            )
        
        # 2. receiver_phone 일치 여부 확인
        if gifticon['receiver_phone'] != request.receiver_phone:
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
        print(f"Error during linkGifticonToUser: {e}")
        traceback.print_exc()
        logger.error(f"Error during linkGifticonToUser: {str(e)}")
        connection.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error during linkGifticonToUser: {str(e)}"
        )
    finally:
        cursor.close()
        connection.close()
