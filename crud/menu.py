"""
Menu CRUD 로직
"""
import uuid
import pymysql
from typing import List, Dict, Optional

from db.session import get_db_connection, close_db_connection
from core.s3_config import S3_CLIENT, BUCKET_NAME

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
                menu_photo_url = s3.generate_presigned_url('get_object',
                    Params={'Bucket': bucket_name, 'Key': row['image_key']},
                    ExpiresIn=3600)

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

    menu_get_url = s3.generate_presigned_url('get_object',
        Params={'Bucket': bucket_name, 'Key': image_key},
        ExpiresIn=3600)

    return {
        'image_key': image_key,
        'menu_put_url': menu_put_url,
        'menu_get_url': menu_get_url
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

