"""
Statistics CRUD 로직
"""
import pymysql
from typing import List, Dict, Optional
from datetime import date, datetime

from db.session import get_db_connection, close_db_connection
from crud.settlement import calc_fee_supply_and_vat


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
        connection.close()


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
        connection.close()


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
        
        # 2. 해당 기간에 사용된 기프티콘 조회 (아직 정산되지 않은 것만). 매출액은 주문(orders) 금액 사용 (gifticon에는 total_price 컬럼 없음)
        cursor.execute("""
            SELECT 
                g.id as gifticon_id,
                g.store_id,
                COALESCE(o.amount, 0) as sales_amount,
                g.applied_fee_rate,
                COALESCE(a.bank, '') as bank_name,
                COALESCE(a.account, '') as account_number
            FROM gifticon g
            LEFT JOIN orders o ON g.order_id = o.id
            LEFT JOIN account a ON g.store_id = a.store_id
            WHERE g.status = 'USED'
            AND DATE(g.used_at) >= %s
            AND DATE(g.used_at) <= %s
            AND g.id NOT IN (SELECT gifticon_id FROM settlement_details)
        """, (period_start, period_end))
        
        gifticons = cursor.fetchall()
        
        if not gifticons:
            return {'message': '정산할 기프티콘이 없습니다.', 'settlement_count': 0}
        
        # 3. 매장별로 그룹화하여 정산 데이터 생성
        store_settlements = {}
        
        for gifticon in gifticons:
            store_id = gifticon['store_id']
            if store_id not in store_settlements:
                store_settlements[store_id] = {
                    'gifticons': [],
                    'bank_name': gifticon['bank_name'],
                    'account_number': gifticon['account_number']
                }
            
            # 수수료 계산: 공급가액 원미만 절사 + 부가세 소수점 첫째 자리 반올림
            fee_rate = float(gifticon['applied_fee_rate'] or 3.00)
            sales_amount = int(gifticon['sales_amount'] or 0)
            _, _, fee_amount = calc_fee_supply_and_vat(sales_amount, fee_rate)
            settlement_amount = sales_amount - fee_amount
            
            store_settlements[store_id]['gifticons'].append({
                'gifticon_id': gifticon['gifticon_id'],
                'sales_amount': sales_amount,
                'fee_amount': fee_amount,
                'settlement_amount': settlement_amount
            })
        
        # 4. 각 매장별로 settlement 생성 (실패 시 해당 매장만 FAILED 행 저장)
        created_count = 0
        failed_count = 0
        failed_reasons = []
        
        for store_id, data in store_settlements.items():
            total_sales = sum(g['sales_amount'] for g in data['gifticons'])
            total_fee = sum(g['fee_amount'] for g in data['gifticons'])
            total_payout = sum(g['settlement_amount'] for g in data['gifticons'])
            bank_name = data.get('bank_name') or ''
            account_number = data.get('account_number') or ''
            
            try:
                # 계좌 정보 없으면 실패 처리
                if not bank_name.strip() and not account_number.strip():
                    raise ValueError('계좌 정보가 없습니다.')
                
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
                
                for gifticon in data['gifticons']:
                    cursor.execute("""
                        INSERT INTO settlement_details (
                            settlement_id, gifticon_id, sales_amount, fee_amount, settlement_amount
                        ) VALUES (%s, %s, %s, %s, %s)
                    """, (
                        settlement_id,
                        gifticon['gifticon_id'],
                        gifticon['sales_amount'],
                        gifticon['fee_amount'],
                        gifticon['settlement_amount']
                    ))
                
                created_count += 1
            except Exception as e:
                # 매장별 실패 시 FAILED 행 저장
                fail_reason = str(e)[:500]
                failed_count += 1
                if len(failed_reasons) < 5:
                    failed_reasons.append(fail_reason)
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
        connection.close()
