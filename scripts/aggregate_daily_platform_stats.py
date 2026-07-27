#!/usr/bin/env python3
"""
플랫폼 일별 통계 집계 배치 스크립트 (GNB-163 / GNB-169)

집계 기준:
  - new_store_count      : store.created_at 기준 당일 신규 입점 매장 수
  - active_store_count   : 당일 발행 또는 사용이 발생한 매장 DISTINCT 수
  - total_issued_count   : gifticon.created_at 기준, REFUNDED/CANCELED/PENDING 제외
  - total_issued_amount  : 위 기프티콘의 menu.price 합계 (발행 시점 메뉴 가격 기준)
  - total_used_count     : gifticon.used_at 기준 USED 상태, REFUNDED 제외
  - total_sales_amount   : 위 기프티콘의 settlement_details.sales_amount 합계 (스냅샷)
  - total_payment_amount : orders.created_at 기준 COMPLETED 결제액, 당일 환불액 차감
  - total_fee_revenue    : GNB-169: (fee_rate - pg_rate) × sales_amount
                           fee_rate = 프로모션 적용 매장은 applied_fee_rate, 일반은 base_fee_rate
                           pgcode별 pg_rate 매핑 적용, 음수 허용

실행:
  ENV=dev  python3 scripts/aggregate_daily_platform_stats.py
  ENV=prod python3 scripts/aggregate_daily_platform_stats.py
  ENV=dev  python3 scripts/aggregate_daily_platform_stats.py --date 2026-07-01
  ENV=dev  python3 scripts/aggregate_daily_platform_stats.py --from 2026-06-01 --to 2026-06-30
"""
import os
import sys
import argparse
import math
from datetime import date, timedelta, datetime, timezone

KST = timezone(timedelta(hours=9))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pymysql
from core.config import settings
from core.fees import PG_FEE_RATE_MAP, PG_FEE_RATE_DEFAULT


def get_connection(db_name: str):
    return pymysql.connect(
        host=settings.db_host,
        user=settings.db_user,
        password=settings.db_password,
        database=db_name,
        port=settings.db_port,
        charset='utf8mb4',
        autocommit=False,
    )


def get_base_fee_rate(cursor) -> float:
    cursor.execute("SELECT base_fee_rate FROM platform_config ORDER BY config_id DESC LIMIT 1")
    row = cursor.fetchone()
    return float(row[0]) if row else 0.0


def aggregate_one_day(cursor, target: date, base_fee_rate: float) -> dict:
    d = target.strftime('%Y-%m-%d')

    # 신규 입점 매장 수
    cursor.execute("""
        SELECT COUNT(*) FROM store
        WHERE DATE(created_at) = %s
    """, (d,))
    new_store_count = cursor.fetchone()[0] or 0

    # 당일 활성 매장 수 (발행 또는 사용 발생)
    cursor.execute("""
        SELECT COUNT(DISTINCT store_id) FROM gifticon
        WHERE (DATE(created_at) = %s AND status NOT IN ('PENDING','REFUNDED','CANCELED'))
           OR (DATE(used_at) = %s AND status = 'USED')
    """, (d, d))
    active_store_count = cursor.fetchone()[0] or 0

    # 발행 수 / 발행 금액 (menu.price 기준)
    cursor.execute("""
        SELECT COUNT(*), COALESCE(SUM(m.price), 0)
        FROM gifticon g
        JOIN menu m ON g.menu_id = m.id
        WHERE DATE(g.created_at) = %s
          AND g.status NOT IN ('PENDING', 'REFUNDED', 'CANCELED')
    """, (d,))
    row = cursor.fetchone()
    total_issued_count = row[0] or 0
    total_issued_amount = int(row[1] or 0)

    # 사용 수 / 사용 금액 (settlement_details.sales_amount 스냅샷)
    cursor.execute("""
        SELECT COUNT(*), COALESCE(SUM(sd.sales_amount), 0)
        FROM gifticon g
        JOIN settlement_details sd ON sd.gifticon_id = g.id
        WHERE DATE(g.used_at) = %s
          AND g.status = 'USED'
    """, (d,))
    row = cursor.fetchone()
    total_used_count = row[0] or 0
    total_sales_amount = int(row[1] or 0)

    # 총 결제 금액 (COMPLETED 주문 - 당일 환불액)
    cursor.execute("""
        SELECT COALESCE(SUM(amount), 0) FROM orders
        WHERE DATE(created_at) = %s AND status = 'COMPLETED'
    """, (d,))
    payment_gross = int(cursor.fetchone()[0] or 0)

    cursor.execute("""
        SELECT COALESCE(SUM(refunded_amount), 0) FROM refund
        WHERE DATE(refunded_at) = %s AND status = 'COMPLETED'
    """, (d,))
    refund_amount = int(cursor.fetchone()[0] or 0)

    total_payment_amount = payment_gross - refund_amount

    # GNB-169: 플랫폼 순수수료 계산
    # gifticon별 (fee_rate - pg_rate) × sales_amount 합산
    # fee_rate: 프로모션 적용 매장 applied_fee_rate, 일반 base_fee_rate
    # pg_rate: gifticon→order의 pgcode 기준
    cursor.execute("""
        SELECT
            sd.sales_amount,
            o.pgcode,
            s.applied_fee_rate,
            s.base_fee_rate AS promo_base_fee_rate
        FROM gifticon g
        JOIN settlement_details sd ON sd.gifticon_id = g.id
        LEFT JOIN orders o ON g.order_id = o.id
        LEFT JOIN settlement s ON sd.settlement_id = s.settlement_id
        WHERE DATE(g.used_at) = %s
          AND g.status = 'USED'
    """, (d,))
    fee_rows = cursor.fetchall()

    total_fee_revenue = 0
    for row in fee_rows:
        sales_amount = int(row[0] or 0)
        pgcode = (row[1] or '').lower()
        applied_fee_rate = row[2]  # None이면 프로모션 미적용
        pg_rate = PG_FEE_RATE_MAP.get(pgcode, PG_FEE_RATE_DEFAULT)

        if applied_fee_rate is not None:
            fee_rate = float(applied_fee_rate)
        else:
            fee_rate = base_fee_rate

        net_rate = fee_rate - pg_rate
        total_fee_revenue += math.floor(sales_amount * net_rate / 100)

    return {
        'target_date': d,
        'new_store_count': new_store_count,
        'active_store_count': active_store_count,
        'total_issued_count': total_issued_count,
        'total_issued_amount': total_issued_amount,
        'total_used_count': total_used_count,
        'total_sales_amount': total_sales_amount,
        'total_payment_amount': total_payment_amount,
        'total_fee_revenue': total_fee_revenue,
    }


def upsert_stats(cursor, stats: dict):
    cursor.execute("""
        INSERT INTO stats_daily_platform (
            target_date, new_store_count, active_store_count,
            total_issued_count, total_issued_amount,
            total_used_count, total_sales_amount,
            total_payment_amount, total_fee_revenue
        ) VALUES (
            %(target_date)s, %(new_store_count)s, %(active_store_count)s,
            %(total_issued_count)s, %(total_issued_amount)s,
            %(total_used_count)s, %(total_sales_amount)s,
            %(total_payment_amount)s, %(total_fee_revenue)s
        )
        ON DUPLICATE KEY UPDATE
            new_store_count     = VALUES(new_store_count),
            active_store_count  = VALUES(active_store_count),
            total_issued_count  = VALUES(total_issued_count),
            total_issued_amount = VALUES(total_issued_amount),
            total_used_count    = VALUES(total_used_count),
            total_sales_amount  = VALUES(total_sales_amount),
            total_payment_amount = VALUES(total_payment_amount),
            total_fee_revenue   = VALUES(total_fee_revenue),
            updated_at          = CURRENT_TIMESTAMP
    """, stats)


def run(db_name: str, dates: list[date]):
    conn = get_connection(db_name)
    try:
        with conn.cursor() as cursor:
            base_fee_rate = get_base_fee_rate(cursor)
            print(f"base_fee_rate: {base_fee_rate}%")

        success = fail = 0
        for d in dates:
            try:
                with conn.cursor() as cursor:
                    stats = aggregate_one_day(cursor, d, base_fee_rate)
                    upsert_stats(cursor, stats)
                conn.commit()
                print(f"  ✓ {d}  발행:{stats['total_issued_count']}건/{stats['total_issued_amount']:,}원  "
                      f"사용:{stats['total_used_count']}건/{stats['total_sales_amount']:,}원  "
                      f"결제:{stats['total_payment_amount']:,}원  순수수료:{stats['total_fee_revenue']:,}원  "
                      f"신규매장:{stats['new_store_count']}")
                success += 1
            except Exception as e:
                conn.rollback()
                print(f"  ✗ {d}  실패: {e}")
                fail += 1

        print(f"\n완료: 성공 {success}개  실패 {fail}개")
        if fail:
            sys.exit(1)
    finally:
        conn.close()


def parse_args():
    parser = argparse.ArgumentParser(description='플랫폼 일별 통계 집계')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--date', type=str, help='특정 날짜 (YYYY-MM-DD)')
    group.add_argument('--from', dest='from_date', type=str, help='시작 날짜 (YYYY-MM-DD)')
    parser.add_argument('--to', dest='to_date', type=str, help='종료 날짜 (YYYY-MM-DD, --from 과 함께 사용)')
    return parser.parse_args()


def main():
    args = parse_args()
    env = os.getenv('ENV', 'dev')
    db_name = 'cafeplatform' if env in ('prod', 'production') else 'cafeplatform_dev'

    print(f"환경: {env}  DB: {db_name}")

    if args.date:
        dates = [date.fromisoformat(args.date)]
    elif args.from_date:
        start = date.fromisoformat(args.from_date)
        end = date.fromisoformat(args.to_date) if args.to_date else date.today() - timedelta(days=1)
        dates = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    else:
        dates = [date.today() - timedelta(days=1)]

    print(f"집계 대상: {dates[0]} ~ {dates[-1]}  ({len(dates)}일)\n")
    run(db_name, dates)


if __name__ == '__main__':
    main()
