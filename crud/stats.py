"""
Statistics CRUD 로직
"""
import pymysql
from typing import List, Dict, Optional
from datetime import date, datetime

from db.session import get_db_connection, close_db_connection


def get_admin_statistics() -> Dict:
    """관리자 통계 데이터 조회 (전체 발행 수, 사용 수, 미사용 수)"""
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        # 전체 발행 수
        cursor.execute("SELECT COUNT(*) as total FROM gifticon")
        total_issued = cursor.fetchone()['total'] or 0
        
        # 사용 수
        cursor.execute("SELECT COUNT(*) as total FROM gifticon WHERE status = 'USED'")
        total_used = cursor.fetchone()['total'] or 0
        
        # 미사용 수
        cursor.execute("SELECT COUNT(*) as total FROM gifticon WHERE status != 'USED'")
        total_unused = cursor.fetchone()['total'] or 0
        
        return {
            'total_issued': total_issued,
            'total_used': total_used,
            'total_unused': total_unused
        }
    finally:
        cursor.close()
        close_db_connection(connection)


def get_admin_settlement_data(start_date: Optional[date] = None, end_date: Optional[date] = None) -> Dict:
    """관리자 정산 데이터 조회 (정산금액, 플랫폼 수수료 매출)"""
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        query = """
            SELECT 
                COALESCE(SUM(total_sales_amount), 0) as total_settlement_amount,
                COALESCE(SUM(total_fee_amount), 0) as total_fee_revenue
            FROM settlement
            WHERE status IN ('COMPLETED', 'PENDING')
        """
        
        params = []
        if start_date:
            query += " AND period_start >= %s"
            params.append(start_date)
        
        if end_date:
            query += " AND period_end <= %s"
            params.append(end_date)
        
        cursor.execute(query, params)
        result = cursor.fetchone()
        
        return {
            'total_settlement_amount': float(result['total_settlement_amount'] or 0),
            'total_fee_revenue': float(result['total_fee_revenue'] or 0)
        }
    finally:
        cursor.close()
        close_db_connection(connection)


def create_settlement_data(cycle_id: int) -> Dict:
    """정산 데이터 생성 (settlement, settlement_details)
    
    정산 주기가 끝난 다음날 또는 이전 정산주기에 대해 정산 데이터 생성
    """
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        # 1. 정산 주기 정보 조회
        cursor.execute("""
            SELECT cycle_id, period_start_date, period_end_date, payout_date
            FROM settlement_cycles
            WHERE cycle_id = %s
        """, (cycle_id,))
        
        cycle = cursor.fetchone()
        if not cycle:
            raise ValueError(f"정산 주기 {cycle_id}를 찾을 수 없습니다.")
        
        period_start = cycle['period_start_date']
        period_end = cycle['period_end_date']
        
        # 2. 미정산 settlement_details 조회 (settlement_id IS NULL, 기간 내 사용된 기프티콘)
        cursor.execute("""
            SELECT
                sd.id as detail_id,
                sd.gifticon_id,
                sd.sales_amount,
                sd.fee_amount,
                sd.settlement_amount,
                g.store_id,
                COALESCE(a.bank, '') as bank_name,
                COALESCE(a.account, '') as account_number
            FROM settlement_details sd
            JOIN gifticon g ON sd.gifticon_id = g.id
            LEFT JOIN account a ON g.store_id = a.store_id
            WHERE sd.settlement_id IS NULL
            AND DATE(g.used_at) >= %s
            AND DATE(g.used_at) <= %s
        """, (period_start, period_end))

        details = cursor.fetchall()

        if not details:
            return {'message': '정산할 기프티콘이 없습니다.', 'settlement_count': 0}

        # 3. 매장별로 그룹화
        store_settlements = {}

        for row in details:
            store_id = row['store_id']
            if store_id not in store_settlements:
                store_settlements[store_id] = {
                    'details': [],
                    'bank_name': row['bank_name'],
                    'account_number': row['account_number']
                }
            store_settlements[store_id]['details'].append(row)

        # 4. 각 매장별로 settlement 마스터 생성 후 settlement_details.settlement_id 업데이트
        created_count = 0
        failed_count = 0
        failed_reasons = []

        for store_id, data in store_settlements.items():
            total_sales = sum(d['sales_amount'] for d in data['details'])
            total_fee = sum(d['fee_amount'] for d in data['details'])
            total_payout = sum(d['settlement_amount'] for d in data['details'])
            bank_name = data.get('bank_name') or ''
            account_number = data.get('account_number') or ''

            try:
                if not bank_name.strip() and not account_number.strip():
                    raise ValueError('계좌 정보가 없습니다.')

                connection.begin()

                cursor.execute("""
                    INSERT INTO settlement (
                        store_id, cycle_id, period_start, period_end,
                        total_sales_amount, total_fee_amount, net_payout_amount,
                        status, payout_date, bank_name, account_number, failure_reason
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'PENDING', %s, %s, %s, NULL)
                """, (
                    store_id, cycle_id, period_start, period_end,
                    total_sales, total_fee, total_payout,
                    cycle['payout_date'], bank_name, account_number
                ))
                settlement_id = cursor.lastrowid

                detail_ids = [d['detail_id'] for d in data['details']]
                cursor.execute(
                    f"UPDATE settlement_details SET settlement_id = %s WHERE id IN ({','.join(['%s'] * len(detail_ids))})",
                    [settlement_id] + detail_ids
                )

                connection.commit()
                created_count += 1
            except Exception as e:
                connection.rollback()
                fail_reason = str(e)[:500]
                failed_count += 1
                if len(failed_reasons) < 5:
                    failed_reasons.append(fail_reason)
                connection.begin()
                cursor.execute("""
                    INSERT INTO settlement (
                        store_id, cycle_id, period_start, period_end,
                        total_sales_amount, total_fee_amount, net_payout_amount,
                        status, payout_date, bank_name, account_number, failure_reason
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'FAILED', %s, %s, %s, %s)
                """, (
                    store_id, cycle_id, period_start, period_end,
                    total_sales, total_fee, total_payout,
                    cycle['payout_date'], bank_name, account_number, fail_reason
                ))
                connection.commit()
        
        if failed_count > 0:
            msg = f"일부 매장 정산 생성 실패 (성공 {created_count}건, 실패 {failed_count}건)."
            if failed_reasons:
                msg += " 사유: " + "; ".join(failed_reasons[:3])
            return {
                'success': False,
                'message': msg,
                'settlement_count': created_count,
                'failed_count': failed_count,
                'cycle_id': cycle_id
            }
        return {
            'message': '정산 데이터가 생성되었습니다.',
            'settlement_count': created_count,
            'cycle_id': cycle_id
        }
    except Exception as e:
        connection.rollback()
        raise e
    finally:
        cursor.close()
        close_db_connection(connection)
