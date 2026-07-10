"""
Statistics CRUD 로직
"""
import math
import pymysql
from typing import List, Dict, Optional
from datetime import date, datetime

from db.session import get_db_connection, close_db_connection
from crud import promotion as promotion_crud


# ── 대시보드 API CRUD (GNB-164 / GNB-165 / GNB-166) ──────────────────────────

def get_dashboard_summary() -> Dict:
    """실시간 요약: 발행잔액 / 이번 정산주기 예정 / 누적 지표

    집계 기준:
    - issued_balance: gifticon 중 UNUSED/PENDING/EXPIRED 상태(미사용) 기프티콘의 menu.price 합계
    - current_cycle: settlement_details.settlement_id IS NULL 건 합계 (현재 진행 중인 주기)
    - cumulative: stats_daily_platform 전체 SUM
    """
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    try:
        # 발행잔액: 미사용(UNUSED/PENDING/EXPIRED) 기프티콘 menu.price 합계, 환불/취소 제외
        cursor.execute("""
            SELECT COALESCE(SUM(m.price), 0) AS issued_balance
            FROM gifticon g
            JOIN menu m ON g.menu_id = m.id
            WHERE g.status IN ('UNUSED', 'PENDING', 'EXPIRED')
        """)
        issued_balance = int(cursor.fetchone()['issued_balance'] or 0)

        # 현재 진행 중인 정산 주기 조회
        cursor.execute("""
            SELECT cycle_id, period_start_date, period_end_date, payout_date
            FROM settlement_cycles
            WHERE status = 'OPEN'
            ORDER BY period_start_date DESC
            LIMIT 1
        """)
        cycle_row = cursor.fetchone()

        current_cycle = None
        if cycle_row:
            cycle_id = cycle_row['cycle_id']
            period_start = cycle_row['period_start_date']
            period_end = cycle_row['period_end_date']
            payout_date = cycle_row['payout_date']

            # 이번 주기 미연결 settlement_details 집계 (정산 예정)
            cursor.execute("""
                SELECT
                    COUNT(DISTINCT g.store_id) AS expected_store_count,
                    COALESCE(SUM(sd.sales_amount), 0) AS expected_settlement_amount
                FROM settlement_details sd
                JOIN gifticon g ON sd.gifticon_id = g.id
                WHERE sd.settlement_id IS NULL
                  AND g.used_at >= %s
                  AND g.used_at < DATE_ADD(%s, INTERVAL 1 DAY)
            """, (period_start, period_end))
            cycle_stats = cursor.fetchone()

            # 기본 수수료율로 예상 수수료 계산
            cursor.execute("SELECT base_fee_rate FROM platform_config ORDER BY config_id DESC LIMIT 1")
            fee_row = cursor.fetchone()
            base_fee_rate = float(fee_row['base_fee_rate']) if fee_row else 0.0
            expected_amount = int(cycle_stats['expected_settlement_amount'] or 0)
            expected_fee = math.floor(expected_amount * base_fee_rate / 100)

            current_cycle = {
                'cycle_id': cycle_id,
                'period_start': period_start.isoformat() if period_start else None,
                'period_end': period_end.isoformat() if period_end else None,
                'payout_date': payout_date.isoformat() if payout_date else None,
                'expected_settlement_amount': expected_amount,
                'expected_store_count': int(cycle_stats['expected_store_count'] or 0),
                'expected_platform_fee': expected_fee,
            }

        # 누적 지표: stats_daily_platform 전체 SUM
        cursor.execute("""
            SELECT
                COALESCE(SUM(total_used_count), 0) AS cumulative_used_count,
                COALESCE(SUM(total_sales_amount), 0) AS cumulative_used_amount
            FROM stats_daily_platform
        """)
        cum = cursor.fetchone()

        return {
            'issued_balance': issued_balance,
            'current_cycle': current_cycle,
            'cumulative': {
                'used_gifticon_count': int(cum['cumulative_used_count'] or 0),
                'used_gifticon_amount': int(cum['cumulative_used_amount'] or 0),
            },
        }
    finally:
        cursor.close()
        close_db_connection(connection)


def get_dashboard_stats(period: str, page: int = 1, size: int = 30) -> Dict:
    """기간별 운영 통계: stats_daily_platform을 period 단위로 GROUP BY 집계

    period: daily | weekly | monthly | yearly | all
    - daily/weekly/monthly: 최신순 30개 페이지네이션, 전체 합계 행 별도 반환
    - yearly/all: 페이지네이션 없음

    GNB-169:
    - weekly 라벨: 주 시작~종료 범위 표시 (예: 2026-01-01~2026-01-07)
    - total_row: 전 기간 합계 항상 포함
    - 수수료: PG 수수료 차감 후 순수수료 (배치 집계값 사용)
    """
    VALID_PERIODS = ('daily', 'weekly', 'monthly', 'yearly', 'all')
    if period not in VALID_PERIODS:
        raise ValueError(f"period must be one of {VALID_PERIODS}")

    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    try:
        # 전체 합계 행 (항상 계산)
        cursor.execute("""
            SELECT
                SUM(new_store_count)        AS new_store_count,
                SUM(total_issued_count)     AS issued_gifticon_count,
                SUM(total_issued_amount)    AS issued_gifticon_amount,
                SUM(total_used_count)       AS used_gifticon_count,
                SUM(total_sales_amount)     AS used_gifticon_amount,
                SUM(total_payment_amount)   AS total_payment_amount,
                SUM(total_fee_revenue)      AS platform_fee_revenue
            FROM stats_daily_platform
        """)
        tot = cursor.fetchone()
        total_row = {
            'label': '전체',
            'is_total': True,
            'new_store_count': int(tot['new_store_count'] or 0),
            'issued_gifticon_count': int(tot['issued_gifticon_count'] or 0),
            'issued_gifticon_amount': int(tot['issued_gifticon_amount'] or 0),
            'used_gifticon_count': int(tot['used_gifticon_count'] or 0),
            'used_gifticon_amount': int(tot['used_gifticon_amount'] or 0),
            'total_payment_amount': int(tot['total_payment_amount'] or 0),
            'platform_fee_revenue': int(tot['platform_fee_revenue'] or 0),
        }

        if period == 'all':
            return {'period': period, 'series': [total_row], 'total_row': total_row,
                    'total_count': 1, 'page': 1, 'size': 1, 'total_pages': 1}

        if period == 'daily':
            group_expr = "DATE_FORMAT(target_date, '%Y-%m-%d')"
            label_expr = group_expr
        elif period == 'weekly':
            # 주 시작(월요일) 기준 label: "YYYY-MM-DD~YYYY-MM-DD"
            group_expr = "DATE_FORMAT(DATE_SUB(target_date, INTERVAL WEEKDAY(target_date) DAY), '%Y-%m-%d')"
            label_expr = (
                "CONCAT("
                "DATE_FORMAT(DATE_SUB(target_date, INTERVAL WEEKDAY(target_date) DAY), '%Y-%m-%d'),"
                "'~',"
                "DATE_FORMAT(DATE_ADD(DATE_SUB(target_date, INTERVAL WEEKDAY(target_date) DAY), INTERVAL 6 DAY), '%Y-%m-%d')"
                ")"
            )
        elif period == 'monthly':
            group_expr = "DATE_FORMAT(target_date, '%Y-%m')"
            label_expr = group_expr
        else:  # yearly
            group_expr = "DATE_FORMAT(target_date, '%Y')"
            label_expr = group_expr

        # pymysql replaces % in SQL when params are given; escape % in MySQL format strings for param queries
        def _esc(s: str) -> str:
            return s.replace('%', '%%')

        if period in ('daily', 'weekly', 'monthly'):
            # 전체 건수 조회 (no params → plain %, MySQL receives %Y etc. correctly)
            cursor.execute(f"""
                SELECT COUNT(DISTINCT {group_expr}) AS cnt
                FROM stats_daily_platform
            """)
            total_count = int(cursor.fetchone()['cnt'] or 0)
            total_pages = math.ceil(total_count / size) if total_count else 1
            offset = (page - 1) * size

            cursor.execute(f"""
                SELECT
                    {_esc(label_expr)} AS label,
                    {_esc(group_expr)} AS sort_key,
                    SUM(new_store_count)        AS new_store_count,
                    SUM(total_issued_count)     AS issued_gifticon_count,
                    SUM(total_issued_amount)    AS issued_gifticon_amount,
                    SUM(total_used_count)       AS used_gifticon_count,
                    SUM(total_sales_amount)     AS used_gifticon_amount,
                    SUM(total_payment_amount)   AS total_payment_amount,
                    SUM(total_fee_revenue)      AS platform_fee_revenue
                FROM stats_daily_platform
                GROUP BY sort_key, label
                ORDER BY sort_key DESC
                LIMIT %s OFFSET %s
            """, (size, offset))
        else:  # yearly (no params)
            total_count = None
            total_pages = 1
            cursor.execute(f"""
                SELECT
                    {label_expr} AS label,
                    SUM(new_store_count)        AS new_store_count,
                    SUM(total_issued_count)     AS issued_gifticon_count,
                    SUM(total_issued_amount)    AS issued_gifticon_amount,
                    SUM(total_used_count)       AS used_gifticon_count,
                    SUM(total_sales_amount)     AS used_gifticon_amount,
                    SUM(total_payment_amount)   AS total_payment_amount,
                    SUM(total_fee_revenue)      AS platform_fee_revenue
                FROM stats_daily_platform
                GROUP BY label
                ORDER BY label DESC
            """)

        rows = cursor.fetchall()
        series = [
            {
                'label': r['label'],
                'is_total': False,
                'new_store_count': int(r['new_store_count'] or 0),
                'issued_gifticon_count': int(r['issued_gifticon_count'] or 0),
                'issued_gifticon_amount': int(r['issued_gifticon_amount'] or 0),
                'used_gifticon_count': int(r['used_gifticon_count'] or 0),
                'used_gifticon_amount': int(r['used_gifticon_amount'] or 0),
                'total_payment_amount': int(r['total_payment_amount'] or 0),
                'platform_fee_revenue': int(r['platform_fee_revenue'] or 0),
            }
            for r in rows
        ]

        return {
            'period': period,
            'series': series,
            'total_row': total_row,
            'total_count': total_count,
            'page': page,
            'size': size,
            'total_pages': total_pages,
        }
    finally:
        cursor.close()
        close_db_connection(connection)


def get_dashboard_settlement_cycles(page: int = 1, size: int = 10) -> Dict:
    """정산 주기별 플랫폼 매출 이력

    GNB-169: 현재 날짜 이전 주기만 표시 (period_end_date <= today), 10개씩 페이지네이션

    집계 기준:
    - total_settlement_amount: 매장 지급 총액 (net_payout_amount 합계, COMPLETED/PENDING)
    - settled_store_count: 정산 건수 (매장 수, FAILED 제외)
    - platform_fee_amount: 플랫폼 수수료 공급가 합계
    - platform_vat_amount: 플랫폼 부가세 합계
    - unused_amount: 해당 주기 발행 기프티콘 중 미사용(UNUSED/PENDING/EXPIRED) 금액
    """
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    try:
        offset = (page - 1) * size
        today = date.today()

        cursor.execute("""
            SELECT COUNT(DISTINCT sc.cycle_id) AS total
            FROM settlement_cycles sc
            WHERE sc.period_end_date <= %s
        """, (today,))
        total = int(cursor.fetchone()['total'] or 0)

        cursor.execute("""
            SELECT
                sc.cycle_id,
                sc.period_start_date,
                sc.period_end_date,
                sc.payout_date,
                COALESCE(SUM(CASE WHEN s.status IN ('COMPLETED','PENDING') THEN s.net_payout_amount ELSE 0 END), 0)
                    AS total_settlement_amount,
                COUNT(CASE WHEN s.status NOT IN ('FAILED') THEN 1 END)
                    AS settled_store_count,
                COALESCE(SUM(CASE WHEN s.status IN ('COMPLETED','PENDING') THEN s.original_fee_supply ELSE 0 END), 0)
                    AS platform_fee_amount,
                COALESCE(SUM(CASE WHEN s.status IN ('COMPLETED','PENDING') THEN s.original_fee_vat ELSE 0 END), 0)
                    AS platform_vat_amount
            FROM settlement_cycles sc
            LEFT JOIN settlement s ON sc.cycle_id = s.cycle_id
            WHERE sc.period_end_date <= %s
            GROUP BY sc.cycle_id, sc.period_start_date, sc.period_end_date, sc.payout_date
            ORDER BY sc.period_start_date DESC
            LIMIT %s OFFSET %s
        """, (today, size, offset))
        rows = cursor.fetchall()

        items = []
        for r in rows:
            period_start = r['period_start_date']
            period_end = r['period_end_date']

            # 해당 주기 미사용 금액: 기간 내 발행된 기프티콘 중 미사용 상태 menu.price 합계
            cursor.execute("""
                SELECT COALESCE(SUM(m.price), 0) AS unused_amount
                FROM gifticon g
                JOIN menu m ON g.menu_id = m.id
                WHERE g.created_at >= %s
                  AND g.created_at < DATE_ADD(%s, INTERVAL 1 DAY)
                  AND g.status IN ('UNUSED', 'PENDING', 'EXPIRED')
            """, (period_start, period_end))
            unused = int(cursor.fetchone()['unused_amount'] or 0)

            items.append({
                'cycle_id': r['cycle_id'],
                'period_start': period_start.isoformat() if period_start else None,
                'period_end': period_end.isoformat() if period_end else None,
                'payout_date': r['payout_date'].isoformat() if r['payout_date'] else None,
                'total_settlement_amount': int(r['total_settlement_amount'] or 0),
                'settled_store_count': int(r['settled_store_count'] or 0),
                'platform_fee_amount': int(r['platform_fee_amount'] or 0),
                'platform_vat_amount': int(r['platform_vat_amount'] or 0),
                'unused_amount': unused,
            })

        return {
            'items': items,
            'total': total,
            'page': page,
            'size': size,
            'total_pages': math.ceil(total / size) if total else 0,
        }
    finally:
        cursor.close()
        close_db_connection(connection)


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
