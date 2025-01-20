import traceback
from fastapi import APIRouter, HTTPException
from fastapi import FastAPI

from fastapi import FastAPI
from typing import Optional, Union
from pydantic import BaseModel

import pymysql
import app.database as database
import boto3
from botocore.client import Config

from models.store import StoreCreate
from models.store import InspectionStatusUpdate
from app.database import get_db_connection
from app.settings import settings


# router = APIRouter()

# prefix = "/dev" if settings.debug == True else ""

# prefix = "/dev" if settings.debug == True else ""
# router = APIRouter(prefix="prefix")

# @router.get(f"{prefix}/list")
router = APIRouter()

bucket_name = "cafe-platform-bucket"

s3 = boto3.client('s3', aws_access_key_id='***REMOVED_AWS_KEY***',
                  aws_secret_access_key='***REMOVED_AWS_SECRET***',
                  region_name='ap-northeast-2',
                  config=Config(signature_version='s3v4'))

@router.get("/list")
def getStoreList():
    connection = get_db_connection()  # 환경에 맞는 DB 연결
    cursor = connection.cursor(pymysql.cursors.DictCursor)  # DB에 접속 및 DB 객체를 가져옴

    try:
        
        cursor.execute('''
        SELECT
            owner_id, 
            store_id, 
            store_name, 
            status, 
            inspection_status, 
            open_yn,
            store_photo_cnt,
            store_lat, 
            store_lng,
            updated_time,
            store_telephone,
            store_description,
            store_address
        FROM Store
        ORDER BY updated_time DESC
        ''')
        
        # DB에서 데이터를 가져오기
        rows = cursor.fetchall()
        storeList = []
        
        # print("읽어온 데이터:", rows)

        for row in rows:
            print(row)
            print("row1", row['owner_id'])
            store_id = row['store_id']

            # S3에서 store_logo URL 생성
            store_logo_url = s3.generate_presigned_url('get_object',
                Params={'Bucket': bucket_name,
                        'Key': f'logo/store_logo_{store_id}.png'},
                ExpiresIn=3600)
            
            # S3에서 store_photo URLs 생성
            store_photo_urls = []
            print("1")
            for i in range(1, row['store_photo_cnt'] + 1):  # row[6]은 store_photo_cnt
                s3_url = s3.generate_presigned_url('get_object',
                    Params={'Bucket': bucket_name,
                            'Key': f'store_image/store_image_{store_id}_{i}.png'},
                    ExpiresIn=3600)
                store_photo_urls.append(s3_url)

            # store 데이터를 구성
            store = {
                "owner_id": row['owner_id'],
                "store_id": row['store_id'],
                "store_name": row['store_name'],
                "store_logo": store_logo_url,
                "store_photo_urls": store_photo_urls,
                "status": row['status'],
                "inspection_status": row['inspection_status'],
                "open_yn": row['open_yn'],
                "store_lat": row['store_lat'],
                "store_lng": row['store_lng'],
                "updated_time": row['updated_time'],
                "store_telephone": row['store_telephone'],
                "store_description": row['store_description'],
                "store_address": row['store_address'],
            }
            storeList.append(store)

        return {"statusCode": 200, "store": storeList}
    
    except Exception as e:
        print(f"오류 발생: {str(e)}")
        print("스택 트레이스:")
        traceback.print_exc() 
        return {"statusCode": 500, "message": "서버 오류 발생"}



@router.get("/list/{owner_id}")
def getStore(owner_id: int):
    connection = get_db_connection()  # 환경에 맞는 DB 연결
    cursor = connection.cursor(pymysql.cursors.DictCursor) # DB에 접속 및 DB 객체를 가져옴
    
    bucket_name = "cafe-platform-bucket"

    s3 = boto3.client('s3',aws_access_key_id='***REMOVED_AWS_KEY***',
                      aws_secret_access_key='***REMOVED_AWS_SECRET***',
                      region_name='ap-northeast-2',
                      config= Config(signature_version='s3v4'))
                      
    try:
        owner_id = owner_id
            
        cursor.execute('''select
        owner_id, 
        store_id, 
        store_name, 
        status, 
        inspection_status, 
        open_yn,
        store_photo_cnt,
        store_lat, 
        store_lng,
        store_address,
        updated_time,
        inspection_msg
        from Store where owner_id=%s ;''', owner_id)
        
        rows = cursor.fetchall()   
        storeList = []
        
        for row in rows:
            store_id = row['store_id']

            store_logo_url = s3.generate_presigned_url('get_object',
                                                    Params={'Bucket': bucket_name,
                                                            'Key': f'logo/store_logo_{store_id}.png',
                                                            },
                                                  ExpiresIn=3600)
                                                  
            store_photo_urls = []
        
            for i in range(1, row['store_photo_cnt']+1):
                s3_url = s3.generate_presigned_url('get_object',
                                                            Params={'Bucket': bucket_name,
                                                                    'Key': f'store_image/store_image_{store_id}_{i}.png',
                                                                    },
                                                          ExpiresIn=3600)

                store_photo_urls.append(s3_url) 
            
            store = {
                "owner_id": row['owner_id'],
                "store_id": row['store_id'],
                "store_name": row['store_name'],
                "store_logo": store_logo_url,
                "store_photo_urls": store_photo_urls,
                "status": row['status'],
                "inspection_status": row['inspection_status'],
                "open_yn": row['open_yn'],
                "store_lat": row['store_lat'],
                "store_lng": row['store_lng'],
                "store_address": row['store_address'],
                "updated_time": row['updated_time'],
                "inspection_msg": row['inspection_msg'],
            }
            storeList.append(store)
        
        return {
            'statusCode': 200,
            'store': storeList
        }
    except Exception as e:
        print(f"오류 발생: {str(e)}")
        print("스택 트레이스:")
        traceback.print_exc() 
        result = {
            'statusCode': 500,
            'msg': "failed get store list",
        }
        return result
    finally:        
        cursor.close()
        connection.close()
    # return {"item_id": item_id}
    
@router.post("/register")
async def registerStore(store: StoreCreate):
    connection = get_db_connection()  # 환경에 맞는 DB 연결
    bucket_name = "cafe-platform-bucket"

    s3 = boto3.client('s3',aws_access_key_id='***REMOVED_AWS_KEY***',
                      aws_secret_access_key='***REMOVED_AWS_SECRET***',
                      region_name='ap-northeast-2',
                      config= Config(signature_version='s3v4'))
                          
    cursor = connection.cursor()
    
    try:
        query = """
            INSERT INTO Store (
                owner_id, store_name, store_telephone, store_description, store_address, store_lat, store_lng, store_photo_cnt
            ) VALUES (
              {},'{}','{}', '{}', '{}', {}, {}, {}
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

        store_id = cursor.lastrowid
        print(store_id)

        store_logo_url = s3.generate_presigned_url('put_object',
                                                    Params={'Bucket': bucket_name,
                                                            'Key': f'logo/store_logo_{store_id}.png',
                                                            },
                                                  ExpiresIn=3600)
                                                  

        bankBook_put_url = s3.generate_presigned_url('put_object',
                                                    Params={'Bucket': bucket_name,
                                                            'Key': f'bankbook/bankbook_{store.owner_id}.png',
                                                            },
                                                  ExpiresIn=3600)
        
        business_put_url = s3.generate_presigned_url('put_object',
                                                    Params={'Bucket': bucket_name,
                                                            'Key': f'business_registration/business_registration_{store.owner_id}.png',
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
    
        
        return {
            'statusCode': 200,
            'store_id': store_id,
            'store_logo_url': store_logo_url,
            'store_photo_urls': store_photo_urls,
            'bankBook_put_url': bankBook_put_url,
            'business_put_url': business_put_url
        }
    except Exception as e:
        print(e)
        result = {
            'statusCode': 500,
            'msg': "failed register store - " + str(e),
            'store_photo_urls': [],
            'store_photo_get_urls': [],
            'bankbook_put_url': "",
            'business_put_url': ""
            }
        return result
    finally:
        connection.close()

#store.store_photo_cnt이 -1이면 이미지 변경은 없다는 의미
@router.post("/update/{store_id}")
def updateStore(store_id: int, store: StoreCreate):
    connection = get_db_connection()  # 환경에 맞는 DB 연결
    bucket_name = "cafe-platform-bucket"

    s3 = boto3.client('s3',aws_access_key_id='***REMOVED_AWS_KEY***',
                      aws_secret_access_key='***REMOVED_AWS_SECRET***',
                      region_name='ap-northeast-2',
                      config= Config(signature_version='s3v4'))
    
    try:
        cursor = connection.cursor()
        
        #기존에 저장된 이미지 삭제
        cursor.execute('''select
        store_photo_cnt
        from Store where store_id=%s ;''', (store_id,))
        
        stored_photo_cnt = cursor.fetchone()
        print('stored_photo_cnt', stored_photo_cnt)
        # # 저장된 값이 없거나 None인 경우 처리
        # if stored_photo_cnt:
        #     stored_photo_cnt = stored_photo_cnt[0]  # 튜플에서 첫 번째 값 추출
        # else:
        #     stored_photo_cnt = 0        
             
        if store.store_photo_cnt != -1: # 변경된 이미지가 있을 때만 저장된 이미지 삭제
            if stored_photo_cnt or stored_photo_cnt != 0:  # 조회 결과가 있는지 확인
                stored_photo_cnt = stored_photo_cnt[0] 
                for i in range(1, stored_photo_cnt+1):
                    object_key =  f'store_image/store_image_{store_id}_{i}.png'
                    s3.delete_object(Bucket=bucket_name, Key=object_key)
                
        query = "UPDATE Store SET "
        values = []
        print("store.store_photo_cnt", store.store_photo_cnt)

        if store.store_address:
            query += "store_address = %s, "
            values.append(store.store_address)
        if store.store_telephone:
            query += "store_telephone = %s, "
            values.append(store.store_telephone)
        if store.store_description:
            query += "store_description = %s, "
            values.append(store.store_description)
        if store.store_photo_cnt != -1:
            query += "store_photo_cnt = %s, "
            values.append(store.store_photo_cnt)
            
        query += "inspection_status = %s, "
        values.append(0)

        query = query[:-2]  # 마지막 쉼표와 공백 제거
        query += " WHERE store_id = %s"
        values.append(store_id)

        cursor.execute(query, tuple(values))
        connection.commit()

        store_photo_urls = []
        store_photo_get_urls = []
        
        updated_stored_photo_cnt = store.store_photo_cnt
        print("stored_photo_cnt", stored_photo_cnt)
        #새로 업데이트 된 이미지 저장 
        for i in range(1, updated_stored_photo_cnt+1):
            if store.store_photo_cnt != -1: # 변경된 이미지가 있을 때만 저장된 이미지 put
                s3_put_url = s3.generate_presigned_url('put_object',
                                                        Params={'Bucket': bucket_name,
                                                                'Key': f'store_image/store_image_{store_id}_{i}.png',
                                                                },
                                                    ExpiresIn=3600)
                store_photo_urls.append(s3_put_url)

            s3_get_url = s3.generate_presigned_url('get_object',
                                                Params={'Bucket': bucket_name,
                                                        'Key': f'store_image/store_image_{store_id}_{i}.png',
                                                        },
                                                ExpiresIn=3600)
            
            store_photo_get_urls.append(s3_get_url)
                
        print("store_photo_urls", store_photo_get_urls)
        
        result = {
            'statusCode': 200,
            'msg': "success",
            'store_photo_urls': store_photo_urls,
            'store_photo_get_urls': store_photo_get_urls
        }
        
        return result
    except Exception as e:
        print(e)
        result = {
            'statusCode': 500,
            'msg': "failed update owner",
            'store_photo_urls': [],
            'store_photo_get_urls': []
        }
    finally:
        connection.close()

@router.post("/delete/{store_id}")
def deleteStore():
    connection = get_db_connection()  # 환경에 맞는 DB 연결 
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
    connection = get_db_connection()  # 환경에 맞는 DB 연결

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
    connection = get_db_connection()  # 환경에 맞는 DB 연결
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

@router.get("/info/{store_id}")
def getStoreInfo(store_id: int):
    connection = get_db_connection()  # 환경에 맞는 DB 연결
    cursor = connection.cursor(pymysql.cursors.DictCursor) # DB에 접속 및 DB 객체를 가져옴
    
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
        store_address, 
        store_telephone,
        store_description,
        store_photo_cnt,
        store_address,
        store_lat, 
        store_lng,
        updated_time,
        inspection_status,
        inspection_msg
        from Store WHERE store_id=%s ;''', (store_id, ))
        
        store = cursor.fetchone()


        if store:
            store_logo_url = s3.generate_presigned_url('get_object',
                                                    Params={'Bucket': bucket_name,
                                                            'Key': f'logo/store_logo_{store_id}.png',
                                                            },
                                                  ExpiresIn=3600)
                                                  
            store_photo_urls = []
            store_photo_cnt = store['store_photo_cnt']

            for i in range(1, store_photo_cnt+1):
                s3_url = s3.generate_presigned_url('get_object',
                                                            Params={'Bucket': bucket_name,
                                                                    'Key': f'store_image/store_image_{store_id}_{i}.png',
                                                                    },
                                                          ExpiresIn=3600)

                store_photo_urls.append(s3_url) 
            
            store = {
                "owner_id": store['owner_id'],
                "store_id": store['store_id'],
                "store_name": store['store_name'],
                "store_logo": store_logo_url,
                "store_telephone": store['store_telephone'],
                "store_address": store['store_address'],
                "store_photo_urls": store_photo_urls,
                "store_description": store['store_description'],
                "store_lat": store['store_lat'],
                "store_lng": store['store_lng'],
                "updated_time": store['updated_time'],
                "inspection_status": store['inspection_status'],
                "inspection_msg": store['inspection_msg']
            }
    
        return {
            'statusCode': 200,
            'store': store
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

# @router.patch("/store/{store_id}/inspection", status_code=status.HTTP_201_CREATED)
@router.patch("/{storeId}/inspection")
def update_inspection_status(storeId: int, status_update: InspectionStatusUpdate):
    if status_update.inspection_status not in [0, 1, 2]:
        raise HTTPException(status_code=400, detail="Invalid inspection status")
    
    try:
        connection = get_db_connection()  # 환경에 맞는 DB 연결
        cursor = connection.cursor(pymysql.cursors.DictCursor) # DB에 접속 및 DB 객체를 가져옴
        
       # SQL 쿼리 수정: 상태와 메시지를 함께 업데이트
        update_query = """
            UPDATE Store
            SET inspection_status = %s, inspection_msg = %s
            WHERE store_id = %s
        """
        
        # 쿼리 실행
        cursor.execute(update_query, (status_update.inspection_status, status_update.inspection_msg, storeId))
        connection.commit()

        # 상태 변경 성공
        if cursor.rowcount > 0:
            return {"message": f"Store {storeId} inspection status updated to {status_update.inspection_status}"}
        else:
            raise HTTPException(status_code=404, detail="Store not found")

    except Exception as e:
        print(e)
        raise HTTPException(status_code=500, detail="Failed to update inspection status")

    finally:
        cursor.close()
        connection.close()