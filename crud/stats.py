"""
Statistics CRUD 로직
"""
import math
import pymysql
from typing import List, Dict, Optional
from datetime import date, datetime

from db.session import get_db_connection, close_db_connection
from crud import promotion as promotion_crud


def _calc_fee(sales_amount: int, fee_rate_pct: float) -> tuple[int, int, int]:
    """수수료 공급가/VAT/총액 계산 (원미만 절사, VAT 반올림)"""
    supply = math.floor(sales_amount * fee_rate_pct / 100)
    vat = round(supply * 0.1)
    return supply, vat, supply + vat


def get_admin_statistics() -> Dict:
    """관리자 통계 데이터 조회 (전체 발행 수, 사용 수, 미사용 수)"""
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)

    try:
        cursor.execute("""
            SELECT
                COUNT(*) AS total_issued,
                SUM(status = 'USED') AS total_used,
                SUM(status != 'USED') AS total_unused
            FROM gifticon
        """)
        row = cursor.fetchone()
        return {
            'total_issued': int(row['total_issued'] or 0),
            'total_used': int(row['total_used'] or 0),
            'total_unused': int(row['total_unused'] or 0),
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
    """정산 데이터 생성 (settlement, settlement_details 연결) - GNB-142

    정산 주기가 끝난 후 매장별로 총 매출액을 집계하고, 정산 지급 예정일(payout_date) 기준으로
    활성 프로모션을 조회해 프로모션 적용/미적용 수수료를 각각 계산해 저장.
    """
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)

    try:
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
        payout_date = cycle['payout_date']

        # 매장별 총 매출 집계 (개별 수수료 없음)
        cursor.execute("""
            SELECT
                g.store_id,
                SUM(sd.sales_amount) AS total_sales,
                COALESCE(a.bank, '') AS bank_name,
                COALESCE(a.account, '') AS account_number
            FROM settlement_details sd
            JOIN gifticon g ON sd.gifticon_id = g.id
            LEFT JOIN account a ON g.store_id = a.store_id
            WHERE sd.settlement_id IS NULL
              AND g.used_at >= %s
              AND g.used_at < DATE_ADD(%s, INTERVAL 1 DAY)
            GROUP BY g.store_id, a.bank, a.account
        """, (period_start, period_end))

        store_rows = cursor.fetchall()

        if not store_rows:
            return {'message': '정산할 기프티콘이 없습니다.', 'settlement_count': 0}

        created_count = 0
        failed_count = 0
        failed_reasons = []

        for row in store_rows:
            store_id = row['store_id']
            total_sales = int(row['total_sales'] or 0)
            bank_name = row['bank_name'] or ''
            account_number = row['account_number'] or ''

            # 지급 예정일 기준 프로모션 조회
            fee_info = promotion_crud.get_fee_info_for_settlement(store_id, payout_date)
            base_fee_rate = fee_info['base_fee_rate']
            applied_fee_rate = fee_info['applied_fee_rate']
            applied_promo_id = fee_info['applied_promo_id']

            # 원본(프로모션 미적용) 수수료 계산
            original_supply, original_vat, original_fee = _calc_fee(total_sales, base_fee_rate)

            # 프로모션 적용 수수료 (프로모션 있을 때만)
            if applied_promo_id is not None:
                promo_supply, promo_vat, promo_fee = _calc_fee(total_sales, applied_fee_rate)
                total_fee = promo_fee
            else:
                promo_supply = promo_vat = promo_fee = None
                total_fee = original_fee

            net_payout = total_sales - total_fee

            try:
                if not bank_name.strip() and not account_number.strip():
                    raise ValueError('계좌 정보가 없습니다.')

                connection.begin()

                cursor.execute("""
                    INSERT INTO settlement (
                        store_id, cycle_id, period_start, period_end,
                        total_sales_amount, total_fee_amount, net_payout_amount,
                        base_fee_rate, applied_promo_id, applied_fee_rate,
                        original_fee_supply, original_fee_vat, original_fee_amount,
                        promo_fee_supply, promo_fee_vat, promo_fee_amount,
                        status, payout_date, bank_name, account_number, failure_reason
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'PENDING', %s, %s, %s, NULL)
                """, (
                    store_id, cycle_id, period_start, period_end,
                    total_sales, total_fee, net_payout,
                    base_fee_rate, applied_promo_id, applied_fee_rate,
                    original_supply, original_vat, original_fee,
                    promo_supply, promo_vat, promo_fee,
                    payout_date, bank_name, account_number
                ))
                settlement_id = cursor.lastrowid

                cursor.execute("""
                    UPDATE settlement_details sd
                    JOIN gifticon g ON sd.gifticon_id = g.id
                    SET sd.settlement_id = %s
                    WHERE sd.settlement_id IS NULL
                      AND g.store_id = %s
                      AND g.used_at >= %s
                      AND g.used_at < DATE_ADD(%s, INTERVAL 1 DAY)
                """, (settlement_id, store_id, period_start, period_end))

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
                        base_fee_rate, applied_promo_id, applied_fee_rate,
                        original_fee_supply, original_fee_vat, original_fee_amount,
                        promo_fee_supply, promo_fee_vat, promo_fee_amount,
                        status, payout_date, bank_name, account_number, failure_reason
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'FAILED', %s, %s, %s, %s)
                """, (
                    store_id, cycle_id, period_start, period_end,
                    total_sales, total_fee, net_payout,
                    base_fee_rate, applied_promo_id, applied_fee_rate,
                    original_supply, original_vat, original_fee,
                    promo_supply, promo_vat, promo_fee,
                    payout_date, bank_name, account_number, fail_reason
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
