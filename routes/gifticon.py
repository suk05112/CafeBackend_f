from fastapi import APIRouter, HTTPException
from fastapi import FastAPI
import traceback

from typing import Union
from pydantic import BaseModel
from loguru import logger

import pymysql
import app.database as database
import boto3
from botocore.client import Config
from app.database import get_db_connection
from datetime import datetime

from models.gifticon import Gifticon
from models.store import StoreCreate

router = APIRouter()

@router.post("/purchase/{user_id}")
def purchaseGifticon(user_id: int, gifticon: Gifticon):
    connection = get_db_connection()  # 환경에 맞는 DB 연결
    cursor = connection.cursor() # DB에 접속 및 DB 객체를 가져옴

    print("storeList 호출1")
      
    try:      
        query = """
            INSERT INTO Gifticon (
                user_id, type, sender, receiver, receiver_phone_number, menu_id, store_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s);
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
            )
        )
        connection.commit()
        gifticon_rows = cursor.fetchone()
        gifticon_id = cursor.lastrowid
        print("gifticon_rows", gifticon_rows, gifticon_id)

        # 2. Order 테이블에 데이터 삽입
        order_query = """
            INSERT INTO `Order` (
                store_id, user_id, payment, price
            ) VALUES (%s, %s, %s, %s);
        """
        cursor.execute(
            order_query,
            (
                gifticon.store_id,
                user_id,
                gifticon.payment,
                gifticon.total_price,
            )
        )
        connection.commit()
        # order_rows = cursor.fetchone()
        # print("order_rows", order_rows)
        order_id = cursor.lastrowid

        # 3. Order_Gifticon 테이블에 데이터 삽입
        order_gifticon_query = """
            INSERT INTO Order_Gifticon (
                user_id, order_id, menu_id, gifticon_id
            ) VALUES (%s, %s, %s, %s);
        """
        cursor.execute(
            order_gifticon_query,
            (
                user_id,
                order_id,
                gifticon.menu_id,
                gifticon_id,
            )
        )
        connection.commit()
        # orderGifticonQuery_rows = cursor.fetchone()

        # print("orderGifticonQuery_rows", orderGifticonQuery_rows[0])

        return {
            'statusCode': 200,
        }
    except Exception as e:
        print(f"Error during purchaseGifticon: {e}")
        raise HTTPException(status_code=500, detail=f"Error during purchaseGifticon: {str(e)}")

    finally:        
        cursor.close()
        connection.close()

@router.get("/list/{user_id}")
def getGifticonList(user_id: int):
    connection = get_db_connection()  # 환경에 맞는 DB 연결
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    gifticonList = []
       
    try:
        user_id = user_id
        
        cursor.execute('''SELECT og.order_id, Menu.*, Gifticon.*
            FROM Order_Gifticon as og 
            JOIN Menu ON og.menu_id  = Menu.menuId 
            JOIN Gifticon ON og.gifticon_id  = Gifticon.id
            WHERE og.user_id=%s ;''', user_id)
        
        bucket_name = "cafe-platform-bucket"

        s3 = boto3.client('s3',aws_access_key_id='***REMOVED_AWS_KEY***',
                      aws_secret_access_key='***REMOVED_AWS_SECRET***',
                      region_name='ap-northeast-2',
                      config= Config(signature_version='s3v4'))
                    
        rows = cursor.fetchall()
        print("sql 실행")
        print(rows)

        for row in rows:
            store_id = row['store_id']
            menu_id = row['menu_id']
            menu_url = s3.generate_presigned_url('get_object',
                                    Params={'Bucket': bucket_name,
                                            'Key': f'menu/menu_{store_id}_{menu_id}.png',
                                            },
                                    ExpiresIn=3600)
            gifticon = {
                "gifticon_id": row['id'],
                # "order_id": row['order_id'],
                "name": row['name'],
                "price": row['price'],
                "description": row['description'],
                "validity": row['validity'],
                "sender": row['sender'],
                "receiver": row['receiver'],
                "use_yn": row['use_yn'],
                "availability": row['availability'],
                "menu_url" : menu_url
            }

            gifticonList.append(gifticon)
    
        print("gifticonList", gifticonList)
    
        return {
            'statusCode': 200,
            'gifticonList': gifticonList
        }
        
    except Exception as e:
        print(e)
        result = {
            'statusCode': 500,
            'msg': "failed get gifticon list",
        }
        return result

    finally:        
        cursor.close()
        connection.close()

@router.get("/{gifticon_id}")
def getGifticon(gifticon_id: int):
    connection = get_db_connection()  # 환경에 맞는 DB 연결

    cursor = connection.cursor(pymysql.cursors.DictCursor)
       
    try:
        cursor.execute('''SELECT * FROM Gifticon
            WHERE id=%s ;''', gifticon_id)
        
        bucket_name = "cafe-platform-bucket"

        s3 = boto3.client('s3',aws_access_key_id='***REMOVED_AWS_KEY***',
                      aws_secret_access_key='***REMOVED_AWS_SECRET***',
                      region_name='ap-northeast-2',
                      config= Config(signature_version='s3v4'))
                    
        gifticon = cursor.fetchone()

        cursor.execute('''SELECT order_id
        FROM Order_Gifticon
        WHERE gifticon_id=%s ;''', gifticon['id'])
        
        order_id = cursor.fetchone()

        print("읽어온 기프티콘", gifticon)

        cursor.execute('''SELECT store_lat, store_lng, store_name
        FROM Store
        WHERE store_id=%s ;''', gifticon['store_id'])
        
        store_info = cursor.fetchone()
        
        cursor.execute('''SELECT name
        FROM Menu
        WHERE menuId=%s ;''', gifticon['menu_id'])
        
        menu_name = cursor.fetchone()
        
        if gifticon:
            store_id = gifticon['store_id']
            menu_id = gifticon['menu_id']
            menu_url = s3.generate_presigned_url('get_object',
                                    Params={'Bucket': bucket_name,
                                            'Key': f'menu/menu_{store_id}_{menu_id}.png',
                                            },
                                    ExpiresIn=3600)
            gifticon = {
                "gifticon_id": gifticon['id'],
                "order_id": order_id['order_id'],
                "validity": gifticon['validity'],
                "sender": gifticon['sender'],
                "type": gifticon['type'],
                "name": menu_name['name'],
                "use_yn": gifticon['use_yn'],
                "availability": gifticon['availability'],
                "menu_url" : menu_url,
                "msg" : gifticon['msg'],
                "created_time" : gifticon['created_time'],
                "store_lat" : store_info["store_lat"],
                "store_lng" : store_info["store_lng"],
                "store_name" : store_info["store_name"]
            }
    
        print("gifticon", gifticon)
    
        return {
            'statusCode': 200,
            'gifticon': gifticon
        }
        
    except Exception as e:
        print(e)
        result = {
            'statusCode': 500,
            'msg': "failed get gifticon",
        }
        return result

    finally:        
        cursor.close()
        connection.close()

@router.patch("/use/{gifticon_id}")
def useGifticon(gifticon_id: int):
    connection = get_db_connection()  # 환경에 맞는 DB 연결
    cursor = connection.cursor(pymysql.cursors.DictCursor)
       
    try:
        
        cursor.execute('''SELECT use_yn, validity From Gifticon WHERE id=%s ;''', gifticon_id)

        gifticon = _ = cursor.fetchone()
        
        result = 0 #사용 성공

        if gifticon:
            if gifticon['use_yn'] == 1:
                result = 1 # 이미 사용된 기프티콘
            elif gifticon['validity'] and gifticon['validity'] < datetime.now():
                result = 2 # 기프티콘 유효기간 만료
        else:
            result = 3 #기프티콘 찾을 수 없음
            
        if result == 0:
            cursor.execute('''UPDATE Gifticon SET use_yn=1, used_time = NOW() WHERE id=%s ;''', gifticon_id)
            connection.commit()
            _ = cursor.fetchall()

        return {
            'result': result,
        }
        
    except Exception as e:
        print(e)
        traceback.print_exc() 
        logger.error(f"failed use gifticon::  {str(e)}")
        raise HTTPException(status_code=500, detail=f"failed use gifticon::  {str(e)}")

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
        FROM Gifticon
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
            FROM Menu
            Where menuId = %s
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

        return {"statusCode": 200, "gifticonList": gifticonList}
    
    except Exception as e:
        print(f"getTodayUsedGifticon:: {str(e)}")
        traceback.print_exc() 
        logger.error(f"getTodayUsedGifticon::  {str(e)}")
        raise HTTPException(status_code=500, detail=f"getTodayUsedGifticon::  {str(e)}")
