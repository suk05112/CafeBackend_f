from fastapi import APIRouter, HTTPException
from fastapi import FastAPI

from fastapi import FastAPI
from typing import Union
from pydantic import BaseModel

import pymysql
import dbinfo
import boto3
from botocore.client import Config

from models.gifticon import Gifticon
from models.store import StoreCreate

router = APIRouter()

@router.post("/purchase/{user_id}")
def purchaseGifticon(user_id: int, gifticon: Gifticon):
    connection = pymysql.connect(
        host = dbinfo.db_host,
        user = dbinfo.db_username,
        passwd = dbinfo.db_password,
        db = dbinfo.db_name,
        port = dbinfo.db_port
    ) # db 접근 하기 위한 정보 

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
                store_id, user_id, payment, total_price
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
        print(e)
        result = {
            'statusCode': 500,
            'msg': "failed get store list",
        }
        print(f"Error during purchaseGifticon: {e}")
        return {"statusCode": 500, "msg": f"Error: {str(e)}"}
    finally:        
        cursor.close()
        connection.close()

@router.get("/list/{user_id}")
def getGifticonList(user_id: int):
    connection = pymysql.connect(
        host = dbinfo.db_host,
        user = dbinfo.db_username,
        passwd = dbinfo.db_password,
        db = dbinfo.db_name,
        port = dbinfo.db_port
    ) # db 접근 하기 위한 정보 

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
    connection = pymysql.connect(
        host = dbinfo.db_host,
        user = dbinfo.db_username,
        passwd = dbinfo.db_password,
        db = dbinfo.db_name,
        port = dbinfo.db_port
    ) # db 접근 하기 위한 정보 

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

        print("읽어온 기프티콘", gifticon)
        if gifticon:
            print("여기는 탐")
            store_id = gifticon['store_id']
            menu_id = gifticon['menu_id']
            menu_url = s3.generate_presigned_url('get_object',
                                    Params={'Bucket': bucket_name,
                                            'Key': f'menu/menu_{store_id}_{menu_id}.png',
                                            },
                                    ExpiresIn=3600)
            gifticon = {
                "gifticon_id": gifticon['id'],
                "validity": gifticon['validity'],
                "sender": gifticon['sender'],
                "use_yn": gifticon['use_yn'],
                "availability": gifticon['availability'],
                "menu_url" : menu_url
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
