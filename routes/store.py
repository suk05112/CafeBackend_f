import traceback
import os
from fastapi import APIRouter, HTTPException, status
from fastapi import FastAPI

from fastapi import FastAPI
from typing import Optional, Union
from pydantic import BaseModel

import pymysql
import app.database as database
from botocore.exceptions import ClientError
from loguru import logger

from models.store import StoreCreate
from models.store import InspectionStatusUpdate
from app.database import get_db_connection
from app.settings import settings
from app.region_code import get_region_from_district, get_region_name, get_district_name
from app.s3_config import S3_CLIENT, BUCKET_NAME

router = APIRouter()

# S3 설정은 app.s3_config에서 가져옴
s3 = S3_CLIENT
bucket_name = BUCKET_NAME

@router.get("/list")
def getStoreList():
    connection = get_db_connection()  # 환경에 맞는 DB 연결
    cursor = connection.cursor(pymysql.cursors.DictCursor)  # DB에 접속 및 DB 객체를 가져옴

    try:
        cursor.execute('''
        SELECT DISTINCT
            s.owner_id, 
            s.id, 
            s.store_name, 
            s.status, 
            s.inspection_status, 
            s.open_yn,
            s.store_photo_cnt,
            s.store_lat, 
            s.store_lng,
            s.updated_at,
            s.store_telephone,
            s.store_description,
            s.store_address
        FROM store s
        INNER JOIN menu m ON s.id = m.store_id
        WHERE (s.inspection_status = 'APPROVED' OR s.inspection_status = 1)
        ORDER BY s.updated_at DESC
        ''')
        
        # DB에서 데이터를 가져오기
        rows = cursor.fetchall()
        storeList = []
        
        for row in rows:
            store_id = row['id']

            # S3에서 store_logo 존재 여부 확인
            logo_key = f'store_logo/store_logo_{store_id}.png'
            store_logo_url = None
            
            try:
                s3.head_object(Bucket=bucket_name, Key=logo_key)
                # 로고가 존재하면 로고 URL 생성
                store_logo_url = s3.generate_presigned_url('get_object',
                    Params={'Bucket': bucket_name,
                            'Key': logo_key},
                    ExpiresIn=3600)
            except ClientError as e:
                # 로고가 없으면 store_image_1 사용
                if e.response['Error']['Code'] == '404':
                    try:
                        image_key = f'store_image/store_image_{store_id}_1.png'
                        s3.head_object(Bucket=bucket_name, Key=image_key)
                        store_logo_url = s3.generate_presigned_url('get_object',
                            Params={'Bucket': bucket_name,
                                    'Key': image_key},
                            ExpiresIn=3600)
                    except ClientError:
                        # store_image_1도 없으면 None
                        store_logo_url = None
                else:
                    store_logo_url = None
            
            # S3에서 store_photo URLs 생성
            store_photo_urls = []
            store_photo_cnt = row['store_photo_cnt'] if row['store_photo_cnt'] is not None else 0
            for i in range(1, store_photo_cnt + 1):  # row[6]은 store_photo_cnt
                s3_url = s3.generate_presigned_url('get_object',
                    Params={'Bucket': bucket_name,
                            'Key': f'store_image/store_image_{store_id}_{i}.png'},
                    ExpiresIn=3600)
                store_photo_urls.append(s3_url)

            # store 데이터를 구성
            store = {
                "owner_id": row['owner_id'],
                "store_id": row['id'],
                "store_name": row['store_name'],
                "store_logo": store_logo_url,
                "store_photo_urls": store_photo_urls,
                "status": row['status'],
                "inspection_status": row['inspection_status'],
                "open_yn": row['open_yn'],
                "store_lat": row['store_lat'],
                "store_lng": row['store_lng'],
                "updated_time": row['updated_at'],
                "store_telephone": row['store_telephone'],
                "store_description": row['store_description'],
                "store_address": row['store_address'],
            }
            storeList.append(store)

        return {"store": storeList}
    
    except Exception as e:
        print(f"오류 발생: {str(e)}")
        print("스택 트레이스:")
        traceback.print_exc() 
        logger.error(f"서버 오류 발생: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"서버 오류 발생: {str(e)}"
        )
    finally:
        cursor.close()
        connection.close()

@router.get("/owner/list/{owner_id}")
def getOwnerStoreList(owner_id: int):
    connection = get_db_connection()  # 환경에 맞는 DB 연결
    cursor = connection.cursor(pymysql.cursors.DictCursor)  # DB에 접속 및 DB 객체를 가져옴

    try:
        cursor.execute('''
        SELECT DISTINCT
            s.id, 
            s.store_name
        FROM store s
        INNER JOIN menu m ON s.id = m.store_id
        WHERE s.owner_id = %s
          AND (s.inspection_status = 'APPROVED' OR s.inspection_status = 1)
        ORDER BY s.updated_at DESC
        ''', (owner_id,))
        
        rows = cursor.fetchall()
        storeList = []
        
        for row in rows:
            print(row)

            # store 데이터를 구성
            store = {
                "store_id": row['id'],
                "store_name": row['store_name'],
            }
            storeList.append(store)

        return {"ownerStoreList": storeList}
    
    except Exception as e:
        print(f"오류 발생: {str(e)}")
        print("스택 트레이스:")
        traceback.print_exc() 
        logger.error(f"서버 오류 발생: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"서버 오류 발생: {str(e)}"
        )
    finally:
        cursor.close()
        connection.close()

@router.get("/regions-districts")
def getRegionsAndDistricts():
    """
    현재 존재하는 매장의 region과 district 코드 및 이름을 반환합니다.
    region별로 그룹화하여 반환합니다.
    성능 최적화: GROUP BY를 사용하여 DB 레벨에서 그룹화 (DISTINCT보다 효율적)
    """
    connection = get_db_connection()  # 환경에 맞는 DB 연결
    cursor = connection.cursor(pymysql.cursors.DictCursor)  # DB에 접속 및 DB 객체를 가져옴

    try:
        # GROUP BY를 사용하여 DB 레벨에서 그룹화 (성능 최적화)
        # 인덱스가 있으면 매우 빠르게 조회됨
        cursor.execute('''
        SELECT DISTINCT
            s.region_code,
            s.district_code
        FROM store s
        INNER JOIN menu m ON s.id = m.store_id
        WHERE s.region_code IS NOT NULL 
          AND s.district_code IS NOT NULL
          AND (s.inspection_status = 'APPROVED' OR s.inspection_status = 1)
        GROUP BY s.region_code, s.district_code
        ORDER BY s.region_code, s.district_code
        ''')
        
        rows = cursor.fetchall()
        
        # region별로 그룹화
        region_dict = {}
        for row in rows:
            region_code = row['region_code']
            district_code = row['district_code']
            
            if region_code not in region_dict:
                region_dict[region_code] = []
            
            # district 정보를 딕셔너리로 저장 (코드와 이름)
            district_info = {
                "district_code": district_code,
                "district_name": get_district_name(district_code)
            }
            
            # 중복 체크 (같은 district_code가 이미 있는지 확인)
            existing = [d for d in region_dict[region_code] if d["district_code"] == district_code]
            if not existing:
                region_dict[region_code].append(district_info)
        
        # 리스트 형태로 변환
        region_list = []
        for region_code, districts in region_dict.items():
            # district_code 기준으로 정렬
            sorted_districts = sorted(districts, key=lambda x: int(x["district_code"]))
            region_list.append({
                "region_code": region_code,
                "region_name": get_region_name(region_code),
                "districts": sorted_districts
            })
        
        # region_code 기준으로 정렬
        region_list.sort(key=lambda x: int(x["region_code"]))
        
        return {"regions": region_list}
    
    except Exception as e:
        print(f"오류 발생: {str(e)}")
        print("스택 트레이스:")
        traceback.print_exc() 
        logger.error(f"서버 오류 발생: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"서버 오류 발생: {str(e)}"
        )
    finally:
        cursor.close()
        connection.close()

@router.get("/list/by-district/{district_code}")
def getStoreListByDistrict(district_code: str):
    connection = get_db_connection()  # 환경에 맞는 DB 연결
    cursor = connection.cursor(pymysql.cursors.DictCursor)  # DB에 접속 및 DB 객체를 가져옴

    try:
        # 1. district 코드에서 region(시/도) 코드 추출 (DB 조회 없이)
        region_code = get_region_from_district(district_code)
        
        if not region_code:
            return {"store": []}
        
        # 2. 해당 region(시/도)에 속한 모든 카페 조회 (리스트용 간단한 정보만)
        cursor.execute('''
        SELECT DISTINCT
            s.id, 
            s.store_name, 
            s.open_yn,
            s.store_address,
            s.store_description
        FROM store s
        INNER JOIN menu m ON s.id = m.store_id
        WHERE s.region_code = %s
          AND (s.inspection_status = 'APPROVED' OR s.inspection_status = 1)
        ORDER BY s.updated_at DESC
        ''', (region_code,))
        
        # DB에서 데이터를 가져오기
        rows = cursor.fetchall()
        storeList = []
        
        for row in rows:
            store_id = row['id']

            # S3에서 store_logo 존재 여부 확인
            logo_key = f'store_logo/store_logo_{store_id}.png'
            store_logo_url = None
            
            try:
                s3.head_object(Bucket=bucket_name, Key=logo_key)
                # 로고가 존재하면 로고 URL 생성
                store_logo_url = s3.generate_presigned_url('get_object',
                    Params={'Bucket': bucket_name,
                            'Key': logo_key},
                    ExpiresIn=3600)
            except ClientError as e:
                # 로고가 없으면 store_image_1 사용
                if e.response['Error']['Code'] == '404':
                    try:
                        image_key = f'store_image/store_image_{store_id}_1.png'
                        s3.head_object(Bucket=bucket_name, Key=image_key)
                        store_logo_url = s3.generate_presigned_url('get_object',
                            Params={'Bucket': bucket_name,
                                    'Key': image_key},
                            ExpiresIn=3600)
                    except ClientError:
                        # store_image_1도 없으면 None
                        store_logo_url = None
                else:
                    store_logo_url = None

            # 리스트용 간단한 store 데이터 구성
            store = {
                "store_id": store_id,
                "store_name": row['store_name'],
                "store_logo": store_logo_url,
                "open_yn": row['open_yn'],
                "store_address": row['store_address'],
                "store_description": row['store_description'],
            }
            storeList.append(store)

        return {"store": storeList}
    
    except Exception as e:
        print(f"오류 발생: {str(e)}")
        print("스택 트레이스:")
        traceback.print_exc() 
        logger.error(f"서버 오류 발생: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"서버 오류 발생: {str(e)}"
        )
    finally:
        cursor.close()
        connection.close()

@router.get("/list/by-location")
def getStoreListByLocation(lat: float, lng: float):
    connection = get_db_connection()  # 환경에 맞는 DB 연결
    cursor = connection.cursor(pymysql.cursors.DictCursor)  # DB에 접속 및 DB 객체를 가져옴

    try:
        # 1. 가장 가까운 카페의 district 코드 가져오기 (승인된 매장, 메뉴 있는 매장만)
        cursor.execute('''
        SELECT DISTINCT s.district_code 
        FROM store s
        INNER JOIN menu m ON s.id = m.store_id
        WHERE s.store_lat IS NOT NULL 
          AND s.store_lng IS NOT NULL 
          AND s.district_code IS NOT NULL
          AND (s.inspection_status = 'APPROVED' OR s.inspection_status = 1)
        ORDER BY (POW(s.store_lat - %s, 2) + POW(s.store_lng - %s, 2))
        LIMIT 1
        ''', (lat, lng))
        
        result = cursor.fetchone()
        if not result or not result.get('district_code'):
            return {"store": []}
        
        # 2. district 코드에서 region(시/도) 코드 추출 (DB 조회 없이)
        region_code = get_region_from_district(result['district_code'])
        
        if not region_code:
            return {"store": []}
        
        # 3. 해당 region(시/도)에 속한 모든 카페 조회 (리스트용 간단한 정보만)
        cursor.execute('''
        SELECT DISTINCT
            s.id, 
            s.store_name, 
            s.open_yn,
            s.store_address,
            s.store_description,
            s.store_lat,
            s.store_lng
        FROM store s
        INNER JOIN menu m ON s.id = m.store_id
        WHERE s.region_code = %s
          AND (s.inspection_status = 'APPROVED' OR s.inspection_status = 1)
        ORDER BY s.updated_at DESC
        ''', (region_code,))
        
        # DB에서 데이터를 가져오기
        rows = cursor.fetchall()
        storeList = []
        
        for row in rows:
            store_id = row['id']

            # S3에서 store_logo 존재 여부 확인
            logo_key = f'store_logo/store_logo_{store_id}.png'
            store_logo_url = None
            
            try:
                s3.head_object(Bucket=bucket_name, Key=logo_key)
                # 로고가 존재하면 로고 URL 생성
                store_logo_url = s3.generate_presigned_url('get_object',
                    Params={'Bucket': bucket_name,
                            'Key': logo_key},
                    ExpiresIn=3600)
            except ClientError as e:
                # 로고가 없으면 store_image_1 사용
                if e.response['Error']['Code'] == '404':
                    try:
                        image_key = f'store_image/store_image_{store_id}_1.png'
                        s3.head_object(Bucket=bucket_name, Key=image_key)
                        store_logo_url = s3.generate_presigned_url('get_object',
                            Params={'Bucket': bucket_name,
                                    'Key': image_key},
                            ExpiresIn=3600)
                    except ClientError:
                        # store_image_1도 없으면 None
                        store_logo_url = None
                else:
                    store_logo_url = None

            # 리스트용 간단한 store 데이터 구성
            store = {
                "store_id": store_id,
                "store_name": row['store_name'],
                "store_logo": store_logo_url,
                "open_yn": row['open_yn'],
                "store_address": row['store_address'],
                "store_description": row['store_description'],
                "store_lat": row['store_lat'],
                "store_lng": row['store_lng']
            }
            storeList.append(store)
            print(storeList)

        return {"store": storeList}
    
    except Exception as e:
        print(f"오류 발생: {str(e)}")
        print("스택 트레이스:")
        traceback.print_exc() 
        logger.error(f"서버 오류 발생: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"서버 오류 발생: {str(e)}"
        )
    finally:
        cursor.close()
        connection.close()

@router.get("/list/{owner_id}")
def getStore(owner_id: int):
    connection = get_db_connection()  # 환경에 맞는 DB 연결
    cursor = connection.cursor(pymysql.cursors.DictCursor) # DB에 접속 및 DB 객체를 가져옴
                      
    try:
        owner_id = owner_id
            
        cursor.execute('''SELECT DISTINCT
        s.owner_id, 
        s.id, 
        s.store_name, 
        s.status, 
        s.inspection_status, 
        s.open_yn,
        s.store_photo_cnt,
        s.store_lat, 
        s.store_lng,
        s.store_address,
        s.updated_at,
        s.inspection_msg
        FROM store s
        INNER JOIN menu m ON s.id = m.store_id
        WHERE s.owner_id = %s
          AND (s.inspection_status = 'APPROVED' OR s.inspection_status = 1)
        ORDER BY s.updated_at DESC''', (owner_id,))
        
        rows = cursor.fetchall()   
        storeList = []
        
        for row in rows:
            store_id = row['id']

            store_logo_url = s3.generate_presigned_url('get_object',
                                                    Params={'Bucket': bucket_name,
                                                            'Key': f'store_logo/store_logo_{store_id}.png',
                                                            },
                                                  ExpiresIn=3600)
                                                  
            store_photo_urls = []
        
            store_photo_cnt = row['store_photo_cnt'] if row['store_photo_cnt'] is not None else 0
            for i in range(1, store_photo_cnt+1):
                s3_url = s3.generate_presigned_url('get_object',
                                                            Params={'Bucket': bucket_name,
                                                                    'Key': f'store_image/store_image_{store_id}_{i}.png',
                                                                    },
                                                          ExpiresIn=3600)

                store_photo_urls.append(s3_url) 
            
            store = {
                "owner_id": row['owner_id'],
                "store_id": row['id'],
                "store_name": row['store_name'],
                "store_logo": store_logo_url,
                "store_photo_urls": store_photo_urls,
                "status": row['status'],
                "inspection_status": row['inspection_status'],
                "open_yn": row['open_yn'],
                "store_lat": row['store_lat'],
                "store_lng": row['store_lng'],
                "store_address": row['store_address'],
                "updated_time": row['updated_at'],
                "inspection_msg": row['inspection_msg'],
            }
            storeList.append(store)
        
        return {"store": storeList}
    except Exception as e:
        print(f"오류 발생: {str(e)}")
        print("스택 트레이스:")
        traceback.print_exc() 
        logger.error(f"서버 오류 발생: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="failed get store list"
        )
    finally:        
        cursor.close()
        connection.close()
    # return {"item_id": item_id}
    
@router.post("/register")
async def registerStore(store: StoreCreate):
    connection = get_db_connection()  # 환경에 맞는 DB 연결
                          
    cursor = connection.cursor()
    
    try:
        query = """
            INSERT INTO store (
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
                                                            'Key': f'store_logo/store_logo_{store_id}.png',
                                                            },
                                                  ExpiresIn=3600)
                                                  

        bankBook_put_url = s3.generate_presigned_url('put_object',
                                                    Params={'Bucket': bucket_name,
                                                            'Key': f'bankbook/bankbook_{store_id}.png',
                                                            },
                                                  ExpiresIn=3600)
        
        business_put_url = s3.generate_presigned_url('put_object',
                                                    Params={'Bucket': bucket_name,
                                                            'Key': f'business_registration/business_registration_{store_id}.png',
                                                            },
                                                  ExpiresIn=3600)                      
    
        store_photo_urls = []
        
        store_photo_cnt = store.store_photo_cnt if store.store_photo_cnt is not None else 0
        for i in range(1, store_photo_cnt+1):
            s3_url = s3.generate_presigned_url('put_object',
                                                    Params={'Bucket': bucket_name,
                                                            'Key': f'store_image/store_image_{store_id}_{i}.png',
                                                            },
                                                  ExpiresIn=3600)

            store_photo_urls.append(s3_url)
    
        
        return {
            'store_id': store_id,
            'store_logo_url': store_logo_url,
            'store_photo_urls': store_photo_urls,
            'bankBook_put_url': bankBook_put_url,
            'business_put_url': business_put_url
        }
    except Exception as e:
        print(e)
        logger.error(f"Error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"failed register store: {str(e)}"
        )
    
        # return result
    finally:
        connection.close()

#store.store_photo_cnt이 -1이면 이미지 변경은 없다는 의미
@router.post("/update/{store_id}")
def updateStore(store_id: int, store: StoreCreate):
    connection = get_db_connection()  # 환경에 맞는 DB 연
    
    try:
        cursor = connection.cursor()
        
        #기존에 저장된 이미지 삭제
        cursor.execute('''select
        store_photo_cnt
        from store where id=%s ;''', (store_id,))
        
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
                
        query = "UPDATE store SET "
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
        query += " WHERE id = %s"
        values.append(store_id)

        cursor.execute(query, tuple(values))
        connection.commit()

        store_photo_urls = []
        store_photo_get_urls = []
        
        updated_stored_photo_cnt = store.store_photo_cnt if store.store_photo_cnt is not None and store.store_photo_cnt != -1 else 0
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
        
        return {
            'msg': "success",
            'store_photo_urls': store_photo_urls,
            'store_photo_get_urls': store_photo_get_urls
        }
    except Exception as e:
        print(e)
        logger.error(f"서버 오류 발생: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="failed update store"
        )
    finally:
        connection.close()

@router.post("/delete/{store_id}")
def deleteStore():
    connection = get_db_connection()  # 환경에 맞는 DB 연결 
    try:
        cursor = connection.cursor()
        store_id = store_id
        query = "DELETE FROM store WHERE id = %s"

        cursor.execute(query, (store_id,))
        connection.commit()
        
        if cursor.rowcount > 0:
            return {
                'msg': "success",
                'store_id': store_id
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="no record found"
            )
    except HTTPException:
        raise
    except Exception as e:
        print(e)
        logger.error(f"서버 오류 발생: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="failed delete store"
        )
    finally:
        connection.close()

@router.get("/search/{item}/{lat}/{lng}")
def searchStore(item: str, lat: float, lng: float):
    connection = get_db_connection()  # 환경에 맞는 DB 연결

    try:
        cursor = connection.cursor()
        storeList = []

        itemQuery = '''select
        owner_id, 
        id, 
        store_name, 
        status, 
        inspection_status, 
        open_yn,
        store_photo_cnt,
        store_lat, 
        store_lng 
        from store'''

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
                                                                    'Key': f'store_logo/store_logo_{row[1]}.png',
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
                    id,
                    store_name,
                    status,
                    inspection_status,
                    open_yn,
                    store_photo_cnt,
                    store_lat,
                    store_lng,
                    (6371 * ACOS(COS(RADIANS(%s)) * COS(RADIANS(store_lat)) * COS(RADIANS(store_lng) - RADIANS(%s)) + SIN(RADIANS(%s)) * SIN(RADIANS(store_lat)))) AS distance
                FROM
                    store
                WHERE
                    (6371 * ACOS(COS(RADIANS(%s)) * COS(RADIANS(store_lat)) * COS(RADIANS(store_lng) - RADIANS(%s)) + SIN(RADIANS(%s)) * SIN(RADIANS(store_lat)))) <= 1
                ORDER BY distance ASC;'''

                cursor.execute(geoQuery, (lat, lng, lat, lat, lng, lat))
                rows = cursor.fetchall()

                for row in rows:
                    store_logo_url = s3.generate_presigned_url('get_object',
                                                            Params={'Bucket': bucket_name,
                                                                    'Key': f'store_logo/store_logo_{row[1]}.png',
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

                return {"storeList": storeList}
            else:
                return {"storeList": []}  
        else:
            geoQuery = '''SELECT
                    owner_id,
                    id,
                    store_name,
                    status,
                    inspection_status,
                    open_yn,
                    store_photo_cnt,
                    store_lat,
                    store_lng,
                    (6371 * ACOS(COS(RADIANS(%s)) * COS(RADIANS(store_lat)) * COS(RADIANS(store_lng) - RADIANS(%s)) + SIN(RADIANS(%s)) * SIN(RADIANS(store_lat)))) AS distance
                FROM
                    store
                WHERE
                    (6371 * ACOS(COS(RADIANS(%s)) * COS(RADIANS(store_lat)) * COS(RADIANS(store_lng) - RADIANS(%s)) + SIN(RADIANS(%s)) * SIN(RADIANS(store_lat)))) <= 1
                ORDER BY distance ASC;'''

            cursor.execute(geoQuery, (lat, lng, lat, lat, lng, lat))
            rows = cursor.fetchall()

            for row in rows:
                store_logo_url = s3.generate_presigned_url('get_object',
                                                            Params={'Bucket': bucket_name,
                                                                    'Key': f'store_logo/store_logo_{row[1]}.png',
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

            return {"storeList": storeList}
    except Exception as e:
        print(e)
        logger.error(f"서버 오류 발생: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="failed search store"
        )
    finally:
        connection.close()
        
@router.get("/search/{lat}/{lng}")
def getCurrentLocationStore(item: str, lat: float, lng: float):
    connection = get_db_connection()  # 환경에 맞는 DB 연결

    try:
        cursor = connection.cursor()
        storeList = []

        geoQuery = '''SELECT
                    owner_id,
                    id,
                    store_name,
                    status,
                    inspection_status,
                    open_yn,
                    store_photo_cnt,
                    store_lat,
                    store_lng,
                    (6371 * ACOS(COS(RADIANS(%s)) * COS(RADIANS(store_lat)) * COS(RADIANS(store_lng) - RADIANS(%s)) + SIN(RADIANS(%s)) * SIN(RADIANS(store_lat)))) AS distance
                FROM
                    store
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

        return {"storeList": storeList}
    except Exception as e:
        print(e)
        logger.error(f"서버 오류 발생: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="failed get current location store"
        )
    finally:
        cursor.close()
        connection.close()

@router.get("/info/{store_id}")
def getStoreInfo(store_id: int):
    connection = get_db_connection()  # 환경에 맞는 DB 연결
    cursor = connection.cursor(pymysql.cursors.DictCursor) # DB에 접속 및 DB 객체를 가져옴

                      
    try:      
        print("storeList 호출1")
      
        cursor.execute('''select 
        owner_id,
        id,
        store_name, 
        store_address, 
        store_telephone,
        store_description,
        store_photo_cnt,
        store_address,
        store_lat, 
        store_lng,
        updated_at,
        inspection_status,
        inspection_msg
        from store WHERE id=%s ;''', (store_id, ))
        
        store = cursor.fetchone()


        if store:
            store_logo_url = s3.generate_presigned_url('get_object',
                                                    Params={'Bucket': bucket_name,
                                                            'Key': f'store_logo/store_logo_{store_id}.png',
                                                            },
                                                  ExpiresIn=3600)
                                                  
            store_photo_urls = []
            store_photo_cnt = store['store_photo_cnt'] if store['store_photo_cnt'] is not None else 0

            for i in range(1, store_photo_cnt+1):
                s3_url = s3.generate_presigned_url('get_object',
                                                            Params={'Bucket': bucket_name,
                                                                    'Key': f'store_image/store_image_{store_id}_{i}.png',
                                                                    },
                                                          ExpiresIn=3600)

                store_photo_urls.append(s3_url) 
            
            store = {
                "owner_id": store['owner_id'],
                "store_id": store['id'],
                "store_name": store['store_name'],
                "store_logo": store_logo_url,
                "store_telephone": store['store_telephone'],
                "store_address": store['store_address'],
                "store_photo_urls": store_photo_urls,
                "store_description": store['store_description'],
                "store_lat": store['store_lat'],
                "store_lng": store['store_lng'],
                "updated_time": store['updated_at'],
                "inspection_status": store['inspection_status'],
                "inspection_msg": store['inspection_msg']
            }
    
        if not store:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Store not found"
            )
        return {"store": store}
    
    except HTTPException:
        raise
    except Exception as e:
        print(e)
        logger.error(f"서버 오류 발생: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="failed get store info"
        )
    finally:        
        cursor.close()
        connection.close()

# @router.patch("/store/{store_id}/inspection", status_code=status.HTTP_201_CREATED)
@router.patch("/{storeId}/inspection")
def update_inspection_status(storeId: int, status_update: InspectionStatusUpdate):
    # inspection_status를 문자열로 변환 (정수인 경우)
    status_value = status_update.inspection_status
    
    if isinstance(status_value, int):
        # 정수를 문자열로 매핑
        status_mapping = {
            0: "PENDING",
            1: "APPROVED",
            2: "REJECTED",
        }
        if status_value in status_mapping:
            status_value = status_mapping[status_value]
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid inspection status: {status_value}. Must be 0 (PENDING), 1 (APPROVED), or 2 (REJECTED)"
            )
    elif isinstance(status_value, str):
        # 문자열을 대문자로 정규화
        status_value = status_value.upper()
        # 유효한 문자열 값 검증
        valid_statuses = ["PENDING", "APPROVED", "REJECTED"]
        if status_value not in valid_statuses:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid inspection status: {status_value}. Must be one of: PENDING, APPROVED, REJECTED"
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid inspection status type: {type(status_value)}. Must be int or str"
        )
    
    connection = None
    cursor = None
    
    try:
        connection = get_db_connection()  # 환경에 맞는 DB 연결
        cursor = connection.cursor(pymysql.cursors.DictCursor) # DB에 접속 및 DB 객체를 가져옴
        
        # 먼저 store가 존재하는지 확인
        cursor.execute('''SELECT id FROM store WHERE id = %s''', (storeId,))
        store = cursor.fetchone()
        
        if not store:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Store with id {storeId} not found"
            )
        
        # SQL 쿼리 수정: 상태와 메시지를 함께 업데이트
        update_query = """
            UPDATE store
            SET inspection_status = %s, inspection_msg = %s
            WHERE id = %s
        """
        
        # 쿼리 실행
        cursor.execute(update_query, (status_value, status_update.inspection_msg, storeId))
        connection.commit()

        # 상태 변경 성공 확인
        if cursor.rowcount > 0:
            return {"message": f"Store {storeId} inspection status updated to {status_value}"}
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update inspection status"
            )

    except HTTPException:
        raise
    except Exception as e:
        print(f"오류 발생: {str(e)}")
        print("스택 트레이스:")
        traceback.print_exc()
        logger.error(f"서버 오류 발생: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update inspection status: {str(e)}"
        )

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()
        