"""Admin CRUD operations"""
import pymysql
from datetime import datetime
from typing import Optional, Dict, List
from db.session import get_db_connection, close_db_connection
from core.s3_config import S3_CLIENT, BUCKET_NAME, get_s3_public_url
from botocore.exceptions import ClientError
from crud import store as store_crud
from crud import menu as menu_crud

s3 = S3_CLIENT
bucket_name = BUCKET_NAME


def get_dashboard_statistics(connection) -> Dict:
    """대시보드 통계 데이터"""
    cursor = connection.cursor(pymysql.cursors.DictCursor)

    try:
        today = datetime.now().date()
        start_of_month = today.replace(day=1)

        # gifticon 관련 집계 1회 쿼리
        cursor.execute('''
            SELECT
                SUM(created_at >= %s AND created_at < DATE_ADD(%s, INTERVAL 1 DAY)) AS gift_issued_today,
                SUM(created_at >= %s) AS gift_issued_month,
                SUM(status = 'USED') AS gift_used_count
            FROM gifticon
        ''', (today, today, start_of_month))
        gift_row = cursor.fetchone()
        gift_issued_today = int(gift_row['gift_issued_today'] or 0)
        gift_issued_month = int(gift_row['gift_issued_month'] or 0)
        gift_used_count = int(gift_row['gift_used_count'] or 0)

        # gifticon 사용금액 집계 (menu JOIN 필요)
        cursor.execute('''
            SELECT
                COALESCE(SUM(CASE WHEN g.used_at >= %s AND g.used_at < DATE_ADD(%s, INTERVAL 1 DAY) THEN m.price ELSE 0 END), 0) AS gift_used_amount_today,
                COALESCE(SUM(CASE WHEN g.used_at >= %s THEN m.price ELSE 0 END), 0) AS gift_used_amount_month
            FROM gifticon g
            LEFT JOIN menu m ON g.menu_id = m.id
            WHERE g.status = 'USED'
        ''', (today, today, start_of_month))
        used_row = cursor.fetchone()
        gift_used_amount_today = float(used_row['gift_used_amount_today'] or 0)
        gift_used_amount_month = float(used_row['gift_used_amount_month'] or 0)
        settlement_amount_month = gift_used_amount_month

        # store 집계 1회 쿼리
        cursor.execute('''
            SELECT
                SUM(created_at >= %s AND created_at < DATE_ADD(%s, INTERVAL 1 DAY)) AS new_stores_today,
                SUM(created_at >= %s) AS new_stores_month,
                SUM(inspection_status != 'approved' OR inspection_status IS NULL) AS pending_stores,
                COUNT(*) AS total_stores
            FROM store
        ''', (today, today, start_of_month))
        store_row = cursor.fetchone()
        new_stores_today = int(store_row['new_stores_today'] or 0)
        new_stores_month = int(store_row['new_stores_month'] or 0)
        pending_stores = int(store_row['pending_stores'] or 0)
        total_stores = int(store_row['total_stores'] or 0)

        # user 집계 1회 쿼리
        cursor.execute('''
            SELECT
                SUM(created_at >= %s AND created_at < DATE_ADD(%s, INTERVAL 1 DAY)) AS new_users_today,
                COUNT(*) AS total_users
            FROM user
        ''', (today, today))
        user_row = cursor.fetchone()
        new_users_today = int(user_row['new_users_today'] or 0)
        total_users = int(user_row['total_users'] or 0)

        return {
            'gift_issued_today': gift_issued_today,
            'gift_issued_month': gift_issued_month,
            'gift_used_amount_today': gift_used_amount_today,
            'gift_used_amount_month': gift_used_amount_month,
            'gift_used_count': gift_used_count,
            'settlement_amount_month': settlement_amount_month,
            'new_stores_today': new_stores_today,
            'new_stores_month': new_stores_month,
            'pending_stores': pending_stores,
            'total_stores': total_stores,
            'new_users_today': new_users_today,
            'total_users': total_users
        }
    finally:
        cursor.close()


def get_stores(connection, search: Optional[str] = None, page: int = 1, limit: int = 20,
               inspection_status: Optional[str] = None, contract_completed: Optional[str] = None) -> Dict:
    """매장 리스트 (관리자용, 페이지네이션)"""
    cursor = connection.cursor(pymysql.cursors.DictCursor)

    def _build_conditions(search, inspection_status, contract_completed):
        conditions = []
        params = []
        if search:
            conditions.append('(s.store_name LIKE %s OR o.name LIKE %s)')
            pattern = f'%{search}%'
            params += [pattern, pattern]
        if inspection_status:
            conditions.append('s.inspection_status = %s')
            params.append(inspection_status)
        if contract_completed:
            conditions.append('s.contract_completed = %s')
            params.append(contract_completed)
        where = (' WHERE ' + ' AND '.join(conditions)) if conditions else ''
        return where, params

    try:
        where, base_params = _build_conditions(search, inspection_status, contract_completed)

        count_query = f'''
            SELECT COUNT(*) as total
            FROM store s
            LEFT JOIN owner o ON s.owner_id = o.id
            {where}
        '''
        cursor.execute(count_query, base_params)
        total_count = cursor.fetchone()['total']

        offset = (page - 1) * limit
        total_pages = (total_count + limit - 1) // limit if total_count > 0 else 1

        query = f'''
            SELECT
                s.id,
                s.owner_id,
                s.store_name as name,
                s.created_at,
                s.inspection_status as status,
                s.contract_completed,
                s.store_address as address,
                o.name as owner_name,
                o.email as owner_email,
                o.phone as owner_phone,
                s.business_number as owner_business_number
            FROM store s
            LEFT JOIN owner o ON s.owner_id = o.id
            {where}
            ORDER BY s.created_at DESC
            LIMIT %s OFFSET %s
        '''
        params = base_params + [limit, offset]
        cursor.execute(query, params)
        stores = cursor.fetchall()

        result = []
        for store in stores:
            store['created_at'] = store['created_at'].isoformat() if store['created_at'] else None
            store['approved'] = store['status'].upper() == 'APPROVED' if store['status'] else False
            result.append(store)

        return {
            'items': result,
            'total': total_count,
            'page': page,
            'limit': limit,
            'total_pages': total_pages
        }
    finally:
        cursor.close()


def get_store_detail(connection, store_id: int) -> Dict:
    """매장 상세 정보"""
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        cursor.execute('''
            SELECT
                s.*,
                o.name as owner_name,
                o.phone as owner_phone,
                a.name as account_holder,
                a.bank as account_bank,
                a.account as account_number
            FROM store s
            LEFT JOIN owner o ON s.owner_id = o.id
            LEFT JOIN account a ON s.id = a.store_id
            WHERE s.id = %s
        ''', (store_id,))
        store = cursor.fetchone()

        if not store:
            return None

        # 로고 URL
        logo_key = f'store_logo/store_logo_{store_id}.png'
        store['logo'] = None
        try:
            s3.head_object(Bucket=bucket_name, Key=logo_key)
            store['logo'] = s3.generate_presigned_url('get_object',
                Params={'Bucket': bucket_name, 'Key': logo_key}, ExpiresIn=3600)
        except ClientError:
            pass

        # 통장사본 URL
        store['bankbook_url'] = None
        bk = store.get('bankbook_key')
        if bk:
            try:
                s3.head_object(Bucket=bucket_name, Key=bk)
                store['bankbook_url'] = s3.generate_presigned_url('get_object',
                    Params={'Bucket': bucket_name, 'Key': bk}, ExpiresIn=3600)
            except ClientError:
                pass

        # 사업자등록증 URL
        store['business_registration_url'] = None
        brk = store.get('business_registration_key')
        if brk:
            try:
                s3.head_object(Bucket=bucket_name, Key=brk)
                store['business_registration_url'] = s3.generate_presigned_url('get_object',
                    Params={'Bucket': bucket_name, 'Key': brk}, ExpiresIn=3600)
            except ClientError:
                pass

        cursor.execute(
            "SELECT image_key FROM store_images WHERE store_id = %s ORDER BY `order` ASC",
            (store_id,)
        )
        store['images'] = [
            s3.generate_presigned_url('get_object',
                Params={'Bucket': bucket_name, 'Key': r['image_key']}, ExpiresIn=3600)
            for r in cursor.fetchall()
        ]

        # 날짜 형식 변환
        if store.get('created_at'):
            store['created_at'] = store['created_at'].isoformat()
        if store.get('updated_at'):
            store['updated_at'] = store['updated_at'].isoformat()

        return store
    finally:
        cursor.close()


def get_store_menus(connection, store_id: int, page: int = 1, limit: int = 10) -> Dict:
    """매장 메뉴 리스트 (페이지네이션)"""
    cursor = connection.cursor(pymysql.cursors.DictCursor)

    try:
        cursor.execute('SELECT COUNT(*) as total FROM menu WHERE store_id = %s', (store_id,))
        total_count = cursor.fetchone()['total']

        offset = (page - 1) * limit
        total_pages = (total_count + limit - 1) // limit if total_count > 0 else 1

        cursor.execute('''
            SELECT
                m.id,
                m.menu_name as name,
                m.price as price,
                m.description as description,
                m.store_id,
                m.image_key
            FROM menu m
            WHERE m.store_id = %s
            ORDER BY m.id ASC
            LIMIT %s OFFSET %s
        ''', (store_id, limit, offset))

        menus = cursor.fetchall()

        result = []
        for menu in menus:
            menu['image'] = None
            if menu.get('image_key'):
                menu['image'] = get_s3_public_url(bucket_name, menu['image_key'])
            del menu['image_key']
            result.append(menu)

        return {
            'items': result,
            'total': total_count,
            'page': page,
            'limit': limit,
            'total_pages': total_pages,
        }
    finally:
        cursor.close()


def get_store_giftcards(connection, store_id: int, page: int = 1, limit: int = 10) -> Dict:
    """매장의 깊티(기프티콘) 리스트 (페이지네이션)"""
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        # 전체 개수 조회
        cursor.execute('''
            SELECT COUNT(*) as total
            FROM gifticon g
            WHERE g.store_id = %s
        ''', (store_id,))
        total_count = cursor.fetchone()['total']
        
        # 페이지네이션 계산
        offset = (page - 1) * limit
        total_pages = (total_count + limit - 1) // limit if total_count > 0 else 1
        
        # 데이터 조회
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
            LIMIT %s OFFSET %s
        ''', (store_id, limit, offset))
        
        giftcards = cursor.fetchall()
        
        result = []
        for card in giftcards:
            card['created_at'] = card['created_at'].isoformat() if card['created_at'] else None
            card['used_at'] = card['used_at'].isoformat() if card['used_at'] else None
            result.append(card)
        
        return {
            'items': result,
            'total': total_count,
            'page': page,
            'limit': limit,
            'total_pages': total_pages
        }
    finally:
        cursor.close()


def get_users(connection, search: Optional[str] = None, page: int = 1, limit: int = 20) -> Dict:
    """유저 리스트 (관리자용, 페이지네이션)"""
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        # 전체 개수 조회
        count_query = 'SELECT COUNT(*) as total FROM user'
        count_params = []
        
        if search:
            count_query += ' WHERE name LIKE %s OR email LIKE %s OR phone LIKE %s OR id = %s'
            search_pattern = f'%{search}%'
            try:
                search_id = int(search)
                count_params = [search_pattern, search_pattern, search_pattern, search_id]
            except ValueError:
                count_params = [search_pattern, search_pattern, search_pattern, -1]
        
        cursor.execute(count_query, count_params)
        total_count = cursor.fetchone()['total']
        
        # 페이지네이션 계산
        offset = (page - 1) * limit
        total_pages = (total_count + limit - 1) // limit if total_count > 0 else 1
        
        # 데이터 조회
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
        query += ' LIMIT %s OFFSET %s'
        params.extend([limit, offset])
        
        cursor.execute(query, params)
        users = cursor.fetchall()
        
        result = []
        for user in users:
            user['created_at'] = user['created_at'].isoformat() if user.get('created_at') else None
            user['last_login'] = user['last_login'].isoformat() if user.get('last_login') else None
            result.append(user)
        
        return {
            'items': result,
            'total': total_count,
            'page': page,
            'limit': limit,
            'total_pages': total_pages
        }
    finally:
        cursor.close()


def get_owners(connection, search: Optional[str] = None, page: int = 1, limit: int = 20) -> Dict:
    """사장님 리스트 (관리자용, 페이지네이션)"""
    cursor = connection.cursor(pymysql.cursors.DictCursor)

    try:
        count_query = 'SELECT COUNT(*) as total FROM owner'
        count_params = []

        if search:
            count_query += ' WHERE (name LIKE %s OR login_id LIKE %s OR email LIKE %s OR phone LIKE %s OR id = %s)'
            search_pattern = f'%{search}%'
            try:
                search_id = int(search)
                count_params = [search_pattern, search_pattern, search_pattern, search_pattern, search_id]
            except ValueError:
                count_params = [search_pattern, search_pattern, search_pattern, search_pattern, -1]

        cursor.execute(count_query, count_params)
        total_count = cursor.fetchone()['total']

        offset = (page - 1) * limit
        total_pages = (total_count + limit - 1) // limit if total_count > 0 else 1

        query = 'SELECT id, name, login_id, email, phone, created_at FROM owner'
        params = []
        if search:
            query += ' WHERE (name LIKE %s OR login_id LIKE %s OR email LIKE %s OR phone LIKE %s OR id = %s)'
            search_pattern = f'%{search}%'
            try:
                search_id = int(search)
                params = [search_pattern, search_pattern, search_pattern, search_pattern, search_id]
            except ValueError:
                params = [search_pattern, search_pattern, search_pattern, search_pattern, -1]

        query += ' ORDER BY id DESC LIMIT %s OFFSET %s'
        params.extend([limit, offset])

        cursor.execute(query, params)
        owners = cursor.fetchall()

        result = []
        for owner in owners:
            owner['created_at'] = owner['created_at'].isoformat() if owner.get('created_at') else None
            result.append(owner)

        return {
            'items': result,
            'total': total_count,
            'page': page,
            'limit': limit,
            'total_pages': total_pages,
        }
    finally:
        cursor.close()


def get_owner_detail(connection, owner_id: int) -> Dict:
    """사장님 상세 정보 (기본정보 + 계좌 + 통장사본 + 매장 목록)"""
    cursor = connection.cursor(pymysql.cursors.DictCursor)

    try:
        cursor.execute(
            'SELECT id, name, login_id, email, phone, created_at FROM owner WHERE id = %s',
            (owner_id,)
        )
        owner = cursor.fetchone()
        if not owner:
            return None

        owner['created_at'] = owner['created_at'].isoformat() if owner.get('created_at') else None

        # 매장 목록 + 각 매장의 계좌 및 통장사본
        cursor.execute(
            'SELECT id, store_name, store_address FROM store WHERE owner_id = %s ORDER BY created_at DESC',
            (owner_id,)
        )
        stores_raw = cursor.fetchall()

        stores = []
        for store in stores_raw:
            store_id = store['id']

            cursor.execute(
                'SELECT name, code, bank, account FROM account WHERE store_id = %s LIMIT 1',
                (store_id,)
            )
            account = cursor.fetchone()

            bankbook_url = None
            try:
                s3.head_object(Bucket=bucket_name, Key=f'bankbook/bankbook_{store_id}.png')
                bankbook_url = s3.generate_presigned_url(
                    'get_object',
                    Params={'Bucket': bucket_name, 'Key': f'bankbook/bankbook_{store_id}.png'},
                    ExpiresIn=3600,
                )
            except ClientError:
                pass

            stores.append({
                'store_id': store_id,
                'store_name': store['store_name'],
                'store_address': store['store_address'],
                'account': account,
                'bankbook_url': bankbook_url,
            })

        owner['stores'] = stores
        return owner
    finally:
        cursor.close()


def get_user_detail(connection, user_id: int) -> Dict:
    """유저 상세 정보"""
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        cursor.execute('''
            SELECT 
                id,
                name,
                email,
                phone,
                created_at,
                last_login
            FROM user
            WHERE id = %s
        ''', (user_id,))
        
        user = cursor.fetchone()
        
        if not user:
            return None
        
        if user.get('created_at'):
            user['created_at'] = user['created_at'].isoformat()
        if user.get('last_login'):
            user['last_login'] = user['last_login'].isoformat()
        
        return user
    finally:
        cursor.close()


def get_user_orders(connection, user_id: int) -> List[Dict]:
    """유저 주문 내역"""
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
        
        return result
    finally:
        cursor.close()


def get_user_giftcards(connection, user_id: int) -> List[Dict]:
    """유저 기프티콘 리스트"""
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
            # validity 처리: datetime 객체면 isoformat, 문자열이면 그대로, None이면 None
            if card.get('validity'):
                if hasattr(card['validity'], 'isoformat'):
                    card['validity'] = card['validity'].isoformat()
                # 이미 문자열이면 그대로 유지
            else:
                card['validity'] = None
            result.append(card)
        
        return result
    finally:
        cursor.close()


def get_orders(connection, search: Optional[str] = None, page: int = 1, limit: int = 20) -> Dict:
    """주문 리스트 (관리자용, 페이지네이션)"""
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        # 전체 개수 조회
        count_query = '''
            SELECT COUNT(*) as total
            FROM `orders` o
            LEFT JOIN store s ON o.store_id = s.id
        '''
        count_params = []
        if search:
            count_query += ' WHERE o.order_no LIKE %s OR o.user_id = %s'
            search_pattern = f'%{search}%'
            try:
                search_id = int(search)
                count_params = [search_pattern, search_id]
            except ValueError:
                count_params = [search_pattern, -1]
        
        cursor.execute(count_query, count_params)
        total_count = cursor.fetchone()['total']
        
        # 페이지네이션 계산
        offset = (page - 1) * limit
        total_pages = (total_count + limit - 1) // limit if total_count > 0 else 1
        
        # 데이터 조회
        query = '''
            SELECT 
                o.id,
                o.user_id,
                o.status,
                o.order_no as order_number,
                s.store_name
            FROM `orders` o
            LEFT JOIN store s ON o.store_id = s.id
        '''
        
        params = []
        if search:
            query += ' WHERE o.order_no LIKE %s OR o.user_id = %s'
            search_pattern = f'%{search}%'
            try:
                search_id = int(search)
                params = [search_pattern, search_id]
            except ValueError:
                params = [search_pattern, -1]
        
        query += ' ORDER BY o.created_at DESC'
        query += ' LIMIT %s OFFSET %s'
        params.extend([limit, offset])
        
        cursor.execute(query, params)
        orders = cursor.fetchall()
        
        result = []
        for order in orders:
            # order_no 컬럼을 order_number로 매핑 (SQL에서 이미 alias로 처리됨)
            # DictCursor를 사용하므로 'order_number' 키로 이미 존재함
            result.append(order)
        
        return {
            'items': result,
            'total': total_count,
            'page': page,
            'limit': limit,
            'total_pages': total_pages
        }
    finally:
        cursor.close()


def get_order_detail(connection, order_id: int) -> Dict:
    """주문 상세 정보"""
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
            return None
        
        if order.get('created_at'):
            order['created_at'] = order['created_at'].isoformat()
        
        order['amount'] = order.get('amount', 0)
        
        return order
    finally:
        cursor.close()


def get_order_giftcards(connection, order_id: int) -> List[Dict]:
    """주문의 기프티콘 리스트"""
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
            # validity 처리: datetime 객체면 isoformat, 문자열이면 그대로, None이면 None
            if card.get('validity'):
                if hasattr(card['validity'], 'isoformat'):
                    card['validity'] = card['validity'].isoformat()
                # 이미 문자열이면 그대로 유지
            else:
                card['validity'] = None
            result.append(card)
        
        return result
    finally:
        cursor.close()


def get_all_menus(connection, page: int = 1, limit: int = 20) -> Dict:
    """전체 메뉴 리스트 (페이지네이션)"""
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        # 전체 개수 조회
        cursor.execute('SELECT COUNT(*) as total FROM menu')
        total_count = cursor.fetchone()['total']
        
        # 페이지네이션 계산
        offset = (page - 1) * limit
        total_pages = (total_count + limit - 1) // limit if total_count > 0 else 1
        
        # 데이터 조회
        cursor.execute('''
            SELECT
                m.id,
                m.menu_name as name,
                m.price as price,
                m.store_id,
                m.image_key,
                s.store_name
            FROM menu m
            LEFT JOIN store s ON m.store_id = s.id
            ORDER BY m.id DESC
            LIMIT %s OFFSET %s
        ''', (limit, offset))
        
        menus = cursor.fetchall()
        
        result = []
        for menu in menus:
            menu['image'] = None
            if menu.get('image_key'):
                menu['image'] = get_s3_public_url(bucket_name, menu['image_key'])
            del menu['image_key']
            result.append(menu)
        
        return {
            'items': result,
            'total': total_count,
            'page': page,
            'limit': limit,
            'total_pages': total_pages
        }
    finally:
        cursor.close()


def get_notices(connection, target: Optional[str] = None, page: int = 1, limit: int = 20) -> Dict:
    """공지사항 리스트 (페이지네이션)
    
    Args:
        connection: DB 연결
        target: 'user' 또는 'owner', None이면 둘 다
        page: 페이지 번호
        limit: 페이지당 항목 수
    """
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        result = []
        total_count = 0
        
        if target is None or target == 'user':
            # 유저 공지사항 조회
            cursor.execute('SELECT COUNT(*) as total FROM notice_user')
            user_total = cursor.fetchone()['total']
            total_count += user_total
            
            if user_total > 0:
                offset = (page - 1) * limit
                cursor.execute('''
                    SELECT id, title, content, created_at, updated_at
                    FROM notice_user
                    ORDER BY created_at DESC
                    LIMIT %s OFFSET %s
                ''', (limit, offset))
                
                user_notices = cursor.fetchall()
                for notice in user_notices:
                    notice['target'] = 'user'
                    notice['created_at'] = notice['created_at'].isoformat() if notice.get('created_at') else None
                    notice['updated_at'] = notice['updated_at'].isoformat() if notice.get('updated_at') else None
                result.extend(user_notices)
        
        if target is None or target == 'owner':
            # 사장님 공지사항 조회
            cursor.execute('SELECT COUNT(*) as total FROM notice_owner')
            owner_total = cursor.fetchone()['total']
            total_count += owner_total
            
            if owner_total > 0:
                offset = (page - 1) * limit
                cursor.execute('''
                    SELECT id, title, content, created_at, updated_at
                    FROM notice_owner
                    ORDER BY created_at DESC
                    LIMIT %s OFFSET %s
                ''', (limit, offset))
                
                owner_notices = cursor.fetchall()
                for notice in owner_notices:
                    notice['target'] = 'owner'
                    notice['created_at'] = notice['created_at'].isoformat() if notice.get('created_at') else None
                    notice['updated_at'] = notice['updated_at'].isoformat() if notice.get('updated_at') else None
                result.extend(owner_notices)
        
        # 날짜순 정렬 (최신순) - ISO 형식 문자열 비교
        result.sort(key=lambda x: x.get('created_at', '') or '', reverse=True)
        
        # target=None일 때는 전체를 가져오고, 각 target별로는 페이지네이션 적용
        # 하지만 템플릿에서 별도로 보여주므로, 일단 전체를 반환
        # 페이지네이션은 전체 개수 기준
        total_pages = (total_count + limit - 1) // limit if total_count > 0 else 1
        
        return {
            'items': result,
            'total': total_count,
            'page': page,
            'limit': limit,
            'total_pages': total_pages
        }
    finally:
        cursor.close()


def create_notice(connection, target: str, title: str, content: str) -> int:
    """공지사항 생성
    
    Args:
        connection: DB 연결
        target: 'user' 또는 'owner'
        title: 공지사항 제목
        content: 공지사항 내용
    
    Returns:
        생성된 공지사항 ID
    """
    cursor = connection.cursor()
    
    try:
        if target == 'user':
            query = 'INSERT INTO notice_user (title, content) VALUES (%s, %s)'
        elif target == 'owner':
            query = 'INSERT INTO notice_owner (title, content) VALUES (%s, %s)'
        else:
            raise ValueError(f"Invalid target: {target}. Must be 'user' or 'owner'")
        
        cursor.execute(query, (title, content))
        connection.commit()
        return cursor.lastrowid
    except Exception as e:
        connection.rollback()
        raise e
    finally:
        cursor.close()


def get_notice_detail(connection, target: str, notice_id: int) -> Optional[Dict]:
    """공지사항 상세 조회
    
    Args:
        connection: DB 연결
        target: 'user' 또는 'owner'
        notice_id: 공지사항 ID
    
    Returns:
        공지사항 정보 dict, 없으면 None
    """
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        if target == 'user':
            query = 'SELECT id, title, content, created_at, updated_at FROM notice_user WHERE id = %s'
        elif target == 'owner':
            query = 'SELECT id, title, content, created_at, updated_at FROM notice_owner WHERE id = %s'
        else:
            raise ValueError(f"Invalid target: {target}. Must be 'user' or 'owner'")
        
        cursor.execute(query, (notice_id,))
        notice = cursor.fetchone()
        
        if notice:
            notice['target'] = target
            notice['created_at'] = notice['created_at'].isoformat() if notice.get('created_at') else None
            notice['updated_at'] = notice['updated_at'].isoformat() if notice.get('updated_at') else None
        
        return notice
    finally:
        cursor.close()


def update_notice(connection, target: str, notice_id: int, title: Optional[str] = None, content: Optional[str] = None) -> bool:
    """공지사항 수정
    
    Args:
        connection: DB 연결
        target: 'user' 또는 'owner'
        notice_id: 공지사항 ID
        title: 공지사항 제목 (선택)
        content: 공지사항 내용 (선택)
    
    Returns:
        수정 성공 여부
    """
    cursor = connection.cursor()
    
    try:
        updates = []
        params = []
        
        if title is not None:
            updates.append('title = %s')
            params.append(title)
        
        if content is not None:
            updates.append('content = %s')
            params.append(content)
        
        if not updates:
            return False
        
        if target == 'user':
            query = f'UPDATE notice_user SET {", ".join(updates)} WHERE id = %s'
        elif target == 'owner':
            query = f'UPDATE notice_owner SET {", ".join(updates)} WHERE id = %s'
        else:
            raise ValueError(f"Invalid target: {target}. Must be 'user' or 'owner'")
        
        params.append(notice_id)
        cursor.execute(query, params)
        connection.commit()
        return cursor.rowcount > 0
    except Exception as e:
        connection.rollback()
        raise e
    finally:
        cursor.close()


def delete_notice(connection, target: str, notice_id: int) -> bool:
    """공지사항 삭제
    
    Args:
        connection: DB 연결
        target: 'user' 또는 'owner'
        notice_id: 공지사항 ID
    
    Returns:
        삭제 성공 여부
    """
    cursor = connection.cursor()
    
    try:
        if target == 'user':
            query = 'DELETE FROM notice_user WHERE id = %s'
        elif target == 'owner':
            query = 'DELETE FROM notice_owner WHERE id = %s'
        else:
            raise ValueError(f"Invalid target: {target}. Must be 'user' or 'owner'")
        
        cursor.execute(query, (notice_id,))
        connection.commit()
        return cursor.rowcount > 0
    except Exception as e:
        connection.rollback()
        raise e
    finally:
        cursor.close()



# ── Popup CRUD ────────────────────────────────────────────────────────────────

def get_popups(connection, target_type: Optional[str] = None, page: int = 1, limit: int = 20) -> dict:
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    try:
        offset = (page - 1) * limit
        if target_type:
            count_q = "SELECT COUNT(*) as total FROM popup WHERE target_type = %s"
            cursor.execute(count_q, (target_type,))
            total = cursor.fetchone()['total']
            cursor.execute(
                "SELECT * FROM popup WHERE target_type = %s ORDER BY display_order ASC, id ASC LIMIT %s OFFSET %s",
                (target_type, limit, offset)
            )
        else:
            cursor.execute("SELECT COUNT(*) as total FROM popup")
            total = cursor.fetchone()['total']
            cursor.execute(
                "SELECT * FROM popup ORDER BY target_type ASC, display_order ASC, id ASC LIMIT %s OFFSET %s",
                (limit, offset)
            )
        rows = cursor.fetchall()
        for r in rows:
            r['is_active'] = bool(r['is_active'])
            for f in ('start_at', 'end_at', 'created_at', 'updated_at'):
                if r.get(f):
                    r[f] = r[f].strftime('%Y-%m-%d %H:%M:%S')
        return {"total": total, "page": page, "limit": limit, "items": rows}
    finally:
        cursor.close()


def get_popup(connection, popup_id: int) -> Optional[dict]:
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    try:
        cursor.execute("SELECT * FROM popup WHERE id = %s", (popup_id,))
        row = cursor.fetchone()
        if row:
            row['is_active'] = bool(row['is_active'])
            for f in ('start_at', 'end_at', 'created_at', 'updated_at'):
                if row.get(f):
                    row[f] = row[f].strftime('%Y-%m-%d %H:%M:%S')
        return row
    finally:
        cursor.close()


def create_popup(connection, target_type: str, title: str, image_url: str,
                 link_url: Optional[str], display_order: int, is_active: bool,
                 start_at, end_at) -> dict:
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    try:
        cursor.execute(
            """INSERT INTO popup (target_type, title, image_url, link_url, display_order, is_active, start_at, end_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (target_type, title, image_url, link_url, display_order, 1 if is_active else 0, start_at, end_at)
        )
        connection.commit()
        new_id = cursor.lastrowid
        return get_popup(connection, new_id)
    except Exception as e:
        connection.rollback()
        raise e
    finally:
        cursor.close()


def update_popup(connection, popup_id: int, **kwargs) -> Optional[dict]:
    cursor = connection.cursor()
    try:
        updates = []
        params = []
        field_map = {
            'title': 'title', 'image_url': 'image_url', 'link_url': 'link_url',
            'display_order': 'display_order', 'start_at': 'start_at', 'end_at': 'end_at'
        }
        for key, col in field_map.items():
            if key in kwargs and kwargs[key] is not None:
                updates.append(f'{col} = %s')
                params.append(kwargs[key])
        if 'is_active' in kwargs and kwargs['is_active'] is not None:
            updates.append('is_active = %s')
            params.append(1 if kwargs['is_active'] else 0)
        if not updates:
            return get_popup(connection, popup_id)
        params.append(popup_id)
        cursor.execute(f"UPDATE popup SET {', '.join(updates)} WHERE id = %s", params)
        connection.commit()
        if cursor.rowcount == 0:
            return None
        return get_popup(connection, popup_id)
    except Exception as e:
        connection.rollback()
        raise e
    finally:
        cursor.close()


def delete_popup(connection, popup_id: int) -> bool:
    cursor = connection.cursor()
    try:
        cursor.execute("DELETE FROM popup WHERE id = %s", (popup_id,))
        connection.commit()
        return cursor.rowcount > 0
    except Exception as e:
        connection.rollback()
        raise e
    finally:
        cursor.close()


def toggle_popup(connection, popup_id: int) -> Optional[dict]:
    cursor = connection.cursor()
    try:
        cursor.execute("UPDATE popup SET is_active = NOT is_active WHERE id = %s", (popup_id,))
        connection.commit()
        if cursor.rowcount == 0:
            return None
        return get_popup(connection, popup_id)
    except Exception as e:
        connection.rollback()
        raise e
    finally:
        cursor.close()


def reorder_popups(connection, ordered_ids: list) -> None:
    """팝업 순서 일괄 업데이트 (id 배열 인덱스 = display_order)"""
    cursor = connection.cursor()
    try:
        for idx, popup_id in enumerate(ordered_ids):
            cursor.execute("UPDATE popup SET display_order = %s WHERE id = %s", (idx, popup_id))
        connection.commit()
    except Exception as e:
        connection.rollback()
        raise e
    finally:
        cursor.close()


# ── Popup App CRUD ─────────────────────────────────────────────────────────────

def get_active_popups(connection, viewer_type: str, viewer_id: Optional[int] = None) -> list:
    """활성 팝업 목록 조회 (오늘 하루 보지 않기 적용)"""
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    try:
        # 숨김 여부 확인 (로그인 유저만)
        if viewer_id is not None:
            cursor.execute(
                "SELECT hidden_until FROM popup_views WHERE viewer_type = %s AND viewer_id = %s",
                (viewer_type, viewer_id)
            )
            view_row = cursor.fetchone()
            if view_row and view_row['hidden_until'] > datetime.now():
                return []

        cursor.execute(
            """SELECT id, title, image_url, link_url, display_order
               FROM popup
               WHERE target_type = %s
                 AND is_active = 1
                 AND (start_at IS NULL OR start_at <= NOW())
                 AND (end_at IS NULL OR end_at >= NOW())
               ORDER BY display_order ASC, id ASC""",
            (viewer_type,)
        )
        return cursor.fetchall()
    finally:
        cursor.close()


def hide_popups_today(connection, viewer_type: str, viewer_id: int) -> None:
    """오늘 하루 보지 않기 (자정까지 숨김)"""
    from datetime import date, timedelta
    hidden_until = datetime.combine(date.today() + timedelta(days=1), datetime.min.time())
    cursor = connection.cursor()
    try:
        cursor.execute(
            """INSERT INTO popup_views (viewer_type, viewer_id, hidden_until)
               VALUES (%s, %s, %s)
               ON DUPLICATE KEY UPDATE hidden_until = VALUES(hidden_until)""",
            (viewer_type, viewer_id, hidden_until)
        )
        connection.commit()
    except Exception as e:
        connection.rollback()
        raise e
    finally:
        cursor.close()
