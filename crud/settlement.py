"""
Settlement CRUD 로직
"""
import pymysql
from typing import List, Dict, Optional
from datetime import datetime

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


def create_or_update_order_settlement(connection, order_id: int, store_id: int, order_amount: float, 
                                      order_date: datetime, commission_rate: float = 6.9) -> int:
    """
    주문건별 정산 정보 생성 또는 업데이트
    
    Args:
        connection: DB 연결 (이미 열려있는 connection 사용)
        order_id: 주문 ID
        store_id: 매장 ID
        order_amount: 주문 금액
        order_date: 주문 일시
        commission_rate: 수수료율 (기본 6.9%)
    
    Returns:
        order_settlement.id
    """
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        # 수수료 계산 (소수점 이하 반올림)
        commission_amount = round(order_amount * (commission_rate / 100))
        settlement_amount = order_amount - commission_amount
        
        # 주문건별 정산 정보 생성
        insert_query = """
            INSERT INTO order_settlement (
                order_id, store_id, order_amount, commission_rate, commission_amount,
                settlement_amount, order_date, status
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'PENDING')
            ON DUPLICATE KEY UPDATE
                order_amount = VALUES(order_amount),
                commission_rate = VALUES(commission_rate),
                commission_amount = VALUES(commission_amount),
                settlement_amount = VALUES(settlement_amount),
                order_date = VALUES(order_date),
                updated_at = NOW()
        """
        cursor.execute(insert_query, (
            order_id,
            store_id,
            order_amount,
            commission_rate,
            commission_amount,
            settlement_amount,
            order_date
        ))
        connection.commit()
        
        # 생성/업데이트된 order_settlement의 id 조회
        cursor.execute("SELECT id FROM order_settlement WHERE order_id = %s", (order_id,))
        result = cursor.fetchone()
        return result['id'] if result else cursor.lastrowid
        
    finally:
        cursor.close()


def create_or_update_monthly_settlement(connection, store_id: int, year: int, month: int) -> int:
    """
    월별 정산 정보 생성 또는 업데이트
    
    Args:
        connection: DB 연결 (이미 열려있는 connection 사용)
        store_id: 매장 ID
        year: 정산 년도
        month: 정산 월 (1~12)
    
    Returns:
        monthly_settlement.id
    """
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        # 해당 월의 주문건별 정산 정보 집계
        aggregate_query = """
            SELECT 
                COUNT(*) as total_order_count,
                COALESCE(SUM(order_amount), 0) as total_amount,
                COALESCE(SUM(commission_amount), 0) as total_commission,
                COALESCE(SUM(settlement_amount), 0) as settlement_amount
            FROM order_settlement
            WHERE store_id = %s
            AND YEAR(order_date) = %s
            AND MONTH(order_date) = %s
            AND status = 'PENDING'
        """
        cursor.execute(aggregate_query, (store_id, year, month))
        aggregate = cursor.fetchone()
        
        total_order_count = aggregate['total_order_count'] or 0
        total_amount = float(aggregate['total_amount'] or 0)
        total_commission = float(aggregate['total_commission'] or 0)
        settlement_amount = float(aggregate['settlement_amount'] or 0)
        
        # 월별 정산 정보 생성 또는 업데이트
        insert_query = """
            INSERT INTO monthly_settlement (
                store_id, settlement_year, settlement_month,
                total_order_count, total_amount, total_commission, settlement_amount,
                status
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'PENDING')
            ON DUPLICATE KEY UPDATE
                total_order_count = VALUES(total_order_count),
                total_amount = VALUES(total_amount),
                total_commission = VALUES(total_commission),
                settlement_amount = VALUES(settlement_amount),
                updated_at = NOW()
        """
        cursor.execute(insert_query, (
            store_id,
            year,
            month,
            total_order_count,
            total_amount,
            total_commission,
            settlement_amount
        ))
        connection.commit()
        
        # 생성/업데이트된 monthly_settlement의 id 조회
        cursor.execute(
            "SELECT id FROM monthly_settlement WHERE store_id = %s AND settlement_year = %s AND settlement_month = %s",
            (store_id, year, month)
        )
        result = cursor.fetchone()
        return result['id'] if result else cursor.lastrowid
        
    finally:
        cursor.close()


def update_settlement_on_order(connection, order_id: int, store_id: int, order_amount: float, 
                                order_date: datetime, commission_rate: float = 6.9):
    """
    주문 발생 시 정산 정보 업데이트 (건별 + 월별)
    
    Args:
        connection: DB 연결 (이미 열려있는 connection 사용)
        order_id: 주문 ID
        store_id: 매장 ID
        order_amount: 주문 금액
        order_date: 주문 일시
        commission_rate: 수수료율 (기본 6.9%)
    """
    # 1. 주문건별 정산 정보 생성/업데이트
    create_or_update_order_settlement(connection, order_id, store_id, order_amount, order_date, commission_rate)
    
    # 2. 해당 월의 월별 정산 정보 생성/업데이트
    year = order_date.year
    month = order_date.month
    create_or_update_monthly_settlement(connection, store_id, year, month)


def get_settlements_by_store(store_id: int) -> List[Dict]:
    """매장별 정산 리스트 조회"""
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        cursor.execute("""
            SELECT * FROM monthly_settlement
            WHERE store_id = %s
            ORDER BY settlement_year DESC, settlement_month DESC
        """, (store_id,))
        
        results = cursor.fetchall()
        settlements = []
        
        for result in results:
            settlements.append({
                'settlement_id': result['id'],
                'total_price': result['total_amount'] or 0,
                'settlement_msg': result.get('memo', ''),
                'settlement_date': result['settlement_date'].isoformat() if result.get('settlement_date') else None,
                'settlement_period': f"{result['settlement_year']}-{result['settlement_month']:02d}",
                'status': result['status'],
                'tax_invoice_issued': bool(result.get('tax_invoice_issued', False)),
                'tax_invoice_issued_date': result['tax_invoice_issued_date'].isoformat() if result.get('tax_invoice_issued_date') else None,
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
                m.menu_name as name,
                os.order_amount as price,
                g.used_at as used_time,
                os.commission_amount as commission
            FROM monthly_settlement ms
            JOIN order_settlement os ON ms.store_id = os.store_id 
                AND YEAR(os.order_date) = ms.settlement_year
                AND MONTH(os.order_date) = ms.settlement_month
            JOIN orders o ON os.order_id = o.id
            JOIN orders_gifticon og ON o.id = og.order_id
            JOIN gifticon g ON og.gifticon_id = g.id
            JOIN menu m ON g.menu_id = m.id
            WHERE ms.id = %s
            AND g.status = 'USED'
            ORDER BY g.used_at DESC
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
                'used_time': result['used_time'].isoformat() if result.get('used_time') else None,
            })
        
        return details
    finally:
        cursor.close()
        connection.close()
