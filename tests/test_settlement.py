#!/usr/bin/env python3
"""
정산 데이터 검증 테스트 코드 (V024 이후 스키마 기준)

V024 변경 요약:
  - 기프티콘 시점 수수료 저장 폐기 → 정산 시점(payout_date 기준) 수수료 확정
  - settlement_details.fee_amount / settlement_amount / *_fee_rate / applied_promo_id / fee_supply / fee_vat 삭제
  - settlement 테이블에 base_fee_rate, applied_promo_id, applied_fee_rate,
    original_fee_supply/vat/amount, promo_fee_supply/vat/amount 추가
"""
import sys
import os
import math

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pymysql
from core.config import settings
from crud import stats as stats_crud


def get_db_connection():
    """데이터베이스 연결"""
    return pymysql.connect(
        host=settings.db_host,
        user=settings.db_user,
        password=settings.db_password,
        database='cafeplatform_dev',
        port=settings.db_port,
        charset='utf8mb4'
    )


def _calc_fee(sales_amount: int, fee_rate_pct: float):
    supply = math.floor(sales_amount * fee_rate_pct / 100)
    vat = round(supply * 0.1)
    return supply, vat, supply + vat


def test_settlement_cycles():
    """정산 주기 데이터 검증"""
    print("=" * 60)
    print("1. 정산 주기 데이터 검증")
    print("=" * 60)

    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)

    try:
        cursor.execute('SELECT COUNT(*) as cnt FROM settlement_cycles')
        total = cursor.fetchone()['cnt']
        print(f"✓ 총 정산 주기 개수: {total}")

        if total == 0:
            print("⚠ 정산 주기 데이터가 없습니다. 먼저 생성해주세요.")
            return False

        cursor.execute('''
            SELECT cycle_id, period_start_date, period_end_date,
                   DATEDIFF(period_end_date, period_start_date) as days
            FROM settlement_cycles
            ORDER BY period_start_date
            LIMIT 10
        ''')

        cycles = cursor.fetchall()
        all_valid = True
        for cycle in cycles:
            days = cycle['days']
            if days != 6:
                print(f"✗ Cycle {cycle['cycle_id']}: 기간이 올바르지 않습니다. (예상: 6일, 실제: {days}일)")
                all_valid = False
            else:
                print(f"✓ Cycle {cycle['cycle_id']}: {cycle['period_start_date']} ~ {cycle['period_end_date']} ({days+1}일)")

        cursor.execute('''
            SELECT cycle_id, period_end_date, payout_date,
                   DATEDIFF(payout_date, period_end_date) as delay_days
            FROM settlement_cycles
            ORDER BY period_start_date
            LIMIT 10
        ''')

        payouts = cursor.fetchall()
        all_valid_payout = True
        for payout in payouts:
            delay = payout['delay_days']
            if delay != 21:
                print(f"✗ Cycle {payout['cycle_id']}: 정산일 지연이 올바르지 않습니다. (예상: 21일, 실제: {delay}일)")
                all_valid_payout = False
            else:
                print(f"✓ Cycle {payout['cycle_id']}: 정산일 {payout['payout_date']} (지연: {delay}일)")

        return all_valid and all_valid_payout
    finally:
        cursor.close()
        connection.close()


def test_settlement_data_creation():
    """정산 데이터 생성 검증"""
    print("\n" + "=" * 60)
    print("2. 정산 데이터 생성 검증")
    print("=" * 60)

    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)

    try:
        cursor.execute('''
            SELECT cycle_id, period_start_date, period_end_date, payout_date
            FROM settlement_cycles
            WHERE status = 'OPEN'
            ORDER BY period_start_date
            LIMIT 1
        ''')

        cycle = cursor.fetchone()
        if not cycle:
            print("⚠ OPEN 상태의 정산 주기가 없습니다.")
            return False

        cycle_id = cycle['cycle_id']
        print(f"테스트할 정산 주기: Cycle {cycle_id} ({cycle['period_start_date']} ~ {cycle['period_end_date']})")

        cursor.execute('''
            SELECT COUNT(*) as cnt
            FROM settlement_details sd
            JOIN gifticon g ON sd.gifticon_id = g.id
            WHERE sd.settlement_id IS NULL
              AND g.used_at >= %s
              AND g.used_at < DATE_ADD(%s, INTERVAL 1 DAY)
        ''', (cycle['period_start_date'], cycle['period_end_date']))

        available_count = cursor.fetchone()['cnt']
        print(f"정산 가능한 미정산 상세 개수: {available_count}")

        if available_count == 0:
            print("⚠ 해당 기간에 정산 가능한 데이터가 없습니다. (테스트는 통과 처리)")
            return True

        result = stats_crud.create_settlement_data(cycle_id)
        print(f"✓ {result['message']} (생성 {result['settlement_count']}건)")

        cursor.execute('''
            SELECT total_sales_amount, total_fee_amount, net_payout_amount,
                   base_fee_rate, applied_fee_rate, applied_promo_id,
                   original_fee_supply, original_fee_vat, original_fee_amount,
                   promo_fee_supply, promo_fee_vat, promo_fee_amount
            FROM settlement
            WHERE cycle_id = %s
        ''', (cycle_id,))
        rows = cursor.fetchall()
        print(f"✓ DB에 저장된 정산 개수: {len(rows)}")

        all_ok = True
        for row in rows:
            sales = int(row['total_sales_amount'])
            base_rate = float(row['base_fee_rate'])
            applied_rate = float(row['applied_fee_rate'])
            applied_promo_id = row['applied_promo_id']

            # 원본 수수료 재계산
            exp_o_supply, exp_o_vat, exp_o_fee = _calc_fee(sales, base_rate)
            if (row['original_fee_supply'] != exp_o_supply
                    or row['original_fee_vat'] != exp_o_vat
                    or row['original_fee_amount'] != exp_o_fee):
                print(f"✗ 원본 수수료 불일치: sales={sales}, base_rate={base_rate}, 저장={row['original_fee_amount']}, 예상={exp_o_fee}")
                all_ok = False

            # 프로모션 있으면 promo_fee 검증, 없으면 NULL 검증
            if applied_promo_id is not None:
                exp_p_supply, exp_p_vat, exp_p_fee = _calc_fee(sales, applied_rate)
                if (row['promo_fee_supply'] != exp_p_supply
                        or row['promo_fee_vat'] != exp_p_vat
                        or row['promo_fee_amount'] != exp_p_fee):
                    print(f"✗ 프로모션 수수료 불일치: sales={sales}, applied_rate={applied_rate}")
                    all_ok = False
                if row['total_fee_amount'] != exp_p_fee:
                    print(f"✗ 프로모션 적용 시 total_fee_amount({row['total_fee_amount']}) != promo_fee({exp_p_fee})")
                    all_ok = False
            else:
                if row['promo_fee_supply'] is not None or row['promo_fee_vat'] is not None or row['promo_fee_amount'] is not None:
                    print(f"✗ 프로모션 없음인데 promo_fee_* 가 채워짐: {row['promo_fee_amount']}")
                    all_ok = False
                if row['total_fee_amount'] != exp_o_fee:
                    print(f"✗ 프로모션 없을 때 total_fee_amount({row['total_fee_amount']}) != original_fee({exp_o_fee})")
                    all_ok = False

            # 순지급액 검증
            expected_payout = sales - int(row['total_fee_amount'])
            if int(row['net_payout_amount']) != expected_payout:
                print(f"✗ net_payout 불일치: 예상 {expected_payout}, 실제 {row['net_payout_amount']}")
                all_ok = False

        if all_ok:
            print("✓ 모든 정산 수수료/지급액이 올바르게 계산되었습니다.")
        return all_ok

    except Exception as e:
        print(f"✗ 오류 발생: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        cursor.close()
        connection.close()


def test_settlement_details_integrity():
    """정산 상세 데이터 무결성 검증"""
    print("\n" + "=" * 60)
    print("3. 정산 상세 데이터 무결성 검증")
    print("=" * 60)

    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)

    try:
        # settlement_id가 채워진 상세 중 중복 기프티콘 검증
        cursor.execute('''
            SELECT gifticon_id, COUNT(*) as cnt
            FROM settlement_details
            WHERE settlement_id IS NOT NULL
            GROUP BY gifticon_id
            HAVING cnt > 1
        ''')

        duplicates = cursor.fetchall()
        if duplicates:
            print(f"✗ 중복 정산된 기프티콘이 {len(duplicates)}개 있습니다.")
            return False
        print("✓ 중복 정산된 기프티콘이 없습니다.")

        # 외래키 무결성 (settlement)
        cursor.execute('''
            SELECT COUNT(*) as cnt
            FROM settlement_details sd
            LEFT JOIN settlement s ON sd.settlement_id = s.settlement_id
            WHERE sd.settlement_id IS NOT NULL AND s.settlement_id IS NULL
        ''')
        orphaned = cursor.fetchone()['cnt']
        if orphaned > 0:
            print(f"✗ 부모 정산이 없는 정산 상세가 {orphaned}개 있습니다.")
            return False
        print("✓ 모든 정산 상세가 유효한 정산에 연결되어 있습니다.")

        # 외래키 무결성 (gifticon)
        cursor.execute('''
            SELECT COUNT(*) as cnt
            FROM settlement_details sd
            LEFT JOIN gifticon g ON sd.gifticon_id = g.id
            WHERE g.id IS NULL
        ''')
        orphaned_gifticon = cursor.fetchone()['cnt']
        if orphaned_gifticon > 0:
            print(f"✗ 존재하지 않는 기프티콘을 참조하는 상세가 {orphaned_gifticon}개 있습니다.")
            return False
        print("✓ 모든 정산 상세가 유효한 기프티콘을 참조합니다.")
        return True
    finally:
        cursor.close()
        connection.close()


def test_settlement_amount_per_store():
    """매장별 정산금액 검증: settlement.total_sales_amount = 해당 details 합계"""
    print("\n" + "=" * 60)
    print("4. 매장별 정산금액 검증")
    print("=" * 60)

    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)

    try:
        cursor.execute('''
            SELECT
                s.settlement_id,
                s.store_id,
                s.total_sales_amount AS s_sales,
                COALESCE(SUM(sd.sales_amount), 0) AS d_sales
            FROM settlement s
            LEFT JOIN settlement_details sd ON s.settlement_id = sd.settlement_id
            GROUP BY s.settlement_id, s.store_id, s.total_sales_amount
            HAVING ABS(s.total_sales_amount - COALESCE(SUM(sd.sales_amount), 0)) > 1
        ''')

        mismatches = cursor.fetchall()
        if mismatches:
            print(f"✗ 매장별 매출액이 상세 합계와 일치하지 않는 건이 {len(mismatches)}건 있습니다:")
            for m in mismatches:
                print(f"  settlement_id={m['settlement_id']}, store_id={m['store_id']}: settlement={m['s_sales']:,} vs details={m['d_sales']:,}")
            return False

        cursor.execute('SELECT COUNT(*) AS cnt FROM settlement')
        total = cursor.fetchone()['cnt']
        print(f"✓ 검증한 정산 건수: {total}건")
        print("✓ 모든 매장별 매출액이 상세 합계와 일치합니다.")
        return True
    except Exception as e:
        print(f"✗ 오류 발생: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        cursor.close()
        connection.close()


def main():
    print("\n" + "=" * 60)
    print("정산 데이터 검증 테스트 시작 (V024 스키마)")
    print("=" * 60)

    results = [
        ("정산 주기 데이터", test_settlement_cycles()),
        ("정산 데이터 생성", test_settlement_data_creation()),
        ("정산 상세 무결성", test_settlement_details_integrity()),
        ("매장별 정산금액", test_settlement_amount_per_store()),
    ]

    print("\n" + "=" * 60)
    print("테스트 결과 요약")
    print("=" * 60)

    passed = failed = 0
    for name, ok in results:
        print(f"{'✓ 통과' if ok else '✗ 실패'}: {name}")
        passed += 1 if ok else 0
        failed += 0 if ok else 1

    print(f"\n총 {len(results)}개 중 {passed}개 통과, {failed}개 실패")
    return 0 if failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
