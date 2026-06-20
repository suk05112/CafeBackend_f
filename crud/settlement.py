"""
Settlement CRUD 로직
"""
import math
import pymysql
from typing import List, Dict, Optional, Tuple
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

KST = ZoneInfo('Asia/Seoul')

from db.session import get_db_connection, close_db_connection


def calc_fee_supply_and_vat(sales_amount: int, fee_rate_pct: float) -> Tuple[int, int, int]:
    """수수료 공급가액(원미만 절사) + 부가세(소수점 첫째 자리 반올림).
    예: 2,220원 3.5% → 공급가액 77원 + 부가세 8원 = 수수료 85원.
    Returns (공급가액, 부가세, 총수수료)."""
    supply = math.floor(sales_amount * fee_rate_pct / 100)  # 원미만 절사
    vat = round(supply * 0.1)  # 부가세 10%, 소수점 첫째 자리 반올림
    total_fee = supply + vat
    return (supply, vat, total_fee)
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
            SELECT settlement_id, total_sales_amount, memo, payout_date,
                   period_start, status, tax_invoice_issued, tax_invoice_issued_date
            FROM settlement
            WHERE store_id = %s
            ORDER BY period_start DESC
        """, (store_id,))

        results = cursor.fetchall()
        settlements = []

        for result in results:
            period_start = result.get('period_start')
            settlements.append({
                'settlement_id': result['settlement_id'],
                'total_price': int(result['total_sales_amount'] or 0),
                'settlement_msg': result.get('memo') or '',
                'settlement_date': result['payout_date'].isoformat() if result.get('payout_date') else None,
                'settlement_period': period_start.strftime('%Y-%m') if period_start else None,
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
            SELECT
                m.menu_name AS name,
                sd.sales_amount AS price,
                g.used_at AS used_time,
                sd.fee_amount AS commission
            FROM settlement_details sd
            JOIN gifticon g ON sd.gifticon_id = g.id
            LEFT JOIN menu m ON g.menu_id = m.id
            WHERE sd.settlement_id = %s
            ORDER BY g.used_at DESC
        """, (settlement_id,))

        results = cursor.fetchall()
        details = []

        for result in results:
            commission = result['commission'] or 0
            price = result['price'] or 0
            details.append({
                'menu_name': result['name'],
                'commission': commission,
                'price': price,
                'deposit': price - commission,
                'used_time': result['used_time'].isoformat() if result.get('used_time') else None,
            })

        return details
    finally:
        cursor.close()
        connection.close()


def update_account(store_id: int, account: Account) -> bool:
    """계좌 정보 변경"""
    connection = get_db_connection()
    cursor = connection.cursor()
    
    try:
        # 기존 계좌 정보 확인
        cursor.execute("SELECT id FROM account WHERE store_id = %s", (store_id,))
        existing = cursor.fetchone()
        
        if existing:
            # 업데이트
            query = """
                UPDATE account 
                SET name = %s, code = %s, bank = %s, account = %s, updated_at = NOW()
                WHERE store_id = %s
            """
            cursor.execute(query, (
                account.name,
                account.code,
                account.bank,
                account.account,
                store_id
            ))
        else:
            # 신규 등록
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


def get_store_statistics(store_id: int) -> Dict:
    """매장 통계 데이터 조회 (발행 수, 사용 수, 미사용 수)"""
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        # 전체 발행 수
        cursor.execute("SELECT COUNT(*) as total FROM gifticon WHERE store_id = %s", (store_id,))
        total_issued = cursor.fetchone()['total'] or 0
        
        # 사용 수
        cursor.execute("SELECT COUNT(*) as total FROM gifticon WHERE store_id = %s AND status = 'USED'", (store_id,))
        total_used = cursor.fetchone()['total'] or 0
        
        # 미사용 수
        cursor.execute("SELECT COUNT(*) as total FROM gifticon WHERE store_id = %s AND status != 'USED'", (store_id,))
        total_unused = cursor.fetchone()['total'] or 0
        
        return {
            'total_issued': total_issued,
            'total_used': total_used,
            'total_unused': total_unused
        }
    finally:
        cursor.close()
        connection.close()


def get_owner_settlement_data(store_id: int) -> List[Dict]:
    """사장님 정산 데이터 조회 (정산 주기별)"""
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        cursor.execute("""
            SELECT 
                s.settlement_id,
                s.cycle_id,
                s.period_start,
                s.period_end,
                s.total_sales_amount,
                s.total_fee_amount,
                s.net_payout_amount,
                s.status,
                s.payout_date,
                s.failure_reason,
                sc.payout_date as expected_payout_date
            FROM settlement s
            LEFT JOIN settlement_cycles sc ON s.cycle_id = sc.cycle_id
            WHERE s.store_id = %s
            ORDER BY s.period_start DESC
        """, (store_id,))
        
        settlements = cursor.fetchall()
        result = []
        
        for settlement in settlements:
            result.append({
                'settlement_id': settlement['settlement_id'],
                'cycle_id': settlement['cycle_id'],
                'period_start': settlement['period_start'].isoformat() if settlement['period_start'] else None,
                'period_end': settlement['period_end'].isoformat() if settlement['period_end'] else None,
                'expected_amount': float(settlement['net_payout_amount'] or 0),
                'fee_amount': float(settlement['total_fee_amount'] or 0),
                'expected_payout_date': settlement['expected_payout_date'].isoformat() if settlement.get('expected_payout_date') else None,
                'status': settlement['status'],
                'payout_date': settlement['payout_date'].isoformat() if settlement['payout_date'] else None,
                'failure_reason': settlement.get('failure_reason'),
            })
        
        return result
    finally:
        cursor.close()
        connection.close()


def get_owner_settlement_list_unified(
    store_id: int,
    past_months: int = 3,
) -> List[Dict]:
    """사장님 정산 목록.
    1) settlement_cycles 전체 읽어서
    2) period_end_date가 과거 past_months달 ~ 오늘 범위인 주기 중, 정산 데이터 존재하는 것만 리스트로 구성
    3) period_start_date ~ period_end_date에 오늘이 포함된 주기(진행 중)는 정산 데이터 없으므로 기존 주문 데이터로 preview 만들어 리스트 맨 앞에 추가
    """
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    try:
        today = datetime.now(tz=KST).date()
        cutoff = today - timedelta(days=max(1, past_months * 30))

        cursor.execute("""
            SELECT cycle_id, period_start_date, period_end_date, payout_date, status
            FROM settlement_cycles
            ORDER BY period_start_date ASC
        """)
        all_cycles = cursor.fetchall()
        if not all_cycles:
            return []

        result = []
        current_cycle = None

        for c in all_cycles:
            period_start = c.get('period_start_date')
            period_end = c.get('period_end_date')
            if not period_start or not period_end:
                continue
            if hasattr(period_start, 'date') and callable(period_start.date):
                period_start = period_start.date()
            if hasattr(period_end, 'date') and callable(period_end.date):
                period_end = period_end.date()

            if period_start <= today <= period_end:
                current_cycle = c

            if period_end < cutoff or period_end > today:
                continue
            cursor.execute("""
                SELECT s.settlement_id, s.cycle_id, s.period_start, s.period_end,
                    s.total_sales_amount, s.total_fee_amount, s.net_payout_amount,
                    s.status, s.payout_date, s.failure_reason,
                    sc.payout_date AS expected_payout_date
                FROM settlement s
                LEFT JOIN settlement_cycles sc ON s.cycle_id = sc.cycle_id
                WHERE s.store_id = %s AND s.cycle_id = %s
                ORDER BY s.settlement_id DESC
                LIMIT 1
            """, (store_id, c['cycle_id']))
            row = cursor.fetchone()
            if not row:
                continue
            pe = row.get('expected_payout_date')
            if pe and hasattr(pe, 'isoformat'):
                pe = pe.isoformat()
            elif pe is not None:
                pe = str(pe)
            else:
                pe = None
            result.append({
                'settlement_id': row['settlement_id'],
                'cycle_id': row['cycle_id'],
                'period_start': row['period_start'].isoformat() if row.get('period_start') else None,
                'period_end': row['period_end'].isoformat() if row.get('period_end') else None,
                'total_sales_amount': int(row['total_sales_amount'] or 0),
                'total_fee_amount': int(row['total_fee_amount'] or 0),
                'net_payout_amount': int(row['net_payout_amount'] or 0),
                'expected_amount': float(row['net_payout_amount'] or 0),
                'fee_amount': float(row['total_fee_amount'] or 0),
                'expected_payout_date': pe,
                'status': row['status'],
                'payout_date': row['payout_date'].isoformat() if row.get('payout_date') else None,
                'failure_reason': row.get('failure_reason'),
            })

        if current_cycle:
            period_start = current_cycle.get('period_start_date')
            period_end = current_cycle.get('period_end_date')
            cycle_id = current_cycle['cycle_id']
            payout_date = current_cycle.get('payout_date')
            period_start_str = period_start.isoformat() if hasattr(period_start, 'isoformat') else str(period_start)
            period_end_str = period_end.isoformat() if hasattr(period_end, 'isoformat') else str(period_end)
            payout_date_str = payout_date.isoformat() if payout_date and hasattr(payout_date, 'isoformat') else (str(payout_date) if payout_date else None)

            cursor.execute("""
                SELECT sd.sales_amount, sd.fee_amount
                FROM settlement_details sd
                JOIN gifticon g ON sd.gifticon_id = g.id
                WHERE sd.settlement_id IS NULL
                  AND g.store_id = %s
                  AND DATE(g.used_at) >= %s
                  AND DATE(g.used_at) <= %s
            """, (store_id, period_start_str, period_end_str))
            rows = cursor.fetchall()
            total_sales = 0
            total_fee = 0
            for r in rows:
                total_sales += int(r['sales_amount'] or 0)
                total_fee += int(r['fee_amount'] or 0)
            net = total_sales - total_fee
            if total_sales > 0:
                preview = {
                    'settlement_id': None,
                    'cycle_id': cycle_id,
                    'period_start': period_start_str,
                    'period_end': period_end_str,
                    'total_sales_amount': total_sales,
                    'total_fee_amount': total_fee,
                    'net_payout_amount': net,
                    'expected_amount': float(net),
                    'fee_amount': float(total_fee),
                    'expected_payout_date': payout_date_str,
                    'status': 'PENDING',
                    'payout_date': None,
                    'failure_reason': None,
                }
                result.insert(0, preview)

        result.sort(key=lambda x: (x.get('period_start') or ''), reverse=True)
        return result
    finally:
        cursor.close()
        connection.close()


def get_owner_settlement_detail(settlement_id: int) -> Optional[Dict]:
    """사장님 정산 상세: 헤더(settlement) + 건별 내역(details). 없으면 None."""
    sid = int(settlement_id)
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    try:
        cursor.execute("""
            SELECT settlement_id, store_id, cycle_id, period_start, period_end,
                total_sales_amount, total_fee_amount, net_payout_amount,
                status, payout_date, failure_reason
            FROM settlement
            WHERE settlement_id = %s
        """, (sid,))
        settlement = cursor.fetchone()
        if not settlement:
            return None
        cursor.execute("""
            SELECT sd.id, sd.gifticon_id, sd.sales_amount, sd.fee_amount, sd.settlement_amount,
                sd.base_fee_rate, sd.applied_promo_id, sd.applied_fee_rate, sd.fee_supply, sd.fee_vat,
                g.used_at, m.menu_name
            FROM settlement_details sd
            JOIN gifticon g ON sd.gifticon_id = g.id
            LEFT JOIN menu m ON g.menu_id = m.id
            WHERE sd.settlement_id = %s
            ORDER BY sd.id
        """, (sid,))
        rows = cursor.fetchall()
        details = []
        supply_amount = 0
        vat_amount = 0
        base_fee_rate = None
        promo_fee_rate = None
        promo_discount_amount = None
        for d in rows:
            used_at = d.get('used_at')
            if used_at and hasattr(used_at, 'strftime'):
                used_at_str = used_at.strftime('%Y-%m-%d %H:%M')
            else:
                used_at_str = str(used_at) if used_at else None
            supply_amount += int(d['fee_supply'] or 0)
            vat_amount += int(d['fee_vat'] or 0)
            if base_fee_rate is None and d.get('base_fee_rate') is not None:
                base_fee_rate = float(d['base_fee_rate'])
            if d.get('applied_promo_id') is not None:
                promo_fee_rate = float(d['applied_fee_rate']) if d.get('applied_fee_rate') is not None else promo_fee_rate
            details.append({
                'id': d['id'],
                'gifticon_id': d['gifticon_id'],
                'menu_name': d.get('menu_name'),
                'used_at': used_at_str,
                'amount': int(d['sales_amount'] or 0),
                'fee_amount': int(d['fee_amount'] or 0),
                'settlement_amount': int(d['settlement_amount'] or 0),
                'status': settlement.get('status'),
            })
        total_sales = int(settlement['total_sales_amount'] or 0)
        if promo_fee_rate is not None and base_fee_rate is not None:
            base_fee = int(total_sales * base_fee_rate / 100)
            actual_fee = int(settlement['total_fee_amount'] or 0)
            diff = base_fee - actual_fee
            promo_discount_amount = diff if diff > 0 else None
        return {
            'settlement': {
                'settlement_id': settlement['settlement_id'],
                'store_id': settlement['store_id'],
                'cycle_id': settlement['cycle_id'],
                'period_start': settlement['period_start'].isoformat() if settlement.get('period_start') else None,
                'period_end': settlement['period_end'].isoformat() if settlement.get('period_end') else None,
                'total_sales_amount': total_sales,
                'total_fee_amount': int(settlement['total_fee_amount'] or 0),
                'net_payout_amount': int(settlement['net_payout_amount'] or 0),
                'status': settlement['status'],
                'payout_date': settlement['payout_date'].isoformat() if settlement.get('payout_date') else None,
                'failure_reason': settlement.get('failure_reason'),
                'base_fee_rate': base_fee_rate,
                'promo_fee_rate': promo_fee_rate,
                'promo_discount_amount': promo_discount_amount,
                'supply_amount': supply_amount,
                'vat_amount': vat_amount,
            },
            'details': details,
        }
    finally:
        cursor.close()
        connection.close()


def get_owner_settlement_preview(store_id: int) -> Optional[Dict]:
    """현재 진행 중인 정산 주기의 미리보기 상세.
    settlement_id가 null인 PENDING 항목의 상세 조회용.
    진행 중인 주기가 없거나 매출이 없으면 None 반환."""
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    try:
        today = datetime.now(tz=KST).date()
        cursor.execute("""
            SELECT cycle_id, period_start_date, period_end_date, payout_date
            FROM settlement_cycles
            WHERE period_start_date <= %s AND period_end_date >= %s
            LIMIT 1
        """, (today, today))
        cycle = cursor.fetchone()
        if not cycle:
            return None

        cycle_id = cycle['cycle_id']
        period_start = cycle['period_start_date']
        period_end = cycle['period_end_date']
        payout_date = cycle['payout_date']

        if hasattr(period_start, 'date'):
            period_start = period_start.date()
        if hasattr(period_end, 'date'):
            period_end = period_end.date()

        period_start_str = period_start.isoformat()
        period_end_str = period_end.isoformat()
        payout_date_str = payout_date.isoformat() if payout_date else None

        # 기본 수수료율
        cursor.execute("SELECT base_fee_rate FROM platform_config WHERE config_id = 1")
        config = cursor.fetchone()
        base_fee_rate = float(config['base_fee_rate']) if config else 3.0

        # 프로모션 수수료율
        cursor.execute("""
            SELECT fp.promo_fee_rate
            FROM fee_promotions fp
            JOIN fee_promotion_stores fps ON fp.promo_id = fps.promo_id
            WHERE fps.store_id = %s
              AND fp.is_active = TRUE
              AND fp.start_date <= %s
              AND fp.end_date >= %s
            ORDER BY fp.start_date ASC
            LIMIT 1
        """, (store_id, period_start_str, period_start_str))
        promo = cursor.fetchone()
        applied_fee_rate = float(promo['promo_fee_rate']) if promo else base_fee_rate
        promo_fee_rate = float(promo['promo_fee_rate']) if promo else None

        # 건별 내역 조회: settlement_details에 선생성됐지만 미정산(settlement_id IS NULL)인 건
        cursor.execute("""
            SELECT sd.id AS detail_id, sd.gifticon_id, sd.sales_amount, sd.fee_amount,
                   sd.settlement_amount, sd.base_fee_rate, sd.applied_fee_rate,
                   sd.fee_supply, sd.fee_vat,
                   g.used_at, m.menu_name
            FROM settlement_details sd
            JOIN gifticon g ON sd.gifticon_id = g.id
            LEFT JOIN menu m ON g.menu_id = m.id
            WHERE sd.settlement_id IS NULL
              AND g.store_id = %s
              AND DATE(g.used_at) >= %s
              AND DATE(g.used_at) <= %s
            ORDER BY g.used_at ASC
        """, (store_id, period_start_str, period_end_str))
        rows = cursor.fetchall()

        if not rows:
            return None

        total_sales = 0
        total_fee = 0
        supply = 0
        vat = 0
        details = []
        for r in rows:
            sales = int(r['sales_amount'] or 0)
            fee = int(r['fee_amount'] or 0)
            settlement_amt = int(r['settlement_amount'] or 0)
            total_sales += sales
            total_fee += fee
            supply += int(r['fee_supply'] or 0)
            vat += int(r['fee_vat'] or 0)

            used_at = r.get('used_at')
            if used_at and hasattr(used_at, 'strftime'):
                used_at_str = used_at.strftime('%Y-%m-%d %H:%M')
            else:
                used_at_str = str(used_at) if used_at else None

            details.append({
                'id': r['detail_id'],
                'gifticon_id': r['gifticon_id'],
                'menu_name': r.get('menu_name'),
                'used_at': used_at_str,
                'amount': sales,
                'fee_amount': fee,
                'settlement_amount': settlement_amt,
                'status': 'PENDING',
            })

        net = total_sales - total_fee

        if promo:
            _, _, base_fee_total = calc_fee_supply_and_vat(total_sales, base_fee_rate)
            promo_discount_amount = base_fee_total - total_fee
        else:
            promo_discount_amount = None

        return {
            'settlement': {
                'settlement_id': None,
                'store_id': store_id,
                'cycle_id': cycle_id,
                'period_start': period_start_str,
                'period_end': period_end_str,
                'total_sales_amount': total_sales,
                'total_fee_amount': total_fee,
                'net_payout_amount': net,
                'status': None,
                'payout_date': None,
                'failure_reason': None,
                'base_fee_rate': base_fee_rate,
                'promo_fee_rate': promo_fee_rate,
                'promo_discount_amount': promo_discount_amount,
                'supply_amount': supply,
                'vat_amount': vat,
                'expected_payout_date': payout_date_str,
            },
            'details': details,
        }
    finally:
        cursor.close()
        connection.close()


def update_settlement_status(settlement_id: int, status: str, failure_reason: Optional[str] = None) -> bool:
    """정산 상태 변경. failure_reason은 FAILED 시에만 사용."""
    allowed = {'READY', 'PENDING', 'COMPLETED', 'HOLD', 'FAILED'}
    if status not in allowed:
        raise ValueError(f"Invalid status: {status}")
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            "UPDATE settlement SET status = %s, failure_reason = %s WHERE settlement_id = %s",
            (status, failure_reason if status == 'FAILED' else None, settlement_id)
        )
        connection.commit()
        return cursor.rowcount > 0
    except Exception as e:
        connection.rollback()
        raise e
    finally:
        cursor.close()
        connection.close()


def update_settlement_tax_invoice(settlement_id: int, tax_invoice_issued: bool) -> bool:
    """세금계산서 발행 여부 변경."""
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        if tax_invoice_issued:
            cursor.execute(
                "UPDATE settlement SET tax_invoice_issued = 1, tax_invoice_issued_date = CURDATE() WHERE settlement_id = %s",
                (settlement_id,)
            )
        else:
            cursor.execute(
                "UPDATE settlement SET tax_invoice_issued = 0, tax_invoice_issued_date = NULL WHERE settlement_id = %s",
                (settlement_id,)
            )
        connection.commit()
        return cursor.rowcount > 0
    except Exception as e:
        connection.rollback()
        raise e
    finally:
        cursor.close()
        connection.close()


def get_settlements_by_cycle(cycle_id: int, page: int = 1, limit: int = 10) -> Dict:
    """관리자: 정산 주기별 매장 정산 리스트 (페이지네이션)"""
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)

    try:
        cursor.execute("SELECT COUNT(*) AS cnt FROM settlement WHERE cycle_id = %s", (cycle_id,))
        total = int((cursor.fetchone() or {}).get('cnt') or 0)
        offset = (page - 1) * limit

        cursor.execute("""
            SELECT
                s.settlement_id,
                s.store_id,
                st.store_name,
                s.cycle_id,
                s.period_start,
                s.period_end,
                s.total_sales_amount,
                s.total_fee_amount,
                s.net_payout_amount,
                s.status,
                s.tax_invoice_issued,
                s.payout_date,
                s.bank_name,
                s.account_number,
                a.name AS account_holder,
                COUNT(sd.id) AS detail_count
            FROM settlement s
            LEFT JOIN store st ON s.store_id = st.id
            LEFT JOIN account a ON s.store_id = a.store_id
            LEFT JOIN settlement_details sd ON s.settlement_id = sd.settlement_id
            WHERE s.cycle_id = %s
            GROUP BY s.settlement_id
            ORDER BY s.store_id
            LIMIT %s OFFSET %s
        """, (cycle_id, limit, offset))

        rows = cursor.fetchall()
        result = []
        for row in rows:
            result.append({
                'settlement_id': row['settlement_id'],
                'store_id': row['store_id'],
                'store_name': row['store_name'] or f"매장({row['store_id']})",
                'cycle_id': row['cycle_id'],
                'period_start': row['period_start'].isoformat() if row['period_start'] else None,
                'period_end': row['period_end'].isoformat() if row['period_end'] else None,
                'total_sales_amount': int(row['total_sales_amount'] or 0),
                'total_fee_amount': int(row['total_fee_amount'] or 0),
                'net_payout_amount': int(row['net_payout_amount'] or 0),
                'status': row['status'],
                'tax_invoice_issued': bool(row.get('tax_invoice_issued')),
                'payout_date': row['payout_date'].isoformat() if row['payout_date'] else None,
                'bank_name': row.get('bank_name'),
                'account_number': row.get('account_number'),
                'account_holder': row.get('account_holder'),
                'detail_count': int(row.get('detail_count') or 0),
            })
        import math
        return {
            'settlements': result,
            'pagination': {
                'total': total,
                'page': page,
                'limit': limit,
                'total_pages': math.ceil(total / limit) if total else 1,
            },
        }
    finally:
        cursor.close()
        connection.close()


def get_settlement_detail_for_admin(settlement_id: int, detail_page: int = 1, detail_limit: int = 10) -> Dict:
    """관리자: 정산 상세 (헤더 + 건별 내역, 사용일 포함)"""
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        cursor.execute("""
            SELECT
                s.settlement_id,
                s.store_id,
                st.store_name,
                s.cycle_id,
                s.period_start,
                s.period_end,
                s.total_sales_amount,
                s.total_fee_amount,
                s.net_payout_amount,
                s.status,
                s.failure_reason,
                s.tax_invoice_issued,
                s.payout_date,
                s.bank_name,
                a.bank AS account_bank,
                s.account_number,
                a.name AS account_holder
            FROM settlement s
            LEFT JOIN store st ON s.store_id = st.id
            LEFT JOIN account a ON s.store_id = a.store_id
            WHERE s.settlement_id = %s
        """, (settlement_id,))
        settlement = cursor.fetchone()
        if not settlement:
            return None

        cursor.execute("SELECT COUNT(*) AS cnt FROM settlement_details WHERE settlement_id = %s", (settlement_id,))
        detail_total = int((cursor.fetchone() or {}).get('cnt') or 0)
        detail_offset = (detail_page - 1) * detail_limit

        cursor.execute("""
            SELECT
                sd.id,
                sd.gifticon_id,
                g.used_at,
                m.menu_name,
                sd.sales_amount,
                sd.fee_amount,
                sd.settlement_amount,
                sd.base_fee_rate,
                sd.applied_fee_rate,
                sd.fee_supply,
                sd.fee_vat
            FROM settlement_details sd
            JOIN gifticon g ON sd.gifticon_id = g.id
            LEFT JOIN menu m ON g.menu_id = m.id
            WHERE sd.settlement_id = %s
            ORDER BY sd.id
            LIMIT %s OFFSET %s
        """, (settlement_id, detail_limit, detail_offset))
        details = cursor.fetchall()

        header = {
            'settlement_id': settlement['settlement_id'],
            'store_id': settlement['store_id'],
            'store_name': settlement['store_name'] or f"매장({settlement['store_id']})",
            'cycle_id': settlement['cycle_id'],
            'period_start': settlement['period_start'].isoformat() if settlement['period_start'] else None,
            'period_end': settlement['period_end'].isoformat() if settlement['period_end'] else None,
            'total_sales_amount': int(settlement['total_sales_amount'] or 0),
            'total_fee_amount': int(settlement['total_fee_amount'] or 0),
            'net_payout_amount': int(settlement['net_payout_amount'] or 0),
            'status': settlement['status'],
            'failure_reason': settlement.get('failure_reason'),
            'tax_invoice_issued': bool(settlement.get('tax_invoice_issued')),
            'payout_date': settlement['payout_date'].isoformat() if settlement.get('payout_date') else None,
            'bank_name': settlement.get('bank_name') or settlement.get('account_bank'),
            'account_number': settlement.get('account_number'),
            'account_holder': settlement.get('account_holder'),
        }
        items = []
        for i, d in enumerate(details, 1):
            used_at = d.get('used_at')
            used_at_str = used_at.strftime('%Y-%m-%d %H:%M') if used_at and hasattr(used_at, 'strftime') else (str(used_at) if used_at else '-')
            sales = int(d.get('sales_amount') or 0)
            fee = int(d.get('fee_amount') or 0)
            items.append({
                'index': i,
                'id': d.get('id'),
                'gifticon_id': d.get('gifticon_id'),
                'menu_name': d.get('menu_name') or '-',
                'used_at': used_at_str,
                'sales_amount': sales,
                'fee_amount': fee,
                'settlement_amount': int(d.get('settlement_amount') or 0),
                'base_fee_rate': float(d['base_fee_rate']) if d.get('base_fee_rate') is not None else None,
                'applied_fee_rate': float(d['applied_fee_rate']) if d.get('applied_fee_rate') is not None else None,
                'fee_supply': int(d.get('fee_supply') or 0),
                'fee_vat': int(d.get('fee_vat') or 0),
            })
        import math as _math
        return {
            'settlement': header,
            'details': items,
            'detail_pagination': {
                'total': detail_total,
                'page': detail_page,
                'limit': detail_limit,
                'total_pages': _math.ceil(detail_total / detail_limit) if detail_total else 1,
            },
        }
    finally:
        cursor.close()
        connection.close()
