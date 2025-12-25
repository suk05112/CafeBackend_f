"""
Settlement CRUD 로직
"""
import pymysql
from typing import List, Dict, Optional

from db.session import get_db_connection
from core.s3_config import S3_CLIENT, BUCKET_NAME
from models.settlement import Account

s3 = S3_CLIENT
bucket_name = BUCKET_NAME


def create_account(store_id: int, account: Account) -> bool:
    """계좌 정보 등록"""
    connection = get_db_connection()
    cursor = connection.cursor()
    
    try:
        query = """
            INSERT INTO account (store_id, name, code, bank, account)
            VALUES (%s, %s, %s, %s, %s)
        """
        cursor.execute(query, (
            store_id,
            account.name,
            account.code,
            account.bank,
            account.account
        ))
        connection.commit()
        return True
    except Exception as e:
        connection.rollback()
        raise e
    finally:
        cursor.close()
        connection.close()


def get_account_by_store(store_id: int) -> Optional[Dict]:
    """매장별 계좌 정보 조회"""
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        cursor.execute("SELECT * FROM account WHERE store_id = %s", (store_id,))
        result = cursor.fetchone()
        
        if result:
            bankbook = s3.generate_presigned_url('get_object',
                Params={'Bucket': bucket_name, 'Key': f'bankbook/bankbook_{store_id}.png'},
                ExpiresIn=3600)
            business = s3.generate_presigned_url('get_object',
                Params={'Bucket': bucket_name, 'Key': f'business_registration/business_registration_{store_id}.png'},
                ExpiresIn=3600)
            
            return {
                'name': result['name'],
                'account': result['account'],
                'bank': result['bank'],
                'bankbook': bankbook,
                'business': business
            }
        return None
    finally:
        cursor.close()
        connection.close()


def get_settlements_by_store(store_id: int) -> List[Dict]:
    """매장별 정산 리스트 조회"""
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        cursor.execute("""
            SELECT * FROM settlement
            WHERE store_id = %s
            ORDER BY settlement_date DESC
        """, (store_id,))
        
        results = cursor.fetchall()
        settlements = []
        
        for result in results:
            settlements.append({
                'settlement_id': result['settlement_id'],
                'total_price': result['total_price'] or 0,
                'settlement_msg': result['settlement_msg'],
                'settlement_date': result['settlement_date'],
                'settlement_period': result['settlement_period'],
                'status': result['status'],
            })
        
        return settlements
    finally:
        cursor.close()
        connection.close()


def get_settlement_detail(settlement_id: int) -> List[Dict]:
    """정산 상세 내역 조회"""
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        cursor.execute("""
            SELECT DISTINCT
                m.name,
                o.price,
                g.used_time,
                o.commission
            FROM settlement s
            JOIN orders o ON s.store_id = o.store_id
            JOIN orders_gifticon og ON o.id = og.order_id
            JOIN gifticon g ON og.gifticon_id = g.id
            JOIN menu m ON g.menu_id = m.id
            WHERE o.settlement_id = %s
            AND g.use_yn = 1
            ORDER BY g.used_time DESC
        """, (settlement_id,))
        
        results = cursor.fetchall()
        details = []
        
        for result in results:
            commission = result['commission'] or 0
            details.append({
                'menu_name': result['name'],
                'commission': commission,
                'price': result['price'],
                'deposit': result['price'] - commission,
                'used_time': result['used_time'],
            })
        
        return details
    finally:
        cursor.close()
        connection.close()


