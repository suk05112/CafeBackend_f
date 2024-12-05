from fastapi import APIRouter, HTTPException
from fastapi import FastAPI

from fastapi import FastAPI
from typing import Optional, Union
from pydantic import BaseModel

import pymysql
import dbinfo
import boto3
from botocore.client import Config

from models.store import StoreCreate

router = APIRouter()

@router.get("/list")
def getStoreList():
    connection = pymysql.connect(
        host = dbinfo.db_host,
        user = dbinfo.db_username,
        passwd = dbinfo.db_password,
        db = dbinfo.db_name,
        port = dbinfo.db_port
    ) # db 접근 하기 위한 정보 

    cursor = connection.cursor() # DB에 접속 및 DB 객체를 가져옴
    
    bucket_name = "cafe-platform-bucket"

    s3 = boto3.client('s3',aws_access_key_id='***REMOVED_AWS_KEY***',
                      aws_secret_access_key='***REMOVED_AWS_SECRET***',
                      region_name='ap-northeast-2',
                      config= Config(signature_version='s3v4'))
                      
    try:      
        print("storeList 호출1")
      
        cursor.execute('''select
        owner_id, 
        store_id, 
        store_name, 
        status, 
        inspection_status, 
        open_yn,
        store_photo_cnt,
        store_lat, 
        store_lng 
        from Store''')
        
        rows = cursor.fetchall()
        row = rows[0]

        storeList = []

        for row in rows:
            store_logo_url = s3.generate_presigned_url('get_object',
                                                    Params={'Bucket': bucket_name,
                                                            'Key': f'logo/store_logo_{row[1]}.png',
                                                            },
                                                  ExpiresIn=3600)
                                                  
            print("logo url success")
            store_photo_urls = []
        
            for i in range(1, row[6]+1):
                s3_url = s3.generate_presigned_url('get_object',
                                                            Params={'Bucket': bucket_name,
                                                                    'Key': f'store_image/store_image_{row[1]}_{i}.png',
                                                                    },
                                                          ExpiresIn=3600)

                store_photo_urls.append(s3_url) 
            
            store = {
                "owner_id": row[0],
                "store_id": row[1],
                "store_name": row[2],
                "store_logo": store_logo_url,
                "store_photo_urls": store_photo_urls,
                "status": row[3],
                "inspection_status": row[4],
                "open_yn": row[5],
                "store_lat": row[7],
                "store_lng": row[8],

            }
            storeList.append(store)
    
        print(storeList)
        
        result = {
            # 'statusCode': 200,
            'store': storeList
        }
    
        # return result
        return {
            'statusCode': 200,
            'body': result
        }
    except Exception as e:
        print(e)
        result = {
            'statusCode': 500,
            'msg': "failed get store list",
        }
    finally:        
        cursor.close()
        connection.close()

@router.post("/register")
async def registerStore(store: StoreCreate):
    connection = pymysql.connect(
    host = dbinfo.db_host,
    user = dbinfo.db_username,
    passwd = dbinfo.db_password,
    db = dbinfo.db_name,
    port = dbinfo.db_port
    ) # db 접근 하기 위한 정보 

    bucket_name = "cafe-platform-bucket"

    s3 = boto3.client('s3',aws_access_key_id='***REMOVED_AWS_KEY***',
                      aws_secret_access_key='***REMOVED_AWS_SECRET***',
                      region_name='ap-northeast-2',
                      config= Config(signature_version='s3v4'))
                          
    # keys = event.keys()
    cursor = connection.cursor()

    # print(keys) 
    print("description")

    try:
        print("sujin1")
        query = """
            INSERT INTO Store (
                owner_id, store_name, store_telephone, store_description, store_address, , store_lat, store_lng, store_photo_cnt
            ) VALUES (
              {},'{}','{}', '{}', '{}', '{}', {}, {}, {}
            );
        """.format(
            store.owner_id,
            store.store_name,
            store.store_telephone,
            store.store_description,
            store.store_address,
            store.store_lat,
            store.store_lng,
            store.store_photo_cnt,
            )
            
        cursor.execute(query)
        connection.commit()
        print("sujin2")

        store_id = cursor.lastrowid
        print(store_id)

        store_logo_url = s3.generate_presigned_url('put_object',
                                                    Params={'Bucket': bucket_name,
                                                            'Key': f'logo/store_logo_{store_id}.png',
                                                            },
                                                  ExpiresIn=3600)
                                                  
                              
    
        store_photo_urls = []
        
        for i in range(1, store.store_photo_cnt+1):
            s3_url = s3.generate_presigned_url('put_object',
                                                    Params={'Bucket': bucket_name,
                                                            'Key': f'store_image/store_image_{store_id}_{i}.png',
                                                            },
                                                  ExpiresIn=3600)

            store_photo_urls.append(s3_url)
        
        rows = cursor.fetchall()
        
        print(s3_url)
        print("sujin test")
        
        return {
            'statusCode': 200,
            'store_id': store_id,
            'store_logo_url': store_logo_url,
            'store_photo_urls': store_photo_urls
        }
    except Exception as e:
        print(e)
        result = {
            'statusCode': 500,
            'msg': "failed register store - " + str(e),
            'store_id': -1
        }
        return result
    finally:
        connection.close()

@router.post("/update/{store_id}")
def updateStore(store: StoreCreate):
    connection = pymysql.connect(
        host = dbinfo.db_host,
        user = dbinfo.db_username,
        passwd = dbinfo.db_password,
        db = dbinfo.db_name,
        port = dbinfo.db_port
    )
    try:
        cursor = connection.cursor()
        
        store_id = store_id
        query = "UPDATE Store SET "
        values = []

        if store.store_address:
            query += "store_address = %s, "
            values.append(store.store_address)
        if store.store_telephone:
            query += "store_telephone = %s, "
            values.append(store.store_telephone)
        if store.store_description:
            query += "store_description = %s, "
            values.append(store.store_description)
        if store.store_photo:
            query += "store_photo = %s, "
            values.append(store.store_photo)
        if store.store_logo:
            query += "store_logo = %s, "
            values.append(store.store_logo)

        query = query[:-2]  # 마지막 쉼표와 공백 제거
        query += " WHERE store_id = %s"
        values.append(store_id)

        cursor.execute(query, tuple(values))
        connection.commit()

        print(cursor.rowcount)
        print(cursor._rows)

        if cursor.rowcount > 0:
            result = {
                'statusCode': 200,
                'msg': "success",
                'owner_id': store_id
            }
        else:
            result = {
                'statusCode': 404,
                'msg': "no record found",
                'owner_id': store_id
            }

        return result
    except Exception as e:
        print(e)
        result = {
            'statusCode': 500,
            'msg': "failed update owner",
            'owner_id': -1
        }
    finally:
        connection.close()

@router.post("/delete/{store_id}")
def deleteStore():
    connection = pymysql.connect(
    host = dbinfo.db_host,
    user = dbinfo.db_username,
    passwd = dbinfo.db_password,
    db = dbinfo.db_name,
    port = dbinfo.db_port
    ) 

    try:
        cursor = connection.cursor()
        store_id = store_id
        query = "DELETE FROM Store WHERE store_id = %s"

        cursor.execute(query, (store_id,))
        connection.commit()
        
        if cursor.rowcount > 0:
            result = {
                'statusCode': 200,
                'msg': "success",
                'store_id': store_id
            }
        else:
            result = {
                'statusCode': 404,
                'msg': "no record found",
                'store_id': store_id
            }
        return result
    except Exception as e:
        print(e)
        result = {
            'statusCode': 500,
            'msg': "failed update owner",
            'owner_id': -1
        }
    finally:
        connection.close()

@router.get("/search/{item}/{lat}/{lng}")
def searchStore(item: str, lat: float, lng: float):
    connection = pymysql.connect(
    host = dbinfo.db_host,
    user = dbinfo.db_username,
    passwd = dbinfo.db_password,
    db = dbinfo.db_name,
    port = dbinfo.db_port
    ) 

    bucket_name = "cafe-platform-bucket"

    s3 = boto3.client('s3',aws_access_key_id='***REMOVED_AWS_KEY***',
                    aws_secret_access_key='***REMOVED_AWS_SECRET***',
                    region_name='ap-northeast-2',
                    config= Config(signature_version='s3v4'))
    try:
        cursor = connection.cursor()
        storeList = []

        itemQuery = '''select
        owner_id, 
        store_id, 
        store_name, 
        status, 
        inspection_status, 
        open_yn,
        store_photo_cnt,
        store_lat, 
        store_lng 
        from Store'''

        if item and item.strip():
            itemQuery += " WHERE store_name LIKE %s"
            item_param = f"%{item}%"
            cursor.execute(itemQuery, (item_param,))
        
            rows = cursor.fetchall()
            # row = rows[0]

            print("검색된 리스트", rows)

            if rows:
                for row in rows:
                    print(row)
                    store_logo_url = s3.generate_presigned_url('get_object',
                                                            Params={'Bucket': bucket_name,
                                                                    'Key': f'logo/store_logo_{row[1]}.png',
                                                                    },
                                                        ExpiresIn=3600)
                                                        
                    print("logo url success")            
                    
                    store = {
                        # "owner_id": row[0],
                        "store_id": row[1],
                        "store_name": row[2],
                        "store_logo": store_logo_url,
                        # "status": row[3],
                        # "inspection_status": row[4],
                        # "open_yn": row[5],
                        "store_lat": row[7],
                        "store_lng": row[8],
                    }
                    storeList.append(store)

                geoQuery = '''SELECT
                    owner_id,
                    store_id,
                    store_name,
                    status,
                    inspection_status,
                    open_yn,
                    store_photo_cnt,
                    store_lat,
                    store_lng,
                    (6371 * ACOS(COS(RADIANS(%s)) * COS(RADIANS(store_lat)) * COS(RADIANS(store_lng) - RADIANS(%s)) + SIN(RADIANS(%s)) * SIN(RADIANS(store_lat)))) AS distance
                FROM
                    Store
                WHERE
                    (6371 * ACOS(COS(RADIANS(%s)) * COS(RADIANS(store_lat)) * COS(RADIANS(store_lng) - RADIANS(%s)) + SIN(RADIANS(%s)) * SIN(RADIANS(store_lat)))) <= 1
                ORDER BY distance ASC;'''

                cursor.execute(geoQuery, (lat, lng, lat, lat, lng, lat))
                rows = cursor.fetchall()

                for row in rows:
                    store_logo_url = s3.generate_presigned_url('get_object',
                                                            Params={'Bucket': bucket_name,
                                                                    'Key': f'logo/store_logo_{row[1]}.png',
                                                                    },
                                                        ExpiresIn=3600)
                    store = {
                        # "owner_id": row[0],
                        "store_id": row[1],
                        "store_name": row[2],
                        "store_logo": store_logo_url,
                        # "status": row[3],
                        # "inspection_status": row[4],
                        # "open_yn": row[5],
                        # "store_photo_cnt": row[6],
                        "store_lat": row[7],
                        "store_lng": row[8],
                        # "distance": row[9],  # Include the calculated distance
                    }
                    storeList.append(store)

                # storeList에서 store_id 기준으로 중복 제거
                unique_store_dict = {store["store_id"]: store for store in storeList}

                # 중복 제거된 storeList 생성
                storeList = list(unique_store_dict.values())

                result = {
                    'statusCode': 200,
                    'storeList': storeList
                }
            else:
                result = {
                    'statusCode': 200,
                    'storeList': []
                }  
        else:
            geoQuery = '''SELECT
                    owner_id,
                    store_id,
                    store_name,
                    status,
                    inspection_status,
                    open_yn,
                    store_photo_cnt,
                    store_lat,
                    store_lng,
                    (6371 * ACOS(COS(RADIANS(%s)) * COS(RADIANS(store_lat)) * COS(RADIANS(store_lng) - RADIANS(%s)) + SIN(RADIANS(%s)) * SIN(RADIANS(store_lat)))) AS distance
                FROM
                    Store
                WHERE
                    (6371 * ACOS(COS(RADIANS(%s)) * COS(RADIANS(store_lat)) * COS(RADIANS(store_lng) - RADIANS(%s)) + SIN(RADIANS(%s)) * SIN(RADIANS(store_lat)))) <= 1
                ORDER BY distance ASC;'''

            cursor.execute(geoQuery, (lat, lng, lat, lat, lng, lat))
            rows = cursor.fetchall()

            for row in rows:
                store_logo_url = s3.generate_presigned_url('get_object',
                                                            Params={'Bucket': bucket_name,
                                                                    'Key': f'logo/store_logo_{row[1]}.png',
                                                                    },
                                                        ExpiresIn=3600)
                store = {
                    # "owner_id": row[0],
                    "store_id": row[1],
                    "store_name": row[2],
                    "store_logo": store_logo_url,

                    # "status": row[3],
                    # "inspection_status": row[4],
                    # "open_yn": row[5],
                    # "store_photo_cnt": row[6],
                    "store_lat": row[7],
                    "store_lng": row[8],
                    # "distance": row[9],  # Include the calculated distance
                }
                storeList.append(store)
                
            # storeList에서 store_id 기준으로 중복 제거
            unique_store_dict = {store["store_id"]: store for store in storeList}

            # 중복 제거된 storeList 생성
            storeList = list(unique_store_dict.values())

            result = {
                'statusCode': 200,
                'storeList': storeList
            }
        return result
    except Exception as e:
        print(e)
        result = {
            'statusCode': 500,
            'msg': "failed searech store",
        }
    finally:
        connection.close()
        
@router.get("/search/{lat}/{lng}")
def getCurrentLocationStore(item: str, lat: float, lng: float):
    connection = pymysql.connect(
    host = dbinfo.db_host,
    user = dbinfo.db_username,
    passwd = dbinfo.db_password,
    db = dbinfo.db_name,
    port = dbinfo.db_port
    ) 

    bucket_name = "cafe-platform-bucket"

    s3 = boto3.client('s3',aws_access_key_id='***REMOVED_AWS_KEY***',
                    aws_secret_access_key='***REMOVED_AWS_SECRET***',
                    region_name='ap-northeast-2',
                    config= Config(signature_version='s3v4'))

    try:
        cursor = connection.cursor()
        storeList = []

        geoQuery = '''SELECT
                    owner_id,
                    store_id,
                    store_name,
                    status,
                    inspection_status,
                    open_yn,
                    store_photo_cnt,
                    store_lat,
                    store_lng,
                    (6371 * ACOS(COS(RADIANS(%s)) * COS(RADIANS(store_lat)) * COS(RADIANS(store_lng) - RADIANS(%s)) + SIN(RADIANS(%s)) * SIN(RADIANS(store_lat)))) AS distance
                FROM
                    Store
                WHERE
                    (6371 * ACOS(COS(RADIANS(%s)) * COS(RADIANS(store_lat)) * COS(RADIANS(store_lng) - RADIANS(%s)) + SIN(RADIANS(%s)) * SIN(RADIANS(store_lat)))) <= 1
                ORDER BY distance ASC;'''

        cursor.execute(geoQuery, (lat, lng, lat, lat, lng, lat))
        rows = cursor.fetchall()

        for row in rows:
            store = {
                "owner_id": row[0],
                "store_id": row[1],
                "store_name": row[2],
                "status": row[3],
                "inspection_status": row[4],
                "open_yn": row[5],
                "store_photo_cnt": row[6],
                "store_lat": row[7],
                "store_lng": row[8],
                "distance": row[9],  # Include the calculated distance
            }
            storeList.append(store)

        return result
    except Exception as e:
        print(e)
        result = {
            'statusCode': 500,
            'msg': "failed update owner",
            'owner_id': -1
        }
    finally:
        connection.close()