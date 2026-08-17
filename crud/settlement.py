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


from core.s3_config import S3_CLIENT, BUCKET_NAME
from models.settlement import Account

s3 = S3_CLIENT
bucket_name = BUCKET_NAME


def _generate_presigned_url(key: Optional[str], expires: int = 3600) -> Optional[str]:
    if not key:
        return None
    try:
        return s3.generate_presigned_url('get_object',
            Params={'Bucket': bucket_name, 'Key': key}, ExpiresIn=expires)
    except Exception:
        return None


def create_account(store_id: int, account: Account) -> bool:
    """계좌 정보 등록"""
    connection = get_db_connection()
    cursor = connection.cursor()
    
    try:
        cursor.execute(
            """INSERT INTO account (store_id, name, code, bank, account)
               VALUES (%s, %s, %s, %s, %s)
               ON DUPLICATE KEY UPDATE name=%s, code=%s, bank=%s, account=%s""",
            (
                store_id, account.name, account.code, account.bank, account.account,
                account.name, account.code, account.bank, account.account,
            )
        )
        connection.commit()
        return True
    except Exception as e:
        connection.rollback()
        raise e
    finally:
        cursor.close()
        close_db_connection(connection)


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
        close_db_connection(connection)



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
        close_db_connection(connection)


def get_settlement_detail(settlement_id: int) -> List[Dict]:
    """정산 상세 내역 조회 (개별 기프티콘 매출만 표시, 수수료는 정산 헤더 참조)"""
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)

    try:
        cursor.execute("""
            SELECT
                COALESCE(g.menu_name_snapshot, m.menu_name) AS name,
                sd.sales_amount AS price,
                g.used_at AS used_time
            FROM settlement_details sd
            JOIN gifticon g ON sd.gifticon_id = g.id
            LEFT JOIN menu m ON g.menu_id = m.id
            WHERE sd.settlement_id = %s
            ORDER BY g.used_at DESC
        """, (settlement_id,))

        results = cursor.fetchall()
        details = []

        for result in results:
            price = result['price'] or 0
            details.append({
                'menu_name': result['name'],
                'price': price,
                'used_time': result['used_time'].isoformat() if result.get('used_time') else None,
            })

        return details
    finally:
        cursor.close()
        close_db_connection(connection)


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
        close_db_connection(connection)


def get_store_statistics(store_id: int) -> Dict:
    """매장 통계 데이터 조회 (발행 수, 사용 수, 미사용 수)"""
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        # 발행/미사용은 발행처(store_id) 기준, 사용은 사용처(used_store_id) 기준.
        # 금액권은 전용 가상매장에서 발행되므로 발행 수에는 잡히지 않고,
        # 실제 사용된 매장의 사용 수에만 반영된다.

        # 전체 발행 수 (정상 결제 완료된 것만)
        cursor.execute("SELECT COUNT(*) as total FROM gifticon WHERE store_id = %s AND status IN ('UNUSED', 'USED')", (store_id,))
        total_issued = cursor.fetchone()['total'] or 0

        # 사용 수 (이 매장에서 사용처리된 건. 메뉴권 중 used_store_id가 없는 과거 데이터는 발행처로 폴백)
        cursor.execute(
            "SELECT COUNT(*) as total FROM gifticon WHERE COALESCE(used_store_id, store_id) = %s AND status = 'USED'",
            (store_id,)
        )
        total_used = cursor.fetchone()['total'] or 0

        # 미사용 수 (아직 사용처가 정해지지 않았으므로 발행처 기준)
        cursor.execute("SELECT COUNT(*) as total FROM gifticon WHERE store_id = %s AND status = 'UNUSED'", (store_id,))
        total_unused = cursor.fetchone()['total'] or 0
        
        return {
            'total_issued': total_issued,
            'total_used': total_used,
            'total_unused': total_unused
        }
    finally:
        cursor.close()
        close_db_connection(connection)


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
        close_db_connection(connection)


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
                continue  # 진행 중 cycle은 settlement 레코드 존재 여부와 무관하게 항상 실시간 preview로 대체

            if period_end < cutoff:
                continue
            if period_end > today and not (period_start <= today <= period_end):
                continue
            cursor.execute("""
                SELECT s.settlement_id, s.cycle_id, s.period_start, s.period_end,
                    s.total_sales_amount, s.total_fee_amount, s.net_payout_amount,
                    s.base_fee_rate, s.applied_promo_id, s.applied_fee_rate,
                    s.original_fee_supply, s.original_fee_vat, s.original_fee_amount,
                    s.promo_fee_supply, s.promo_fee_vat, s.promo_fee_amount,
                    s.status, s.payout_date, s.failure_reason,
                    sc.payout_date AS expected_payout_date,
                    fp.title AS applied_promo_title
                FROM settlement s
                LEFT JOIN settlement_cycles sc ON s.cycle_id = sc.cycle_id
                LEFT JOIN fee_promotions fp ON s.applied_promo_id = fp.promo_id
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
                'base_fee_rate': float(row['base_fee_rate']) if row.get('base_fee_rate') is not None else None,
                'applied_fee_rate': float(row['applied_fee_rate']) if row.get('applied_fee_rate') is not None else None,
                'applied_promo_id': row.get('applied_promo_id'),
                'applied_promo_title': row.get('applied_promo_title'),
                'original_fee_supply': int(row['original_fee_supply']) if row.get('original_fee_supply') is not None else None,
                'original_fee_vat': int(row['original_fee_vat']) if row.get('original_fee_vat') is not None else None,
                'original_fee_amount': int(row['original_fee_amount']) if row.get('original_fee_amount') is not None else None,
                'promo_fee_supply': int(row['promo_fee_supply']) if row.get('promo_fee_supply') is not None else None,
                'promo_fee_vat': int(row['promo_fee_vat']) if row.get('promo_fee_vat') is not None else None,
                'promo_fee_amount': int(row['promo_fee_amount']) if row.get('promo_fee_amount') is not None else None,
                'total_fee_amount': int(row['total_fee_amount'] or 0),
                'net_payout_amount': int(row['net_payout_amount'] or 0),
                'expected_amount': float(row['net_payout_amount'] or 0),
                'fee_amount': float(row['total_fee_amount'] or 0),
                'expected_payout_date': pe,
                'status': row['status'],
                'payout_date': row['payout_date'].isoformat() if row.get('payout_date') else None,
                'failure_reason': row.get('failure_reason'),
            })

        current_cycle_already_in_result = current_cycle is not None and any(
            r.get('cycle_id') == current_cycle['cycle_id'] for r in result
        )
        if current_cycle and not current_cycle_already_in_result:
            preview = _build_preview_summary(cursor, store_id, current_cycle)
            if preview:
                result.insert(0, preview)

        result.sort(key=lambda x: (x.get('period_start') or ''), reverse=True)
        return result
    finally:
        cursor.close()
        close_db_connection(connection)


def get_owner_settlement_detail(settlement_id: int) -> Optional[Dict]:
    """사장님 정산 상세: 헤더(settlement) + 건별 내역(details). 없으면 None. (GNB-142)"""
    sid = int(settlement_id)
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    try:
        cursor.execute("""
            SELECT s.settlement_id, s.store_id, s.cycle_id, s.period_start, s.period_end,
                s.total_sales_amount, s.total_fee_amount, s.net_payout_amount,
                s.base_fee_rate, s.applied_promo_id, s.applied_fee_rate,
                s.original_fee_supply, s.original_fee_vat, s.original_fee_amount,
                s.promo_fee_supply, s.promo_fee_vat, s.promo_fee_amount,
                s.status, s.payout_date, s.failure_reason,
                fp.title AS applied_promo_title
            FROM settlement s
            LEFT JOIN fee_promotions fp ON s.applied_promo_id = fp.promo_id
            WHERE s.settlement_id = %s
        """, (sid,))
        settlement = cursor.fetchone()
        if not settlement:
            return None

        cursor.execute("""
            SELECT sd.id, sd.gifticon_id, sd.sales_amount, sd.fee_amount, sd.settlement_amount,
                g.used_at, COALESCE(g.menu_name_snapshot, m.menu_name) AS menu_name
            FROM settlement_details sd
            JOIN gifticon g ON sd.gifticon_id = g.id
            LEFT JOIN menu m ON g.menu_id = m.id
            WHERE sd.settlement_id = %s
            ORDER BY sd.id
        """, (sid,))
        rows = cursor.fetchall()
        details = []
        for d in rows:
            used_at = d.get('used_at')
            if used_at and hasattr(used_at, 'strftime'):
                used_at_str = used_at.strftime('%Y-%m-%d %H:%M')
            else:
                used_at_str = str(used_at) if used_at else None
            details.append({
                'id': d['id'],
                'gifticon_id': d['gifticon_id'],
                'menu_name': d.get('menu_name'),
                'used_at': used_at_str,
                'amount': int(d['sales_amount'] or 0),
                'fee_amount': int(d['fee_amount'] or 0),
                'settlement_amount': int(d['settlement_amount'] or 0),
            })

        return {
            'settlement': {
                'settlement_id': settlement['settlement_id'],
                'store_id': settlement['store_id'],
                'cycle_id': settlement['cycle_id'],
                'period_start': settlement['period_start'].isoformat() if settlement.get('period_start') else None,
                'period_end': settlement['period_end'].isoformat() if settlement.get('period_end') else None,
                'total_sales_amount': int(settlement['total_sales_amount'] or 0),
                'base_fee_rate': float(settlement['base_fee_rate']) if settlement.get('base_fee_rate') is not None else None,
                'applied_fee_rate': float(settlement['applied_fee_rate']) if settlement.get('applied_fee_rate') is not None else None,
                'applied_promo_id': settlement.get('applied_promo_id'),
                'applied_promo_title': settlement.get('applied_promo_title'),
                'original_fee_supply': int(settlement['original_fee_supply']) if settlement.get('original_fee_supply') is not None else None,
                'original_fee_vat': int(settlement['original_fee_vat']) if settlement.get('original_fee_vat') is not None else None,
                'original_fee_amount': int(settlement['original_fee_amount']) if settlement.get('original_fee_amount') is not None else None,
                'promo_fee_supply': int(settlement['promo_fee_supply']) if settlement.get('promo_fee_supply') is not None else None,
                'promo_fee_vat': int(settlement['promo_fee_vat']) if settlement.get('promo_fee_vat') is not None else None,
                'promo_fee_amount': int(settlement['promo_fee_amount']) if settlement.get('promo_fee_amount') is not None else None,
                'total_fee_amount': int(settlement['total_fee_amount'] or 0),
                'net_payout_amount': int(settlement['net_payout_amount'] or 0),
                'status': settlement['status'],
                'payout_date': settlement['payout_date'].isoformat() if settlement.get('payout_date') else None,
                'failure_reason': settlement.get('failure_reason'),
            },
            'details': details,
        }
    finally:
        cursor.close()
        close_db_connection(connection)


def _fetch_current_cycle(cursor) -> Optional[Dict]:
    today = datetime.now(tz=KST).date()
    cursor.execute("""
        SELECT cycle_id, period_start_date, period_end_date, payout_date
        FROM settlement_cycles
        WHERE period_start_date <= %s AND period_end_date >= %s
        LIMIT 1
    """, (today, today))
    return cursor.fetchone()


def _compute_preview_totals(cursor, store_id: int, cycle: Dict) -> Optional[Dict]:
    """진행중 주기의 총 매출을 집계하고 payout_date 기준 프로모션 적용해 예상 정산액 계산."""
    from crud import promotion as promotion_crud

    period_start = cycle['period_start_date']
    period_end = cycle['period_end_date']
    payout_date = cycle['payout_date']

    if hasattr(period_start, 'date') and callable(period_start.date):
        period_start = period_start.date()
    if hasattr(period_end, 'date') and callable(period_end.date):
        period_end = period_end.date()

    period_start_str = period_start.isoformat()
    period_end_str = period_end.isoformat()

    cursor.execute("""
        SELECT sd.id AS detail_id, sd.gifticon_id, sd.sales_amount,
               sd.fee_supply, sd.fee_vat, sd.fee_amount, sd.settlement_amount,
               g.used_at, COALESCE(g.menu_name_snapshot, m.menu_name) AS menu_name
        FROM settlement_details sd
        JOIN gifticon g ON sd.gifticon_id = g.id
        LEFT JOIN menu m ON g.menu_id = m.id
        WHERE sd.settlement_id IS NULL
          AND COALESCE(g.used_store_id, g.store_id) = %s
          AND g.used_at >= %s
          AND g.used_at < DATE_ADD(%s, INTERVAL 1 DAY)
        ORDER BY g.used_at ASC
    """, (store_id, period_start_str, period_end_str))
    rows = cursor.fetchall()
    if not rows:
        return None

    total_sales = sum(int(r['sales_amount'] or 0) for r in rows)

    fee_info = promotion_crud.get_fee_info_for_settlement(store_id, payout_date)
    base_fee_rate = fee_info['base_fee_rate']
    applied_fee_rate = fee_info['applied_fee_rate']
    applied_promo_id = fee_info['applied_promo_id']
    applied_promo_title = fee_info['applied_promo_title']

    # 건별로 저장된 기본 수수료(fee_supply/fee_vat)를 합산해 상세내역과 정합성을 맞춘다.
    original_supply = sum(int(r['fee_supply'] or 0) for r in rows)
    original_vat = sum(int(r['fee_vat'] or 0) for r in rows)
    original_fee = original_supply + original_vat

    if applied_promo_id is not None:
        promo_supply = math.floor(total_sales * applied_fee_rate / 100)
        promo_vat = round(promo_supply * 0.1)
        promo_fee = promo_supply + promo_vat
        total_fee = promo_fee
    else:
        promo_supply = promo_vat = promo_fee = None
        total_fee = original_fee

    net = total_sales - total_fee

    return {
        'rows': rows,
        'period_start_str': period_start_str,
        'period_end_str': period_end_str,
        'payout_date_str': payout_date.isoformat() if payout_date and hasattr(payout_date, 'isoformat') else (str(payout_date) if payout_date else None),
        'total_sales': total_sales,
        'total_fee': total_fee,
        'net': net,
        'base_fee_rate': base_fee_rate,
        'applied_fee_rate': applied_fee_rate,
        'applied_promo_id': applied_promo_id,
        'applied_promo_title': applied_promo_title,
        'original_fee_supply': original_supply,
        'original_fee_vat': original_vat,
        'original_fee_amount': original_fee,
        'promo_fee_supply': promo_supply,
        'promo_fee_vat': promo_vat,
        'promo_fee_amount': promo_fee,
    }


def _build_preview_summary(cursor, store_id: int, cycle: Dict) -> Optional[Dict]:
    """정산 목록에 넣을 요약 preview 항목 (list API용)"""
    p = _compute_preview_totals(cursor, store_id, cycle)
    if not p:
        return None
    return {
        'settlement_id': None,
        'cycle_id': cycle['cycle_id'],
        'period_start': p['period_start_str'],
        'period_end': p['period_end_str'],
        'total_sales_amount': p['total_sales'],
        'base_fee_rate': p['base_fee_rate'],
        'applied_fee_rate': p['applied_fee_rate'],
        'applied_promo_id': p['applied_promo_id'],
        'applied_promo_title': p['applied_promo_title'],
        'original_fee_supply': p['original_fee_supply'],
        'original_fee_vat': p['original_fee_vat'],
        'original_fee_amount': p['original_fee_amount'],
        'promo_fee_supply': p['promo_fee_supply'],
        'promo_fee_vat': p['promo_fee_vat'],
        'promo_fee_amount': p['promo_fee_amount'],
        'total_fee_amount': p['total_fee'],
        'net_payout_amount': p['net'],
        'expected_amount': float(p['net']),
        'fee_amount': float(p['total_fee']),
        'expected_payout_date': p['payout_date_str'],
        'status': 'PENDING',
        'payout_date': None,
        'failure_reason': None,
    }


def get_owner_settlement_preview(store_id: int) -> Optional[Dict]:
    """현재 진행 중인 정산 주기의 미리보기 상세 (GNB-142).
    payout_date 기준 활성 프로모션 조회 후 총액 기반 예상 수수료 계산.
    진행 중인 주기가 없거나 매출이 없으면 None 반환."""
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    try:
        cycle = _fetch_current_cycle(cursor)
        if not cycle:
            return None

        p = _compute_preview_totals(cursor, store_id, cycle)
        if not p:
            return None

        details = []
        for r in p['rows']:
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
                'amount': int(r['sales_amount'] or 0),
                'fee_amount': int(r['fee_amount'] or 0),
                'settlement_amount': int(r['settlement_amount'] or 0),
            })

        return {
            'settlement': {
                'settlement_id': None,
                'store_id': store_id,
                'cycle_id': cycle['cycle_id'],
                'period_start': p['period_start_str'],
                'period_end': p['period_end_str'],
                'total_sales_amount': p['total_sales'],
                'base_fee_rate': p['base_fee_rate'],
                'applied_fee_rate': p['applied_fee_rate'],
                'applied_promo_id': p['applied_promo_id'],
                'applied_promo_title': p['applied_promo_title'],
                'original_fee_supply': p['original_fee_supply'],
                'original_fee_vat': p['original_fee_vat'],
                'original_fee_amount': p['original_fee_amount'],
                'promo_fee_supply': p['promo_fee_supply'],
                'promo_fee_vat': p['promo_fee_vat'],
                'promo_fee_amount': p['promo_fee_amount'],
                'total_fee_amount': p['total_fee'],
                'net_payout_amount': p['net'],
                'status': 'PENDING',
                'payout_date': None,
                'expected_payout_date': p['payout_date_str'],
                'failure_reason': None,
            },
            'details': details,
        }
    finally:
        cursor.close()
        close_db_connection(connection)


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
        close_db_connection(connection)


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
        close_db_connection(connection)


def get_settlement_cycle_preview(cycle_id: int) -> Optional[Dict]:
    """관리자: 정산 주기 미리보기 (배치 생성 전 예상 매장별 정산 리스트).

    settlement_id가 없는(아직 정산되지 않은) settlement_details를 매장별로 집계해
    프로모션 적용 후 예상 순지급액을 계산한다. 이미 배치가 실행되어 해당 매장의
    settlement이 생성된 경우 그 매장은 집계에서 자연히 제외된다(sd.settlement_id IS NULL 조건).
    이미 완료된 주기의 매장별 정산 리스트(get_settlements_by_cycle)와 동일한 필드 구성으로
    반환해 관리자 화면에서 진행 중/완료 주기를 같은 테이블로 보여줄 수 있게 한다.
    cycle_id가 없으면 None 반환.
    """
    from crud import promotion as promotion_crud
    from crud.stats import _calc_fee

    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    try:
        cursor.execute("""
            SELECT cycle_id, period_start_date, period_end_date, payout_date, status
            FROM settlement_cycles
            WHERE cycle_id = %s
        """, (cycle_id,))
        cycle = cursor.fetchone()
        if not cycle:
            return None

        period_start = cycle['period_start_date']
        period_end = cycle['period_end_date']
        payout_date = cycle['payout_date']

        cursor.execute("""
            SELECT
                COALESCE(g.used_store_id, g.store_id) AS store_id,
                st.store_name,
                SUM(sd.sales_amount) AS total_sales,
                COUNT(*) AS detail_count
            FROM settlement_details sd
            JOIN gifticon g ON sd.gifticon_id = g.id
            LEFT JOIN store st ON COALESCE(g.used_store_id, g.store_id) = st.id
            WHERE sd.settlement_id IS NULL
              AND g.used_at >= %s
              AND g.used_at < DATE_ADD(%s, INTERVAL 1 DAY)
            GROUP BY COALESCE(g.used_store_id, g.store_id), st.store_name
            ORDER BY COALESCE(g.used_store_id, g.store_id)
        """, (period_start, period_end))
        store_rows = cursor.fetchall()

        stores = []
        total_expected_amount = 0
        expected_settlement_count = 0
        for row in store_rows:
            store_id = row['store_id']
            total_sales = int(row['total_sales'] or 0)
            detail_count = int(row['detail_count'] or 0)
            expected_settlement_count += detail_count

            fee_info = promotion_crud.get_fee_info_for_settlement(store_id, payout_date)
            applied_fee_rate = fee_info['applied_fee_rate']
            _, _, fee_amount = _calc_fee(total_sales, applied_fee_rate)
            net_payout_amount = total_sales - fee_amount
            total_expected_amount += net_payout_amount

            stores.append({
                'store_id': store_id,
                'store_name': row['store_name'] or f"매장({store_id})",
                'total_sales_amount': total_sales,
                'total_fee_amount': fee_amount,
                'net_payout_amount': net_payout_amount,
                'detail_count': detail_count,
            })

        return {
            'cycle_id': cycle_id,
            'period_start_date': period_start.isoformat() if period_start else None,
            'period_end_date': period_end.isoformat() if period_end else None,
            'payout_date': payout_date.isoformat() if payout_date else None,
            'status': cycle['status'],
            'expected_store_count': len(stores),
            'expected_settlement_count': expected_settlement_count,
            'total_expected_amount': total_expected_amount,
            'stores': stores,
        }
    finally:
        cursor.close()
        close_db_connection(connection)


def get_settlements_by_cycle(cycle_id: int, page: int = 1, limit: int = 10) -> Dict:
    """관리자: 정산 주기별 매장 정산 리스트 (페이지네이션)"""
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)

    try:
        cursor.execute("SELECT COUNT(*) AS cnt FROM settlement WHERE cycle_id = %s", (cycle_id,))
        total = int((cursor.fetchone() or {}).get('cnt') or 0)

        cursor.execute(
            "SELECT COUNT(*) AS cnt FROM settlement WHERE cycle_id = %s AND status = 'FAILED'",
            (cycle_id,)
        )
        failed_count = int((cursor.fetchone() or {}).get('cnt') or 0)

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
                (SELECT COUNT(*) FROM settlement_details sd WHERE sd.settlement_id = s.settlement_id) AS detail_count
            FROM settlement s
            LEFT JOIN store st ON s.store_id = st.id
            LEFT JOIN account a ON s.store_id = a.store_id
            WHERE s.cycle_id = %s
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
            'failed_count': failed_count,
            'pagination': {
                'total': total,
                'page': page,
                'limit': limit,
                'total_pages': math.ceil(total / limit) if total else 1,
            },
        }
    finally:
        cursor.close()
        close_db_connection(connection)


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
                st.store_logo_key,
                st.bankbook_key,
                s.cycle_id,
                s.period_start,
                s.period_end,
                s.total_sales_amount,
                s.total_fee_amount,
                s.net_payout_amount,
                s.base_fee_rate,
                s.applied_promo_id,
                s.applied_fee_rate,
                s.original_fee_supply,
                s.original_fee_vat,
                s.original_fee_amount,
                s.promo_fee_supply,
                s.promo_fee_vat,
                s.promo_fee_amount,
                s.status,
                s.failure_reason,
                s.tax_invoice_issued,
                s.payout_date,
                s.bank_name,
                a.bank AS account_bank,
                s.account_number,
                a.name AS account_holder,
                fp.title AS applied_promo_title
            FROM settlement s
            LEFT JOIN store st ON s.store_id = st.id
            LEFT JOIN account a ON s.store_id = a.store_id
            LEFT JOIN fee_promotions fp ON s.applied_promo_id = fp.promo_id
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
                COALESCE(g.menu_name_snapshot, m.menu_name) AS menu_name,
                sd.sales_amount,
                sd.fee_rate,
                sd.fee_supply,
                sd.fee_vat,
                sd.fee_amount,
                sd.settlement_amount
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
            'base_fee_rate': float(settlement['base_fee_rate']) if settlement.get('base_fee_rate') is not None else None,
            'applied_fee_rate': float(settlement['applied_fee_rate']) if settlement.get('applied_fee_rate') is not None else None,
            'applied_promo_id': settlement.get('applied_promo_id'),
            'applied_promo_title': settlement.get('applied_promo_title'),
            'original_fee_supply': int(settlement['original_fee_supply']) if settlement.get('original_fee_supply') is not None else None,
            'original_fee_vat': int(settlement['original_fee_vat']) if settlement.get('original_fee_vat') is not None else None,
            'original_fee_amount': int(settlement['original_fee_amount']) if settlement.get('original_fee_amount') is not None else None,
            'promo_fee_supply': int(settlement['promo_fee_supply']) if settlement.get('promo_fee_supply') is not None else None,
            'promo_fee_vat': int(settlement['promo_fee_vat']) if settlement.get('promo_fee_vat') is not None else None,
            'promo_fee_amount': int(settlement['promo_fee_amount']) if settlement.get('promo_fee_amount') is not None else None,
            'total_fee_amount': int(settlement['total_fee_amount'] or 0),
            'net_payout_amount': int(settlement['net_payout_amount'] or 0),
            'status': settlement['status'],
            'failure_reason': settlement.get('failure_reason'),
            'tax_invoice_issued': bool(settlement.get('tax_invoice_issued')),
            'payout_date': settlement['payout_date'].isoformat() if settlement.get('payout_date') else None,
            'bank_name': settlement.get('bank_name') or settlement.get('account_bank'),
            'account_number': settlement.get('account_number'),
            'account_holder': settlement.get('account_holder'),
            'store_logo_url': _generate_presigned_url(settlement.get('store_logo_key')),
            'bankbook_url': _generate_presigned_url(settlement.get('bankbook_key')),
        }
        applied_promo_id = settlement.get('applied_promo_id')
        header_applied_fee_rate = float(settlement['applied_fee_rate']) if settlement.get('applied_fee_rate') is not None else None

        items = []
        for i, d in enumerate(details, 1):
            used_at = d.get('used_at')
            used_at_str = used_at.strftime('%Y-%m-%d %H:%M') if used_at and hasattr(used_at, 'strftime') else (str(used_at) if used_at else '-')
            base_fee_rate = float(d['fee_rate']) if d.get('fee_rate') is not None else None
            applied_fee_rate = header_applied_fee_rate if applied_promo_id is not None else base_fee_rate
            items.append({
                'index': i,
                'id': d.get('id'),
                'gifticon_id': d.get('gifticon_id'),
                'menu_name': d.get('menu_name') or '-',
                'used_at': used_at_str,
                'sales_amount': int(d.get('sales_amount') or 0),
                'base_fee_rate': base_fee_rate,
                'applied_fee_rate': applied_fee_rate,
                'fee_supply': int(d['fee_supply']) if d.get('fee_supply') is not None else 0,
                'fee_vat': int(d['fee_vat']) if d.get('fee_vat') is not None else 0,
                'fee_amount': int(d['fee_amount']) if d.get('fee_amount') is not None else 0,
                'settlement_amount': int(d['settlement_amount']) if d.get('settlement_amount') is not None else int(d.get('sales_amount') or 0),
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
        close_db_connection(connection)
