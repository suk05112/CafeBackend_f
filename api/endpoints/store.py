import traceback
import os
import uuid
from fastapi import APIRouter, HTTPException, status, Query
from typing import Optional, Union, List, Dict
from pydantic import BaseModel

import pymysql
import app.database as database
from botocore.exceptions import ClientError
import logging
from cachetools import TTLCache
import threading

from models.store import StoreCreate
from models.store import InspectionStatusUpdate
from db.session import get_db_connection, close_db_connection
from core.config import settings
from core.region_code import get_region_from_district, get_region_name, get_district_name
from core.s3_config import S3_CLIENT, BUCKET_NAME
from app.aligo_service import send_store_review_result
from core.exceptions import InternalError

logger = logging.getLogger("cafe_backend")

router = APIRouter()

s3 = S3_CLIENT
bucket_name = BUCKET_NAME

# S3 Presigned URL 캐시 (최대 2000개, TTL 3000초 — S3 만료 3600초보다 짧게)
_presigned_cache: TTLCache = TTLCache(maxsize=2000, ttl=3000)
_cache_lock = threading.Lock()


def _get_presigned_url(key: str) -> str:
    with _cache_lock:
        if key in _presigned_cache:
            return _presigned_cache[key]
    url = s3.generate_presigned_url('get_object',
        Params={'Bucket': bucket_name, 'Key': key},
        ExpiresIn=3600)
    with _cache_lock:
        _presigned_cache[key] = url
    return url


def _generate_logo_key(store_id: int) -> str:
    return f'store_logo/store_logo_{store_id}_{uuid.uuid4().hex[:8]}.png'

def _generate_bankbook_key(store_id: int) -> str:
    return f'bankbook/bankbook_{store_id}_{uuid.uuid4().hex[:8]}.png'

def _generate_business_key(store_id: int) -> str:
    return f'business_registration/business_registration_{store_id}_{uuid.uuid4().hex[:8]}.png'

def _get_store_logo_url(store_logo_key: str) -> Optional[str]:
    if not store_logo_key:
        return None
    return _get_presigned_url(store_logo_key)

def _get_store_photo_urls(cursor, store_id: int) -> List[str]:
    """store_images 테이블에서 매장 사진 presigned GET URL 목록 반환"""
    cursor.execute(
        "SELECT image_key FROM store_images WHERE store_id = %s ORDER BY `order` ASC",
        (store_id,)
    )
    rows = cursor.fetchall()
    return [_get_presigned_url(row['image_key'] if isinstance(row, dict) else row[0]) for row in rows]

def _get_store_photo_urls_bulk(cursor, store_ids: List[int]) -> Dict[int, List[str]]:
    """여러 store_id의 store_images를 한 번의 쿼리로 배치 조회"""
    if not store_ids:
        return {}
    placeholders = ','.join(['%s'] * len(store_ids))
    cursor.execute(
        f"SELECT store_id, image_key FROM store_images WHERE store_id IN ({placeholders}) ORDER BY store_id, `order` ASC",
        store_ids
    )
    result: Dict[int, List[str]] = {sid: [] for sid in store_ids}
    for row in cursor.fetchall():
        sid = row['store_id'] if isinstance(row, dict) else row[0]
        key = row['image_key'] if isinstance(row, dict) else row[1]
        result[sid].append(_get_presigned_url(key))
    return result


def _delete_store_images(cursor, connection, store_id: int) -> None:
    """store_images 테이블 레코드 삭제 및 S3 객체 삭제"""
    cursor.execute(
        "SELECT image_key FROM store_images WHERE store_id = %s",
        (store_id,)
    )
    rows = cursor.fetchall()
    for row in rows:
        key = row['image_key'] if isinstance(row, dict) else row[0]
        s3.delete_object(Bucket=bucket_name, Key=key)
    cursor.execute("DELETE FROM store_images WHERE store_id = %s", (store_id,))


def _insert_store_images(cursor, store_id: int, image_count: int):
    """store_images 테이블에 uuid 키 INSERT 후 put_url 목록 반환"""
    result = []
    for i in range(image_count):
        image_key = f'store_image/store_image_{store_id}_{uuid.uuid4().hex[:8]}.png'
        cursor.execute(
            "INSERT INTO store_images (store_id, image_key, `order`) VALUES (%s, %s, %s)",
            (store_id, image_key, i)
        )
        put_url = s3.generate_presigned_url('put_object',
            Params={'Bucket': bucket_name, 'Key': image_key},
            ExpiresIn=3600)
        result.append({'image_key': image_key, 'put_url': put_url})
    return result

@router.get("/search")
def searchStore(
    query: str = Query(..., description="검색어"),
    cursor: Optional[int] = Query(None, description="페이지네이션 커서 (마지막 store_id)"),
    limit: int = Query(50, description="한 번에 가져올 최대 개수 (기본값: 50, 최대: 200)")
):
    """
    FULLTEXT 인덱스를 사용한 매장명 검색 API
    Cursor-based 페이지네이션을 지원합니다.
    cursor는 마지막으로 반환된 store_id를 사용합니다.
    """
    # limit 최대값 제한
    if limit > 200:
        limit = 200
    if limit < 1:
        limit = 50
    
    connection = get_db_connection()  # 환경에 맞는 DB 연결
    db_cursor = connection.cursor(pymysql.cursors.DictCursor)  # DB에 접속 및 DB 객체를 가져옴

    try:
        
        # FULLTEXT 검색 쿼리 (MATCH AGAINST 사용)
        # inspection_status는 'APPROVED'만 허용, 메뉴 1개 이상인 것만
        # cursor가 있으면 해당 store_id보다 작은 것만 조회
        if cursor:
            db_cursor.execute('''
            SELECT
                s.owner_id,
                s.id,
                s.store_name,
                s.status,
                s.inspection_status,
                s.open_yn,
                s.store_description,
                s.store_address,
                s.store_logo_key,
                MATCH(s.store_name) AGAINST(%s IN NATURAL LANGUAGE MODE) AS relevance
            FROM store s
            WHERE s.inspection_status = 'APPROVED'
              AND s.contract_completed = 'COMPLETED'
              AND MATCH(s.store_name) AGAINST(%s IN NATURAL LANGUAGE MODE)
              AND s.id < %s
              AND EXISTS (
                  SELECT 1 FROM menu m WHERE m.store_id = s.id
              )
            ORDER BY relevance DESC, s.id DESC
            LIMIT %s
            ''', (query, query, cursor, limit))
        else:
            db_cursor.execute('''
            SELECT
                s.owner_id,
                s.id,
                s.store_name,
                s.status,
                s.inspection_status,
                s.open_yn,
                s.store_description,
                s.store_address,
                s.store_logo_key,
                MATCH(s.store_name) AGAINST(%s IN NATURAL LANGUAGE MODE) AS relevance
            FROM store s
            WHERE s.inspection_status = 'APPROVED'
              AND s.contract_completed = 'COMPLETED'
              AND MATCH(s.store_name) AGAINST(%s IN NATURAL LANGUAGE MODE)
              AND EXISTS (
                  SELECT 1 FROM menu m WHERE m.store_id = s.id
              )
            ORDER BY relevance DESC, s.id DESC
            LIMIT %s
            ''', (query, query, limit))

        # DB에서 데이터를 가져오기
        rows = db_cursor.fetchall()
        storeList = []

        for row in rows:
            store_id = row['id']
            store_logo_url = _get_store_logo_url(row['store_logo_key'])

            # store 데이터를 구성
            store = {
                "owner_id": row['owner_id'],
                "store_id": row['id'],
                "store_name": row['store_name'],
                "store_logo": store_logo_url,
                "status": row['status'],
                "inspection_status": row['inspection_status'],
                "open_yn": row['open_yn'],
                "store_description": row['store_description'],
                "store_address": row['store_address'],
            }
            storeList.append(store)

        # 페이지네이션 정보 계산
        # 다음 페이지가 있는지 확인 (반환된 데이터가 limit과 같으면 다음 페이지가 있을 가능성이 있음)
        has_next = len(storeList) == limit
        next_cursor = None
        if storeList:
            # 마지막 항목의 store_id를 다음 cursor로 사용
            next_cursor = storeList[-1]['store_id']
        
        return {
            "store": storeList,
            "pagination": {
                "cursor": cursor,
                "next_cursor": next_cursor,
                "limit": limit,
                "has_next": has_next
            }
        }
    
    except Exception as e:
        traceback.print_exc()
        raise InternalError(e, "getStoreMenu")
    finally:
        db_cursor.close()
        close_db_connection(connection)

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
            s.store_lat,
            s.store_lng,
            s.updated_at,
            s.store_telephone,
            s.store_description,
            s.store_address,
            s.store_logo_key
        FROM store s
        INNER JOIN menu m ON s.id = m.store_id
        WHERE (s.inspection_status = 'APPROVED' OR s.inspection_status = 1)
          AND s.contract_completed = 'COMPLETED'
        ORDER BY s.updated_at DESC
        ''')

        # DB에서 데이터를 가져오기
        rows = cursor.fetchall()
        store_ids = [row['id'] for row in rows]
        photo_urls_map = _get_store_photo_urls_bulk(cursor, store_ids)
        storeList = []

        for row in rows:
            store_id = row['id']
            store = {
                "owner_id": row['owner_id'],
                "store_id": store_id,
                "store_name": row['store_name'],
                "store_logo": _get_store_logo_url(row['store_logo_key']),
                "store_photo_urls": photo_urls_map.get(store_id, []),
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
        traceback.print_exc()
        raise InternalError(e, "getStoreList")
    finally:
        cursor.close()
        close_db_connection(connection)

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
        traceback.print_exc()
        raise InternalError(e, "store endpoint")
    finally:
        cursor.close()
        close_db_connection(connection)

@router.get("/regions-districts")
def getRegionsAndDistricts(offset: Optional[int] = Query(0, description="페이지네이션 오프셋"), limit: int = Query(50, description="한 번에 가져올 최대 개수")):
    """
    현재 존재하는 매장의 region과 district 코드 및 이름을 반환합니다.
    region별로 그룹화하여 반환합니다.
    성능 최적화: GROUP BY를 사용하여 DB 레벨에서 그룹화 (DISTINCT보다 효율적)
    """
    connection = get_db_connection()  # 환경에 맞는 DB 연결
    db_cursor = connection.cursor(pymysql.cursors.DictCursor)  # DB에 접속 및 DB 객체를 가져옴

    try:
        # GROUP BY를 사용하여 DB 레벨에서 그룹화 (성능 최적화)
        # 인덱스가 있으면 매우 빠르게 조회됨
        # offset과 limit을 사용한 페이지네이션
        db_cursor.execute('''
        SELECT DISTINCT
            s.region_code,
            s.district_code
        FROM store s
        INNER JOIN menu m ON s.id = m.store_id
        WHERE s.region_code IS NOT NULL 
          AND s.district_code IS NOT NULL
          AND s.inspection_status = 'APPROVED'
          AND s.contract_completed = 'COMPLETED'
        GROUP BY s.region_code, s.district_code
        HAVING COUNT(m.id) >= 1
        ORDER BY s.region_code, s.district_code
        LIMIT %s OFFSET %s
        ''', (limit, offset))
        
        rows = db_cursor.fetchall()
        
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
        traceback.print_exc()
        raise InternalError(e, "store endpoint")
    finally:
        db_cursor.close()
        close_db_connection(connection)

@router.get("/list/by-district/{district_code}")
def getStoreListByDistrict(
    district_code: str, 
    cursor: Optional[str] = Query(None, description="페이지네이션 커서 (updated_at,store_id 형식)"),
    limit: int = Query(50, description="한 번에 가져올 최대 개수 (기본값: 50, 최대: 200)")
):
    """
    지역별 매장 목록 조회 API
    Cursor-based 페이지네이션을 지원합니다.
    cursor 형식: "updated_at,store_id" (예: "2025-01-01 00:00:00,123")
    """
    # limit 최대값 제한
    if limit > 200:
        limit = 200
    if limit < 1:
        limit = 50
    
    connection = get_db_connection()  # 환경에 맞는 DB 연결
    db_cursor = connection.cursor(pymysql.cursors.DictCursor)  # DB에 접속 및 DB 객체를 가져옴

    try:
        # 1. district 코드에서 region(시/도) 코드 추출 (DB 조회 없이)
        region_code = get_region_from_district(district_code)
        
        if not region_code:
            return {
                "store": [],
                "pagination": {
                    "cursor": cursor,
                    "next_cursor": None,
                    "limit": limit,
                    "has_next": False
                }
            }
        
        # cursor 파싱 (updated_at,store_id 형식)
        cursor_updated_at = None
        cursor_store_id = None
        if cursor:
            try:
                parts = cursor.split(',')
                if len(parts) == 2:
                    cursor_updated_at = parts[0]
                    cursor_store_id = int(parts[1])
            except (ValueError, IndexError):
                # 잘못된 cursor 형식이면 무시하고 처음부터 조회
                cursor_updated_at = None
                cursor_store_id = None
        
        # 2. 해당 region(시/도)에 속한 모든 카페 조회 (리스트용 간단한 정보만)
        # inspection_status는 'APPROVED'만, 메뉴 1개 이상인 것만, cursor 기반 페이지네이션
        if cursor_updated_at and cursor_store_id:
            db_cursor.execute('''
            SELECT
                s.id,
                s.store_name,
                s.open_yn,
                s.store_address,
                s.store_description,
                s.updated_at,
                s.store_logo_key,
                s.store_lat,
                s.store_lng
            FROM store s
            WHERE s.region_code = %s
              AND s.inspection_status = 'APPROVED'
              AND s.contract_completed = 'COMPLETED'
              AND (
                  s.updated_at < %s
                  OR (s.updated_at = %s AND s.id < %s)
              )
              AND EXISTS (SELECT 1 FROM menu m WHERE m.store_id = s.id)
            ORDER BY s.updated_at DESC, s.id DESC
            LIMIT %s
            ''', (region_code, cursor_updated_at, cursor_updated_at, cursor_store_id, limit))
        else:
            db_cursor.execute('''
            SELECT
                s.id,
                s.store_name,
                s.open_yn,
                s.store_address,
                s.store_description,
                s.updated_at,
                s.store_logo_key,
                s.store_lat,
                s.store_lng
            FROM store s
            WHERE s.region_code = %s
              AND s.inspection_status = 'APPROVED'
              AND s.contract_completed = 'COMPLETED'
              AND EXISTS (SELECT 1 FROM menu m WHERE m.store_id = s.id)
            ORDER BY s.updated_at DESC, s.id DESC
            LIMIT %s
            ''', (region_code, limit))

        # DB에서 데이터를 가져오기
        rows = db_cursor.fetchall()
        storeList = []

        for row in rows:
            store_id = row['id']
            store_logo_url = _get_store_logo_url(row['store_logo_key'])

            # 리스트용 간단한 store 데이터 구성
            store = {
                "store_id": store_id,
                "store_name": row['store_name'],
                "store_logo": store_logo_url,
                "open_yn": row['open_yn'],
                "store_address": row['store_address'],
                "store_description": row['store_description'],
                "store_lat": row['store_lat'],
                "store_lng": row['store_lng'],
            }
            storeList.append(store)

        # 페이지네이션 정보 계산
        has_next = len(storeList) == limit
        next_cursor = None
        if storeList:
            # 마지막 항목의 updated_at과 store_id를 조합하여 다음 cursor 생성
            last_item = storeList[-1]
            # updated_at은 쿼리 결과에서 가져오기
            last_updated_at = None
            for row in rows:
                if row['id'] == last_item['store_id']:
                    last_updated_at = row.get('updated_at')
                    if last_updated_at:
                        # datetime을 문자열로 변환
                        if hasattr(last_updated_at, 'strftime'):
                            last_updated_at = last_updated_at.strftime('%Y-%m-%d %H:%M:%S')
                        else:
                            last_updated_at = str(last_updated_at)
                    break
            
            if last_updated_at:
                next_cursor = f"{last_updated_at},{last_item['store_id']}"
        
        return {
            "store": storeList,
            "pagination": {
                "cursor": cursor,
                "next_cursor": next_cursor,
                "limit": limit,
                "has_next": has_next
            }
        }
    
    except Exception as e:
        traceback.print_exc()
        raise InternalError(e, "store endpoint")
    finally:
        db_cursor.close()
        close_db_connection(connection)

@router.get("/list/by-location")
def getStoreListByLocation(lat: float, lng: float):
    """
    지도 중심 3KM 반경 내의 매장 조회
    inspection_status는 'APPROVED'만, 메뉴 1개 이상인 것만 반환
    """
    connection = get_db_connection()  # 환경에 맞는 DB 연결
    cursor = connection.cursor(pymysql.cursors.DictCursor)  # DB에 접속 및 DB 객체를 가져옴

    try:
        # 지도 중심 3KM 반경 내의 매장 조회 (Haversine 공식 사용)
        # inspection_status는 'APPROVED'만, 메뉴 1개 이상인 것만
        cursor.execute('''
        SELECT DISTINCT
            s.id,
            s.store_name,
            s.open_yn,
            s.store_address,
            s.store_description,
            s.store_lat,
            s.store_lng,
            s.store_logo_key,
            (6371 * ACOS(COS(RADIANS(%s)) * COS(RADIANS(s.store_lat)) *
                COS(RADIANS(s.store_lng) - RADIANS(%s)) +
                SIN(RADIANS(%s)) * SIN(RADIANS(s.store_lat)))) AS distance
        FROM store s
        INNER JOIN menu m ON s.id = m.store_id
        WHERE s.store_lat IS NOT NULL
          AND s.store_lng IS NOT NULL
          AND s.inspection_status = 'APPROVED'
          AND s.contract_completed = 'COMPLETED'
        GROUP BY s.id
        HAVING COUNT(m.id) >= 1
          AND (6371 * ACOS(COS(RADIANS(%s)) * COS(RADIANS(s.store_lat)) *
                COS(RADIANS(s.store_lng) - RADIANS(%s)) +
                SIN(RADIANS(%s)) * SIN(RADIANS(s.store_lat)))) <= 3
        ORDER BY distance ASC
        ''', (lat, lng, lat, lat, lng, lat))

        # DB에서 데이터를 가져오기
        rows = cursor.fetchall()
        storeList = []

        for row in rows:
            store_id = row['id']
            store_logo_url = _get_store_logo_url(row['store_logo_key'])

            # 리스트용 간단한 store 데이터 구성
            store = {
                "store_id": store_id,
                "store_name": row['store_name'],
                "store_logo": store_logo_url,
                "open_yn": row['open_yn'],
                "store_address": row['store_address'],
                "store_description": row['store_description'],
                "store_lat": row['store_lat'],
                "store_lng": row['store_lng'],
            }
            storeList.append(store)

        return {"store": storeList}
    
    except Exception as e:
        traceback.print_exc()
        raise InternalError(e, "store endpoint")
    finally:
        cursor.close()
        close_db_connection(connection)

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
        s.store_lat,
        s.store_lng,
        s.store_address,
        s.updated_at,
        s.inspection_msg,
        s.store_logo_key
        FROM store s
        INNER JOIN menu m ON s.id = m.store_id
        WHERE s.owner_id = %s
          AND (s.inspection_status = 'APPROVED' OR s.inspection_status = 1)
        ORDER BY s.updated_at DESC''', (owner_id,))

        rows = cursor.fetchall()
        store_ids = [row['id'] for row in rows]
        photo_urls_map = _get_store_photo_urls_bulk(cursor, store_ids)
        storeList = []

        for row in rows:
            store_id = row['id']
            store = {
                "owner_id": row['owner_id'],
                "store_id": store_id,
                "store_name": row['store_name'],
                "store_logo": _get_store_logo_url(row['store_logo_key']),
                "store_photo_urls": photo_urls_map.get(store_id, []),
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
        close_db_connection(connection)
    
@router.post("/register")
async def registerStore(store: StoreCreate):
    connection = get_db_connection()  # 환경에 맞는 DB 연결
                          
    cursor = connection.cursor()
    
    try:
        # district_code에서 region_code 자동 계산
        region_code = None
        district_code = store.district_code
        
        if district_code:
            region_code = get_region_from_district(district_code)
        
        # region_code와 district_code를 포함한 INSERT 쿼리
        query = """
            INSERT INTO store (
                owner_id, store_name, store_telephone, store_description, store_address,
                store_lat, store_lng, region_code, district_code
            ) VALUES (
              %s, %s, %s, %s, %s, %s, %s, %s, %s
            );
        """
        cursor.execute(query, (
            store.owner_id,
            store.store_name,
            store.store_telephone,
            store.store_description,
            store.store_address,
            store.store_lat,
            store.store_lng,
            region_code,
            district_code
        ))
            
        connection.commit()

        store_id = cursor.lastrowid
        print(store_id)

        logo_key = _generate_logo_key(store_id)
        bankbook_key = _generate_bankbook_key(store_id)
        business_key = _generate_business_key(store_id)

        cursor.execute(
            "UPDATE store SET store_logo_key = %s, bankbook_key = %s, business_registration_key = %s WHERE id = %s",
            (logo_key, bankbook_key, business_key, store_id)
        )

        store_logo_put_url = s3.generate_presigned_url('put_object',
            Params={'Bucket': bucket_name, 'Key': logo_key}, ExpiresIn=3600)
        bankBook_put_url = s3.generate_presigned_url('put_object',
            Params={'Bucket': bucket_name, 'Key': bankbook_key}, ExpiresIn=3600)
        business_put_url = s3.generate_presigned_url('put_object',
            Params={'Bucket': bucket_name, 'Key': business_key}, ExpiresIn=3600)

        image_count = store.image_count if store.image_count is not None else 0
        store_photos = _insert_store_images(cursor, store_id, image_count)
        connection.commit()

        return {
            'store_id': store_id,
            'store_logo_put_url': store_logo_put_url,
            'store_photos': store_photos,
            'bankBook_put_url': bankBook_put_url,
            'business_put_url': business_put_url
        }
    except HTTPException:
        raise
    except Exception as e:
        connection.rollback()
        raise InternalError(e, "registerStore")
    finally:
        close_db_connection(connection)

@router.post("/update/{store_id}")
def updateStore(store_id: int, store: StoreCreate):
    connection = get_db_connection()

    try:
        cursor = connection.cursor(pymysql.cursors.DictCursor)

        cursor.execute("SELECT inspection_status FROM store WHERE id = %s", (store_id,))
        current = cursor.fetchone()
        current_status = current['inspection_status'] if current else None

        query = "UPDATE store SET "
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

        logo_key = _generate_logo_key(store_id)
        bankbook_key = _generate_bankbook_key(store_id)
        business_key = _generate_business_key(store_id)

        query += "store_logo_key = %s, bankbook_key = %s, business_registration_key = %s, "
        values.extend([logo_key, bankbook_key, business_key])

        if current_status == 'REJECTED':
            query += "inspection_status = %s, "
            values.append('PENDING')

        query = query[:-2]
        query += " WHERE id = %s"
        values.append(store_id)

        cursor.execute(query, tuple(values))

        store_photos = []

        if store.image_count is not None:
            _delete_store_images(cursor, connection, store_id)
            store_photos = _insert_store_images(cursor, store_id, store.image_count)

        connection.commit()

        store_photo_get_urls = _get_store_photo_urls(cursor, store_id)

        store_logo_put_url = s3.generate_presigned_url('put_object',
            Params={'Bucket': bucket_name, 'Key': logo_key}, ExpiresIn=3600)
        bankBook_put_url = s3.generate_presigned_url('put_object',
            Params={'Bucket': bucket_name, 'Key': bankbook_key}, ExpiresIn=3600)
        business_put_url = s3.generate_presigned_url('put_object',
            Params={'Bucket': bucket_name, 'Key': business_key}, ExpiresIn=3600)

        return {
            'msg': "success",
            'store_logo_put_url': store_logo_put_url,
            'bankBook_put_url': bankBook_put_url,
            'business_put_url': business_put_url,
            'store_photos': store_photos,
            'store_photo_get_urls': store_photo_get_urls
        }
    except Exception as e:
        connection.rollback()
        raise InternalError(e, "updateStore")
    finally:
        close_db_connection(connection)

@router.post("/delete/{store_id}")
def deleteStore(store_id: int):
    connection = get_db_connection()  # 환경에 맞는 DB 연결 
    try:
        cursor = connection.cursor()
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
        raise InternalError(e, "deleteStore")
    finally:
        close_db_connection(connection)

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
        store_lat,
        store_lng,
        store_logo_key
        from store'''

        if item and item.strip():
            itemQuery += " WHERE store_name LIKE %s AND inspection_status = 'APPROVED' AND contract_completed = 'COMPLETED'"
            item_param = f"%{item}%"
            cursor.execute(itemQuery, (item_param,))
        
            rows = cursor.fetchall()
            # row = rows[0]

            print("검색된 리스트", rows)

            if rows:
                for row in rows:
                    print(row)
                    store_logo_url = _get_store_logo_url(row[8])
                    store = {
                        "store_id": row[1],
                        "store_name": row[2],
                        "store_logo": store_logo_url,
                        "store_lat": row[6],
                        "store_lng": row[7],
                    }
                    storeList.append(store)

                geoQuery = '''SELECT
                    owner_id,
                    id,
                    store_name,
                    status,
                    inspection_status,
                    open_yn,
                    store_lat,
                    store_lng,
                    (6371 * ACOS(COS(RADIANS(%s)) * COS(RADIANS(store_lat)) * COS(RADIANS(store_lng) - RADIANS(%s)) + SIN(RADIANS(%s)) * SIN(RADIANS(store_lat)))) AS distance,
                    store_logo_key
                FROM
                    store
                WHERE
                    inspection_status = 'APPROVED'
                    AND contract_completed = 'COMPLETED'
                    AND (6371 * ACOS(COS(RADIANS(%s)) * COS(RADIANS(store_lat)) * COS(RADIANS(store_lng) - RADIANS(%s)) + SIN(RADIANS(%s)) * SIN(RADIANS(store_lat)))) <= 1
                ORDER BY distance ASC;'''

                cursor.execute(geoQuery, (lat, lng, lat, lat, lng, lat))
                rows = cursor.fetchall()

                for row in rows:
                    store_logo_url = _get_store_logo_url(row[9])
                    store = {
                        "store_id": row[1],
                        "store_name": row[2],
                        "store_logo": store_logo_url,
                        "store_lat": row[6],
                        "store_lng": row[7],
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
                    store_lat,
                    store_lng,
                    (6371 * ACOS(COS(RADIANS(%s)) * COS(RADIANS(store_lat)) * COS(RADIANS(store_lng) - RADIANS(%s)) + SIN(RADIANS(%s)) * SIN(RADIANS(store_lat)))) AS distance,
                    store_logo_key
                FROM
                    store
                WHERE
                    inspection_status = 'APPROVED'
                    AND contract_completed = 'COMPLETED'
                    AND (6371 * ACOS(COS(RADIANS(%s)) * COS(RADIANS(store_lat)) * COS(RADIANS(store_lng) - RADIANS(%s)) + SIN(RADIANS(%s)) * SIN(RADIANS(store_lat)))) <= 1
                ORDER BY distance ASC;'''

            cursor.execute(geoQuery, (lat, lng, lat, lat, lng, lat))
            rows = cursor.fetchall()

            for row in rows:
                store_logo_url = _get_store_logo_url(row[9])
                store = {
                    "store_id": row[1],
                    "store_name": row[2],
                    "store_logo": store_logo_url,
                    "store_lat": row[6],
                    "store_lng": row[7],
                }
                storeList.append(store)
                
            # storeList에서 store_id 기준으로 중복 제거
            unique_store_dict = {store["store_id"]: store for store in storeList}

            # 중복 제거된 storeList 생성
            storeList = list(unique_store_dict.values())

            return {"storeList": storeList}
    except Exception as e:
        raise InternalError(e, "searchStore")
    finally:
        close_db_connection(connection)
        
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
                    store_lat,
                    store_lng,
                    (6371 * ACOS(COS(RADIANS(%s)) * COS(RADIANS(store_lat)) * COS(RADIANS(store_lng) - RADIANS(%s)) + SIN(RADIANS(%s)) * SIN(RADIANS(store_lat)))) AS distance
                FROM
                    store
                WHERE
                    inspection_status = 'APPROVED'
                    AND contract_completed = 'COMPLETED'
                    AND (6371 * ACOS(COS(RADIANS(%s)) * COS(RADIANS(store_lat)) * COS(RADIANS(store_lng) - RADIANS(%s)) + SIN(RADIANS(%s)) * SIN(RADIANS(store_lat)))) <= 1
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
                "store_lat": row[6],
                "store_lng": row[7],
                "distance": row[8],
            }
            storeList.append(store)

        return {"storeList": storeList}
    except Exception as e:
        raise InternalError(e, "getCurrentLocationStore")
    finally:
        cursor.close()
        close_db_connection(connection)

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
        store_lat,
        store_lng,
        updated_at,
        inspection_status,
        inspection_msg,
        store_logo_key
        from store WHERE id=%s ;''', (store_id, ))

        store = cursor.fetchone()


        if store:
            photo_urls_map = _get_store_photo_urls_bulk(cursor, [store_id])
            store = {
                "owner_id": store['owner_id'],
                "store_id": store['id'],
                "store_name": store['store_name'],
                "store_logo": _get_store_logo_url(store['store_logo_key']),
                "store_telephone": store['store_telephone'],
                "store_address": store['store_address'],
                "store_photo_urls": photo_urls_map.get(store_id, []),
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
        raise InternalError(e, "getStoreInfo")
    finally:        
        cursor.close()
        close_db_connection(connection)

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
        
        # 먼저 store와 owner 전화번호 함께 조회
        cursor.execute('''
            SELECT s.id, s.store_name, o.phone
            FROM store s
            JOIN owner o ON s.owner_id = o.id
            WHERE s.id = %s
        ''', (storeId,))
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
            if status_value in ("APPROVED", "REJECTED") and store.get("phone"):
                result_text = "승인" if status_value == "APPROVED" else "반려"
                detail_text = status_update.inspection_msg or ("-" if status_value == "APPROVED" else "사유 없음")
                send_store_review_result(
                    receiver=store["phone"],
                    result=result_text,
                    detail=detail_text,
                    recvname="사장님",
                )
            return {"message": f"Store {storeId} inspection status updated to {status_value}"}
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update inspection status"
            )

    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise InternalError(e, "update_inspection_status")
    finally:
        if cursor:
            cursor.close()
        if connection:
            close_db_connection(connection)


@router.patch("/{storeId}/contract")
def update_contract_status(storeId: int, body: dict):
    """계약상태 업데이트 (NONE: 미계약, SENT: 계약서전송, COMPLETED: 계약완료)"""
    contract_status = body.get('contract_status')
    if contract_status not in ('NONE', 'SENT', 'COMPLETED'):
        raise HTTPException(status_code=400, detail="contract_status must be one of: NONE, SENT, COMPLETED")

    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(pymysql.cursors.DictCursor)
        cursor.execute('SELECT id FROM store WHERE id = %s', (storeId,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail=f"Store {storeId} not found")
        cursor.execute('UPDATE store SET contract_completed = %s WHERE id = %s', (contract_status, storeId))
        connection.commit()
        return {"message": f"Store {storeId} contract_status updated to {contract_status}"}
    except HTTPException:
        raise
    except Exception as e:
        raise InternalError(e, "update_contract_status")
    finally:
        if cursor:
            cursor.close()
        if connection:
            close_db_connection(connection)
