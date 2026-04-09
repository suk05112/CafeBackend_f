"""
Menu CRUD 로직
"""
import pymysql
from typing import List, Dict, Optional

from db.session import get_db_connection
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
            SELECT id, menu_name, price, description, status 
            FROM menu 
            WHERE store_id = %s AND is_deleted = 0
        """, (store_id,))
        
        rows = cursor.fetchall()
        menus = []
        
        for row in rows:
            menu_id = row['id']
            menu_photo_url = None
            
            try:
                menu_key = f'menu/menu_{store_id}_{menu_id}.png'
                s3.head_object(Bucket=bucket_name, Key=menu_key)
                menu_photo_url = s3.generate_presigned_url('get_object',
                    Params={'Bucket': bucket_name, 'Key': menu_key},
                    ExpiresIn=3600)
            except:
                pass
            
            menus.append({
                "menu_id": row['id'],
                "store_id": store_id,
                "menu_name": row['menu_name'],
                "price": row['price'],
                "description": row['description'],
                "status": row['status'],
                "menu_photo": menu_photo_url
            })
        
        return menus
    finally:
        cursor.close()
        connection.close()


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
        connection.close()


def create_menu(store_id: int, menu_data: Menu) -> int:
    """메뉴 생성"""
    connection = get_db_connection()
    cursor = connection.cursor()
    
    try:
        query = """
            INSERT INTO menu (store_id, menu_name, price, description)
            VALUES (%s, %s, %s, %s)
        """
        
        cursor.execute(query, (
            store_id,
            menu_data.name,
            menu_data.price,
            menu_data.description,
        ))
        connection.commit()
        
        return cursor.lastrowid
    except Exception as e:
        connection.rollback()
        raise e
    finally:
        cursor.close()
        connection.close()


def generate_menu_s3_urls(store_id: int, menu_id: int) -> Dict:
    """메뉴 S3 presigned URLs 생성"""
    menu_put_url = s3.generate_presigned_url('put_object',
        Params={'Bucket': bucket_name, 'Key': f'menu/menu_{store_id}_{menu_id}.png'},
        ExpiresIn=3600)
    
    menu_get_url = s3.generate_presigned_url('get_object',
        Params={'Bucket': bucket_name, 'Key': f'menu/menu_{store_id}_{menu_id}.png'},
        ExpiresIn=3600)
    
    return {
        'menu_put_url': menu_put_url,
        'menu_get_url': menu_get_url
    }


def update_menu(menu_id: int, menu_data: Menu) -> bool:
    """메뉴 정보 업데이트"""
    connection = get_db_connection()
    cursor = connection.cursor()
    
    try:
        query = "UPDATE menu SET "
        values = []
        
        if menu_data.name:
            query += "menu_name = %s, "
            values.append(menu_data.name)
        if menu_data.price:
            query += "price = %s, "
            values.append(menu_data.price)
        if menu_data.description:
            query += "description = %s, "
            values.append(menu_data.description)
        
        query = query[:-2]  # 마지막 쉼표와 공백 제거
        query += " WHERE id = %s"
        values.append(menu_id)
        
        cursor.execute(query, tuple(values))
        connection.commit()
        
        return cursor.rowcount > 0
    except Exception as e:
        connection.rollback()
        raise e
    finally:
        cursor.close()
        connection.close()


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
        connection.close()

