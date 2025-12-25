import traceback
from fastapi import APIRouter, HTTPException, status, Query
from typing import Optional
from datetime import datetime, timedelta
from pydantic import BaseModel
import pymysql
from db.session import get_db_connection
from core.s3_config import S3_CLIENT, BUCKET_NAME
from botocore.exceptions import ClientError
from models.store import StoreCreate
from models.menu import Menu

# CRUD 사용
from crud import store as store_crud
from crud import menu as menu_crud

router = APIRouter()

# S3 설정
s3 = S3_CLIENT
bucket_name = BUCKET_NAME

@router.get("/dashboard/statistics")
def get_dashboard_statistics():
    """대시보드 통계 데이터"""
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        # 현재 날짜 기준
        today = datetime.now().date()
        start_of_month = today.replace(day=1)
        start_of_day = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        
        # 상품권 발행 수 (일)
        cursor.execute('''
            SELECT COUNT(*) as count FROM gifticon
            WHERE DATE(created_at) = %s
        ''', (today,))
        gift_issued_today = cursor.fetchone()['count'] or 0
        
        # 상품권 발행 수 (월)
        cursor.execute('''
            SELECT COUNT(*) as count FROM gifticon
            WHERE DATE(created_at) >= %s
        ''', (start_of_month,))
        gift_issued_month = cursor.fetchone()['count'] or 0
        
        # 상품권 사용금액 (일)
        cursor.execute('''
            SELECT COALESCE(SUM(price), 0) as total FROM gifticon
            WHERE status = 'USED' AND DATE(used_at) = %s
        ''', (today,))
        gift_used_amount_today = cursor.fetchone()['total'] or 0
        
        # 상품권 사용금액 (월)
        cursor.execute('''
            SELECT COALESCE(SUM(price), 0) as total FROM gifticon
            WHERE status = 'USED' AND DATE(used_at) >= %s
        ''', (start_of_month,))
        gift_used_amount_month = cursor.fetchone()['total'] or 0
        
        # 상품권 사용 수
        cursor.execute('''
            SELECT COUNT(*) as count FROM gifticon
            WHERE status = 'USED'
        ''')
        gift_used_count = cursor.fetchone()['count'] or 0
        
        # 정산 금액 (월) - 실제 정산 테이블이 있다면 수정 필요
        cursor.execute('''
            SELECT COALESCE(SUM(price), 0) as total FROM gifticon
            WHERE status = 'USED' AND DATE(used_at) >= %s
        ''', (start_of_month,))
        settlement_amount_month = cursor.fetchone()['total'] or 0
        
        # 신규 매장 등록 수 (일)
        cursor.execute('''
            SELECT COUNT(*) as count FROM store
            WHERE DATE(created_at) = %s
        ''', (today,))
        new_stores_today = cursor.fetchone()['count'] or 0
        
        # 신규 매장 등록 수 (월)
        cursor.execute('''
            SELECT COUNT(*) as count FROM store
            WHERE DATE(created_at) >= %s
        ''', (start_of_month,))
        new_stores_month = cursor.fetchone()['count'] or 0
        
        # 승인 안된 매장 수
        cursor.execute('''
            SELECT COUNT(*) as count FROM store
            WHERE inspection_status != 'approved' OR inspection_status IS NULL
        ''')
        pending_stores = cursor.fetchone()['count'] or 0
        
        # 전체 매장 수
        cursor.execute('SELECT COUNT(*) as count FROM store')
        total_stores = cursor.fetchone()['count'] or 0
        
        # 신규 가입 유저 (일)
        cursor.execute('''
            SELECT COUNT(*) as count FROM user
            WHERE DATE(created_at) = %s
        ''', (today,))
        new_users_today = cursor.fetchone()['count'] or 0
        
        # 전체 유저
        cursor.execute('SELECT COUNT(*) as count FROM user')
        total_users = cursor.fetchone()['count'] or 0
        
        return {
            'gift_issued_today': gift_issued_today,
            'gift_issued_month': gift_issued_month,
            'gift_used_amount_today': float(gift_used_amount_today),
            'gift_used_amount_month': float(gift_used_amount_month),
            'gift_used_count': gift_used_count,
            'settlement_amount_month': float(settlement_amount_month),
            'new_stores_today': new_stores_today,
            'new_stores_month': new_stores_month,
            'pending_stores': pending_stores,
            'total_stores': total_stores,
            'new_users_today': new_users_today,
            'total_users': total_users
        }
        
    except Exception as e:
        print(f"Error in get_dashboard_statistics: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()

@router.get("/stores")
def get_stores(
    search: Optional[str] = Query(None, description="매장 이름, 사장님 이름으로 검색")
):
    """매장 리스트 (관리자용)"""
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        query = '''
            SELECT 
                s.id,
                s.owner_id,
                s.store_name as name,
                s.created_at,
                s.inspection_status as status,
                s.store_address as address,
                o.name as owner_name
            FROM store s
            LEFT JOIN owner o ON s.owner_id = o.id
        '''
        
        params = []
        if search:
            query += ' WHERE s.store_name LIKE %s OR o.name LIKE %s'
            search_pattern = f'%{search}%'
            params = [search_pattern, search_pattern]
        
        query += ' ORDER BY s.id ASC'
        
        cursor.execute(query, params)
        stores = cursor.fetchall()
        
        # 날짜 형식 변환
        result = []
        for store in stores:
            store['created_at'] = store['created_at'].isoformat() if store['created_at'] else None
            store['approved'] = store['status'] == 'approved'
            result.append(store)
        
        return {'stores': result}
        
    except Exception as e:
        print(f"Error in get_stores: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()

@router.get("/stores/{store_id}")
def get_store_detail(store_id: int):
    """매장 상세 정보"""
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        # 매장 기본 정보
        cursor.execute('''
            SELECT 
                s.*,
                o.name as owner_name,
                o.phone as owner_phone
            FROM store s
            LEFT JOIN owner o ON s.owner_id = o.id
            WHERE s.id = %s
        ''', (store_id,))
        store = cursor.fetchone()
        
        if not store:
            raise HTTPException(status_code=404, detail="Store not found")
        
        # 로고 URL
        logo_key = f'store_logo/store_logo_{store_id}.png'
        store['logo'] = None
        try:
            s3.head_object(Bucket=bucket_name, Key=logo_key)
            store['logo'] = s3.generate_presigned_url('get_object',
                Params={'Bucket': bucket_name, 'Key': logo_key}, ExpiresIn=3600)
        except ClientError:
            pass
        
        # 매장 사진 URLs
        store_photo_urls = []
        store_photo_cnt = store.get('store_photo_cnt', 0) or 0
        for i in range(1, store_photo_cnt + 1):
            try:
                image_key = f'store_image/store_image_{store_id}_{i}.png'
                s3.head_object(Bucket=bucket_name, Key=image_key)
                url = s3.generate_presigned_url('get_object',
                    Params={'Bucket': bucket_name, 'Key': image_key}, ExpiresIn=3600)
                store_photo_urls.append(url)
            except ClientError:
                pass
        store['images'] = store_photo_urls
        
        # 사업자 등록증, 통장사본 URL (필드가 있다면)
        # store['business_registration'] = None  # 실제 필드명에 맞게 수정
        # store['bank_account_copy'] = None  # 실제 필드명에 맞게 수정
        # store['account_number'] = None  # 실제 필드명에 맞게 수정
        
        # 날짜 형식 변환
        if store.get('created_at'):
            store['created_at'] = store['created_at'].isoformat()
        if store.get('updated_at'):
            store['updated_at'] = store['updated_at'].isoformat()
        
        return store
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in get_store_detail: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()

@router.get("/stores/{store_id}/menu")
def get_store_menus(store_id: int):
    """매장 메뉴 리스트"""
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        cursor.execute('''
            SELECT 
                m.id,
                m.menu_name as name,
                m.price as price,
                m.description as description,
                m.store_id
            FROM menu m
            WHERE m.store_id = %s
        ''', (store_id,))
        
        menus = cursor.fetchall()
        
        # 메뉴 이미지 URL 추가
        result = []
        for menu in menus:
            menu_id = menu['id']
            image_key = f'menu_image/menu_image_{menu_id}.png'
            menu['image'] = None
            try:
                s3.head_object(Bucket=bucket_name, Key=image_key)
                menu['image'] = s3.generate_presigned_url('get_object',
                    Params={'Bucket': bucket_name, 'Key': image_key}, ExpiresIn=3600)
            except ClientError:
                pass
            result.append(menu)
        
        return {'menus': result}
        
    except Exception as e:
        print(f"Error in get_store_menus: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()

@router.get("/stores/{store_id}/giftcards")
def get_store_giftcards(store_id: int):
    """매장의 깊티(기프티콘) 리스트"""
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        cursor.execute('''
            SELECT 
                g.id,
                g.created_at,
                g.used_at,
                g.status,
                m.price as amount,
                g.user_id,
                m.menu_name as menu_name
            FROM gifticon g
            LEFT JOIN menu m ON g.menu_id = m.id
            WHERE g.store_id = %s
            ORDER BY g.created_at DESC
        ''', (store_id,))
        
        giftcards = cursor.fetchall()
        
        result = []
        for card in giftcards:
            card['created_at'] = card['created_at'].isoformat() if card['created_at'] else None
            card['used_at'] = card['used_at'].isoformat() if card['used_at'] else None
            result.append(card)
        
        return {'giftcards': result}
        
    except Exception as e:
        print(f"Error in get_store_giftcards: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()

@router.get("/users")
def get_users(
    search: Optional[str] = Query(None, description="이름, 아이디, 전화번호, ID로 검색")
):
    """유저 리스트 (관리자용)"""
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        query = '''
            SELECT 
                id,
                name,
                email,
                phone,
                created_at,
                last_login
            FROM user
        '''
        
        params = []
        if search:
            query += ' WHERE name LIKE %s OR email LIKE %s OR phone LIKE %s OR id = %s'
            search_pattern = f'%{search}%'
            try:
                search_id = int(search)
                params = [search_pattern, search_pattern, search_pattern, search_id]
            except ValueError:
                params = [search_pattern, search_pattern, search_pattern, -1]
        
        query += ' ORDER BY id ASC'
        
        cursor.execute(query, params)
        users = cursor.fetchall()
        
        # 날짜 형식 변환
        result = []
        for user in users:
            user['created_at'] = user['created_at'].isoformat() if user.get('created_at') else None
            user['last_login'] = user['last_login'].isoformat() if user.get('last_login') else None
            result.append(user)
        
        return {'users': result}
        
    except Exception as e:
        print(f"Error in get_users: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()

@router.get("/users/{user_id}")
def get_user_detail(user_id: int):
    """유저 상세 정보"""
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        cursor.execute('''
            SELECT 
                id,
                name,
                email,
                phone as phone,
                created_at,
                last_login
            FROM user
            WHERE id = %s
        ''', (user_id,))
        
        user = cursor.fetchone()
        
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # 날짜 형식 변환
        if user.get('created_at'):
            user['created_at'] = user['created_at'].isoformat()
        if user.get('last_login'):
            user['last_login'] = user['last_login'].isoformat()
        
        # 약관동의 정보 (필드가 있다면)
        # user['terms_agreed'] = False
        # user['terms_agreed_date'] = None
        # user['privacy_agreed'] = False
        # user['privacy_agreed_date'] = None
        
        return user
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in get_user_detail: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()

@router.get("/users/{user_id}/orders")
def get_user_orders(user_id: int):
    """유저 주문 내역"""
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        cursor.execute('''
            SELECT 
                o.id,
                o.created_at,
                o.amount,
                o.payment,
                o.payment_key,
                o.status
            FROM `orders` o
            WHERE o.user_id = %s
            ORDER BY o.created_at DESC
        ''', (user_id,))
        
        orders = cursor.fetchall()
        
        result = []
        for order in orders:
            order['created_at'] = order['created_at'].isoformat() if order.get('created_at') else None
            result.append(order)
        
        return {'orders': result}
        
    except Exception as e:
        print(f"Error in get_user_orders: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()

@router.get("/users/{user_id}/giftcards")
def get_user_giftcards(user_id: int):
    """유저 기프티콘 리스트"""
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        cursor.execute('''
            SELECT 
                g.id,
                m.price,
                g.gift_code,
                g.validity,
                g.created_at as received_at,
                g.used_at,
                g.status,
                m.menu_name
            FROM gifticon g
            LEFT JOIN menu m ON g.menu_id = m.id
            WHERE g.user_id = %s
            ORDER BY g.created_at DESC
        ''', (user_id,))
        
        giftcards = cursor.fetchall()
        
        result = []
        for card in giftcards:
            card['received_at'] = card['received_at'].isoformat() if card.get('received_at') else None
            card['used_at'] = card['used_at'].isoformat() if card.get('used_at') else None
            card['validity'] = card['validity'].isoformat() if card.get('validity') else None
            result.append(card)
        
        return {'giftcards': result}
        
    except Exception as e:
        print(f"Error in get_user_giftcards: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()

@router.get("/orders")
def get_orders(
    search: Optional[str] = Query(None, description="주문번호, user id로 검색")
):
    """주문 리스트 (관리자용)"""
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        query = '''
            SELECT 
                o.id,
                o.order_no,
                o.user_id,
                o.status,
                s.store_name
            FROM `orders` o
            LEFT JOIN store s ON o.store_id = s.id
        '''
        
        params = []
        if search:
            query += ' WHERE o.order_number LIKE %s OR o.user_id = %s'
            search_pattern = f'%{search}%'
            try:
                search_id = int(search)
                params = [search_pattern, search_id]
            except ValueError:
                params = [search_pattern, -1]
        
        query += ' ORDER BY o.created_at DESC'
        
        cursor.execute(query, params)
        orders = cursor.fetchall()
        
        return {'orders': orders}
        
    except Exception as e:
        print(f"Error in get_orders: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()

@router.get("/orders/{order_id}")
def get_order_detail(order_id: int):
    """주문 상세 정보"""
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        cursor.execute('''
            SELECT 
                o.*,
                s.store_name
            FROM `orders` o
            LEFT JOIN store s ON o.store_id = s.id
            WHERE o.id = %s
        ''', (order_id,))
        
        order = cursor.fetchone()
        
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        
        # 날짜 형식 변환
        if order.get('created_at'):
            order['created_at'] = order['created_at'].isoformat()
        
        # 받는 사람 정보 (필드가 있다면)
        # order['recipient_name'] = order.get('recipient_name')
        # order['recipient_phone'] = order.get('recipient_phone')
        order['amount'] = order.get('amount', 0)
        
        return order
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in get_order_detail: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()

@router.get("/orders/{order_id}/giftcards")
def get_order_giftcards(order_id: int):
    """주문의 기프티콘 리스트"""
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        cursor.execute('''
            SELECT 
                g.id,
                m.price,
                g.gift_code,
                g.validity,
                g.created_at as received_at,
                g.used_at,
                g.status,
                m.menu_name,
                s.store_name,
                s.id as store_id
            FROM gifticon g
            LEFT JOIN menu m ON g.menu_id = m.id
            LEFT JOIN store s ON g.store_id = s.id
            WHERE g.order_id = %s
            ORDER BY g.created_at DESC
        ''', (order_id,))
        
        giftcards = cursor.fetchall()
        
        result = []
        for card in giftcards:
            card['received_at'] = card['received_at'].isoformat() if card.get('received_at') else None
            card['used_at'] = card['used_at'].isoformat() if card.get('used_at') else None
            card['validity'] = card['validity'].isoformat() if card.get('validity') else None
            result.append(card)
        
        return {'giftcards': result}
        
    except Exception as e:
        print(f"Error in get_order_giftcards: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()

@router.get("/menus")
def get_all_menus():
    """전체 메뉴 리스트"""
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        cursor.execute('''
            SELECT 
                m.id,
                m.menu_name as name,
                m.price as price,
                m.store_id,
                s.store_name
            FROM menu m
            LEFT JOIN store s ON m.store_id = s.id
            ORDER BY m.id DESC
        ''')
        
        menus = cursor.fetchall()
        
        # 메뉴 이미지 URL 추가
        result = []
        for menu in menus:
            menu_id = menu['id']
            image_key = f'menu_image/menu_image_{menu_id}.png'
            menu['image'] = None
            try:
                s3.head_object(Bucket=bucket_name, Key=image_key)
                menu['image'] = s3.generate_presigned_url('get_object',
                    Params={'Bucket': bucket_name, 'Key': image_key}, ExpiresIn=3600)
            except ClientError:
                pass
            result.append(menu)
        
        return {'menus': result}
        
    except Exception as e:
        print(f"Error in get_all_menus: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()

@router.get("/notices")
def get_notices():
    """공지사항 리스트"""
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        # 공지사항 테이블이 있다면 (예시)
        # cursor.execute('''
        #     SELECT 
        #         id,
        #         title,
        #         content,
        #         target,
        #         created_at
        #     FROM notice
        #     ORDER BY created_at DESC
        # ''')
        # notices = cursor.fetchall()
        
        # 현재는 빈 리스트 반환 (공지사항 테이블이 없을 수 있음)
        return {'notices': []}
        
    except Exception as e:
        print(f"Error in get_notices: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()

@router.post("/test/store")
def create_test_store(store: StoreCreate):
    """테스트 매장 추가 (CRUD 사용)"""
    try:
        store_id = store_crud.create_store(store)
        s3_urls = store_crud.generate_store_s3_urls(store_id, store.store_photo_cnt)
        
        return {
            'store_id': store_id,
            'store_logo_url': s3_urls['store_logo_url'],
            'store_photo_urls': s3_urls['store_photo_urls'],
            'bankBook_put_url': s3_urls['bankBook_put_url'],
            'business_put_url': s3_urls['business_put_url']
        }
    except Exception as e:
        print(f"Error in create_test_store: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"failed register store: {str(e)}"
        )

@router.post("/test/menu/{store_id}")
def create_test_menu(store_id: int, menu: Menu):
    """테스트 메뉴 추가 (CRUD 사용)"""
    try:
        if menu.store_id != store_id:
            raise HTTPException(status_code=400, detail="store_id in path and body must match")
        
        menu_id = menu_crud.create_menu(store_id, menu)
        s3_urls = menu_crud.generate_menu_s3_urls(store_id, menu_id)
        
        return {
            'menu_id': menu_id,
            'menu_put_url': s3_urls['menu_put_url'],
            'menu_get_url': s3_urls['menu_get_url']
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in create_test_menu: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"failed add menu: {str(e)}"
        )

