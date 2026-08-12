"""
Menu CRUD 로직
"""
import math
import uuid
import pymysql
from typing import List, Dict, Optional

from db.session import get_db_connection, close_db_connection
from core.s3_config import S3_CLIENT, BUCKET_NAME, get_s3_public_url

# schemas는 models를 직접 참조
from models.menu import Menu

s3 = S3_CLIENT
bucket_name = BUCKET_NAME


def get_menus_by_store(store_id: int) -> List[Dict]:
    """매장별 메뉴 리스트 조회"""
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        cursor.execute("""
            SELECT id, menu_name, price, description, status, image_key
            FROM menu
            WHERE store_id = %s AND is_deleted = 0
        """, (store_id,))
        
        rows = cursor.fetchall()
        menus = []
        
        for row in rows:
            menu_photo_url = None
            if row['image_key']:
                menu_photo_url = get_s3_public_url(bucket_name, row['image_key'])

            menus.append({
                "menu_id": row['id'],
                "name": row['menu_name'],
                "price": row['price'],
                "description": row['description'],
                "status": row['status'],
                "menu_photo": menu_photo_url
            })
        
        return menus
    finally:
        cursor.close()
        close_db_connection(connection)


def get_voucher_menus() -> List[Dict]:
    """금액권(교환권) 상품 리스트 조회

    금액권은 전용 가상매장의 menu 레코드로 관리되며, 특정 매장에 속하지 않으므로
    매장 메뉴 추천과 달리 거리/지역 조건 없이 액면가 오름차순으로 반환한다.
    """
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)

    try:
        cursor.execute("""
            SELECT id, store_id, menu_name, price, description, image_key
            FROM menu
            WHERE product_type = 'VOUCHER' AND status = 'ACTIVE' AND is_deleted = 0
            ORDER BY price ASC
        """)

        rows = cursor.fetchall()
        vouchers = []

        for row in rows:
            menu_photo_url = None
            if row['image_key']:
                menu_photo_url = get_s3_public_url(bucket_name, row['image_key'])

            vouchers.append({
                # 구매 시 store_id가 필요하므로 앱이 하드코딩하지 않도록 함께 내려준다
                "store_id": row['store_id'],
                "menu_id": row['id'],
                "menu_name": row['menu_name'],
                "price": row['price'],
                "description": row['description'],
                "menu_photo": menu_photo_url,
            })

        return vouchers
    finally:
        cursor.close()
        close_db_connection(connection)


def get_menu_by_id(menu_id: int) -> Optional[Dict]:
    """메뉴 상세 조회"""
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        cursor.execute("""
            SELECT * FROM menu WHERE id = %s AND is_deleted = 0
        """, (menu_id,))
        
        row = cursor.fetchone()
        if not row:
            return None
        
        return dict(row)
    finally:
        cursor.close()
        close_db_connection(connection)


def create_menu(store_id: int, menu_data: Menu) -> int:
    """메뉴 생성"""
    connection = get_db_connection()
    cursor = connection.cursor()
    
    try:
        query = """
            INSERT INTO menu (store_id, menu_name, price, description, status)
            VALUES (%s, %s, %s, %s, %s)
        """

        cursor.execute(query, (
            store_id,
            menu_data.name,
            menu_data.price,
            menu_data.description,
            menu_data.status,
        ))
        connection.commit()
        
        return cursor.lastrowid
    except Exception as e:
        connection.rollback()
        raise e
    finally:
        cursor.close()
        close_db_connection(connection)


def generate_menu_s3_urls(store_id: int, menu_id: int) -> Dict:
    """메뉴 S3 presigned URLs 생성 (uuid 포함 고유 키 사용)"""
    image_key = f'menu/menu_{store_id}_{menu_id}_{uuid.uuid4().hex[:8]}.png'

    menu_put_url = s3.generate_presigned_url('put_object',
        Params={'Bucket': bucket_name, 'Key': image_key},
        ExpiresIn=3600)

    return {
        'image_key': image_key,
        'menu_put_url': menu_put_url,
        'menu_get_url': get_s3_public_url(bucket_name, image_key)
    }


def save_menu_image_key(menu_id: int, image_key: str) -> None:
    """메뉴 image_key DB 저장"""
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            "UPDATE menu SET image_key = %s WHERE id = %s",
            (image_key, menu_id)
        )
        connection.commit()
    except Exception as e:
        connection.rollback()
        raise e
    finally:
        cursor.close()
        close_db_connection(connection)


def update_menu(menu_id: int, store_id: int, menu_data: Menu) -> bool:
    """메뉴 정보 업데이트"""
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        query = "UPDATE menu SET menu_name = %s, price = %s, status = %s"
        values = [menu_data.name, menu_data.price, menu_data.status]

        if menu_data.description is not None:
            query += ", description = %s"
            values.append(menu_data.description)

        query += " WHERE id = %s AND is_deleted = 0"
        values.append(menu_id)

        cursor.execute(query, tuple(values))
        connection.commit()

        if cursor.rowcount == 0:
            # 동일한 값으로 업데이트 시 rowcount == 0 → 레코드 존재 여부로 판단
            cursor.execute("SELECT id FROM menu WHERE id = %s AND is_deleted = 0", (menu_id,))
            if cursor.fetchone() is None:
                return False

        if menu_data.change_image or menu_data.delete_image:
            cursor2 = connection.cursor(pymysql.cursors.DictCursor)
            cursor2.execute("SELECT image_key FROM menu WHERE id = %s", (menu_id,))
            row = cursor2.fetchone()
            cursor2.close()
            existing_key = row['image_key'] if row else None

            if existing_key:
                s3.delete_object(Bucket=bucket_name, Key=existing_key)

            if menu_data.delete_image:
                cursor.execute("UPDATE menu SET image_key = NULL WHERE id = %s", (menu_id,))
                connection.commit()

        return True
    except Exception as e:
        connection.rollback()
        raise e
    finally:
        cursor.close()
        close_db_connection(connection)


def get_recommended_menus_by_location(lat: float, lng: float, radius: float, limit: int, cursor: Optional[str]) -> Dict:
    """GPS 반경 기반 메뉴 추천 (거리순 정렬, cursor 페이지네이션)"""
    connection = get_db_connection()
    db_cursor = connection.cursor(pymysql.cursors.DictCursor)

    try:
        cursor_distance = None
        cursor_menu_id = None
        if cursor:
            try:
                parts = cursor.split(',')
                if len(parts) == 2:
                    cursor_distance = float(parts[0])
                    cursor_menu_id = int(parts[1])
            except (ValueError, IndexError):
                pass

        # lat/lng bounding box prefilter (인덱스 range scan 가능하도록)
        # 위도 1도 ≈ 111km, 경도 1도 ≈ 111 * cos(lat) km
        lat_delta = radius / 111.0
        cos_lat = math.cos(math.radians(lat))
        lng_delta = radius / (111.0 * cos_lat) if cos_lat > 1e-6 else 180.0
        min_lat = lat - lat_delta
        max_lat = lat + lat_delta
        min_lng = lng - lng_delta
        max_lng = lng + lng_delta

        base_select = """
            SELECT
                s.id AS store_id,
                s.store_name,
                s.store_logo_key,
                m.id AS menu_id,
                m.menu_name,
                m.price,
                m.description,
                m.image_key,
                (6371 * ACOS(COS(RADIANS(%s)) * COS(RADIANS(s.store_lat)) *
                    COS(RADIANS(s.store_lng) - RADIANS(%s)) +
                    SIN(RADIANS(%s)) * SIN(RADIANS(s.store_lat)))) AS distance
            FROM store s
            INNER JOIN menu m ON s.id = m.store_id
            WHERE s.store_lat BETWEEN %s AND %s
              AND s.store_lng BETWEEN %s AND %s
              AND s.inspection_status = 'APPROVED'
              AND s.contract_completed = 'COMPLETED'
              AND m.status = 'ACTIVE'
              AND m.is_deleted = 0
              AND m.image_key IS NOT NULL
        """

        having_distance = f"HAVING distance <= %s"

        if cursor_distance is not None and cursor_menu_id is not None:
            query = base_select + f"""
            {having_distance}
              AND (distance > %s OR (distance = %s AND m.id > %s))
            ORDER BY distance ASC, m.id ASC
            LIMIT %s
            """
            params = (lat, lng, lat, min_lat, max_lat, min_lng, max_lng,
                      radius, cursor_distance, cursor_distance, cursor_menu_id, limit)
        else:
            query = base_select + f"""
            {having_distance}
            ORDER BY distance ASC, m.id ASC
            LIMIT %s
            """
            params = (lat, lng, lat, min_lat, max_lat, min_lng, max_lng, radius, limit)

        db_cursor.execute(query, params)
        rows = db_cursor.fetchall()

        items = _build_menu_recommend_items(rows, include_distance=True)

        next_cursor = None
        if len(items) == limit and rows:
            last = rows[-1]
            next_cursor = f"{last['distance']},{last['menu_id']}"

        return {"menuList": items, "next_cursor": next_cursor, "has_next": len(items) == limit}
    finally:
        db_cursor.close()
        close_db_connection(connection)


def get_recommended_menus_by_district(district_code: str, limit: int, cursor: Optional[str]) -> Dict:
    """지역구 기반 메뉴 추천 (updated_at 기준 정렬, cursor 페이지네이션)"""
    from core.region_code import get_region_from_district
    connection = get_db_connection()
    db_cursor = connection.cursor(pymysql.cursors.DictCursor)

    try:
        region_code = get_region_from_district(district_code)
        if not region_code:
            return {"menuList": [], "next_cursor": None, "has_next": False}

        cursor_updated_at = None
        cursor_menu_id = None
        if cursor:
            try:
                parts = cursor.split(',')
                if len(parts) == 2:
                    cursor_updated_at = parts[0]
                    cursor_menu_id = int(parts[1])
            except (ValueError, IndexError):
                pass

        base_select = """
            SELECT
                s.id AS store_id,
                s.store_name,
                s.store_logo_key,
                s.updated_at,
                m.id AS menu_id,
                m.menu_name,
                m.price,
                m.description,
                m.image_key
            FROM store s
            INNER JOIN menu m ON s.id = m.store_id
            WHERE s.region_code = %s
              AND s.inspection_status = 'APPROVED'
              AND s.contract_completed = 'COMPLETED'
              AND m.status = 'ACTIVE'
              AND m.is_deleted = 0
              AND m.image_key IS NOT NULL
        """

        if cursor_updated_at and cursor_menu_id is not None:
            query = base_select + """
              AND (s.updated_at < %s OR (s.updated_at = %s AND m.id < %s))
            ORDER BY s.updated_at DESC, m.id DESC
            LIMIT %s
            """
            params = (region_code, cursor_updated_at, cursor_updated_at, cursor_menu_id, limit)
        else:
            query = base_select + """
            ORDER BY s.updated_at DESC, m.id DESC
            LIMIT %s
            """
            params = (region_code, limit)

        db_cursor.execute(query, params)
        rows = db_cursor.fetchall()

        items = _build_menu_recommend_items(rows, include_distance=False)

        next_cursor = None
        if len(items) == limit and rows:
            last = rows[-1]
            updated_at = last['updated_at']
            if hasattr(updated_at, 'strftime'):
                updated_at = updated_at.strftime('%Y-%m-%d %H:%M:%S')
            next_cursor = f"{updated_at},{last['menu_id']}"

        return {"menuList": items, "next_cursor": next_cursor, "has_next": len(items) == limit}
    finally:
        db_cursor.close()
        close_db_connection(connection)


def _build_menu_recommend_items(rows: List[Dict], include_distance: bool) -> List[Dict]:
    items = []
    for row in rows:
        menu_photo_url = None
        if row['image_key']:
            menu_photo_url = get_s3_public_url(bucket_name, row['image_key'])
        store_logo_url = None
        if row['store_logo_key']:
            store_logo_url = s3.generate_presigned_url(
                'get_object',
                Params={'Bucket': bucket_name, 'Key': row['store_logo_key']},
                ExpiresIn=3600
            )
        item = {
            "store_id": row['store_id'],
            "store_name": row['store_name'],
            "store_logo": store_logo_url,
            "menu_id": row['menu_id'],
            "menu_name": row['menu_name'],
            "price": row['price'],
            "description": row['description'],
            "menu_photo": menu_photo_url,
        }
        if include_distance:
            item["distance"] = round(row['distance'], 2)
        items.append(item)
    return items


def delete_menu(menu_id: int) -> bool:
    """메뉴 삭제 (soft delete)"""
    connection = get_db_connection()
    cursor = connection.cursor()
    
    try:
        query = "UPDATE menu SET is_deleted = 1 WHERE id = %s"
        cursor.execute(query, (menu_id,))
        connection.commit()
        
        return cursor.rowcount > 0
    except Exception as e:
        connection.rollback()
        raise e
    finally:
        cursor.close()
        close_db_connection(connection)

