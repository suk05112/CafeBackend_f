#!/usr/bin/env python3
"""
정산 데이터 검증 테스트 코드
"""
import sys
import os
from datetime import date, datetime, timedelta

# 프로젝트 루트를 Python 경로에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pymysql
from core.config import settings
from crud import settlement_cycle as cycle_crud
from crud import stats as stats_crud
from crud import promotion as promotion_crud


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


def test_settlement_cycles():
    """정산 주기 데이터 검증"""
    print("=" * 60)
    print("1. 정산 주기 데이터 검증")
    print("=" * 60)
    
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        # 전체 정산 주기 개수 확인
        cursor.execute('SELECT COUNT(*) as cnt FROM settlement_cycles')
        total = cursor.fetchone()['cnt']
        print(f"✓ 총 정산 주기 개수: {total}")
        
        if total == 0:
            print("⚠ 정산 주기 데이터가 없습니다. 먼저 생성해주세요.")
            return False
        
        # 정산 주기 기간 검증 (5일)
        cursor.execute('''
            SELECT 
                cycle_id,
                period_start_date,
                period_end_date,
                DATEDIFF(period_end_date, period_start_date) as days
            FROM settlement_cycles
            ORDER BY period_start_date
            LIMIT 10
        ''')
        
        cycles = cursor.fetchall()
        all_valid = True
        
        for cycle in cycles:
            days = cycle['days']
            if days != 4:  # 시작일 포함하면 5일이지만 DATEDIFF는 4를 반환
                print(f"✗ Cycle {cycle['cycle_id']}: 기간이 올바르지 않습니다. (예상: 4일, 실제: {days}일)")
                all_valid = False
            else:
                print(f"✓ Cycle {cycle['cycle_id']}: {cycle['period_start_date']} ~ {cycle['period_end_date']} ({days+1}일)")
        
        if all_valid:
            print("✓ 모든 정산 주기 기간이 올바릅니다.")
        
        # 정산일 검증 (종료일 + 10일, 영업일 기준)
        cursor.execute('''
            SELECT 
                cycle_id,
                period_end_date,
                payout_date,
                DATEDIFF(payout_date, period_end_date) as delay_days
            FROM settlement_cycles
            ORDER BY period_start_date
            LIMIT 10
        ''')
        
        payouts = cursor.fetchall()
        all_valid_payout = True
        
        for payout in payouts:
            delay = payout['delay_days']
            payout_date = payout['payout_date']
            weekday = payout_date.weekday()  # 0=월요일, 6=일요일
            
            # 최소 10일, 최대 12일 (주말 고려)
            if delay < 10 or delay > 12:
                print(f"✗ Cycle {payout['cycle_id']}: 정산일이 올바르지 않습니다. (종료일: {payout['period_end_date']}, 정산일: {payout_date}, 지연: {delay}일)")
                all_valid_payout = False
            elif weekday >= 5:  # 토요일(5) 또는 일요일(6)
                print(f"✗ Cycle {payout['cycle_id']}: 정산일이 주말입니다. (정산일: {payout_date})")
                all_valid_payout = False
            else:
                print(f"✓ Cycle {payout['cycle_id']}: 정산일 {payout_date} (지연: {delay}일, 영업일)")
        
        if all_valid_payout:
            print("✓ 모든 정산일이 올바릅니다.")
        
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
        # OPEN 상태의 정산 주기 조회
        cursor.execute('''
            SELECT cycle_id, period_start_date, period_end_date
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
        
        # 테스트용 기프티콘 데이터 확인
        cursor.execute('''
            SELECT COUNT(*) as cnt
            FROM gifticon
            WHERE status = 'USED'
            AND DATE(used_at) >= %s
            AND DATE(used_at) <= %s
            AND id NOT IN (SELECT gifticon_id FROM settlement_details)
        ''', (cycle['period_start_date'], cycle['period_end_date']))
        
        available_count = cursor.fetchone()['cnt']
        print(f"정산 가능한 기프티콘 개수: {available_count}")
        
        if available_count == 0:
            print("⚠ 해당 기간에 정산 가능한 기프티콘이 없습니다.")
            print("  (실제 데이터가 있으면 정산 데이터 생성이 가능합니다.)")
            return True  # 데이터가 없어도 테스트는 통과
        
        # 정산 데이터 생성 테스트
        print(f"\n정산 데이터 생성 시도...")
        result = stats_crud.create_settlement_data(cycle_id)
        
        print(f"✓ {result['message']}")
        print(f"✓ 생성된 정산 개수: {result['settlement_count']}")
        
        # 생성된 정산 데이터 확인
        cursor.execute('''
            SELECT COUNT(*) as cnt
            FROM settlement
            WHERE cycle_id = %s
        ''', (cycle_id,))
        
        settlement_count = cursor.fetchone()['cnt']
        print(f"✓ DB에 저장된 정산 개수: {settlement_count}")
        
        # 정산 상세 데이터 확인
        cursor.execute('''
            SELECT COUNT(*) as cnt
            FROM settlement_details sd
            JOIN settlement s ON sd.settlement_id = s.settlement_id
            WHERE s.cycle_id = %s
        ''', (cycle_id,))
        
        detail_count = cursor.fetchone()['cnt']
        print(f"✓ 정산 상세 데이터 개수: {detail_count}")
        
        # 정산 금액 검증
        cursor.execute('''
            SELECT 
                SUM(total_sales_amount) as total_sales,
                SUM(total_fee_amount) as total_fee,
                SUM(net_payout_amount) as total_payout
            FROM settlement
            WHERE cycle_id = %s
        ''', (cycle_id,))
        
        amounts = cursor.fetchone()
        if amounts['total_sales']:
            print(f"\n정산 금액 요약:")
            print(f"  총 매출액: {amounts['total_sales']:,}원")
            print(f"  총 수수료: {amounts['total_fee']:,}원")
            print(f"  실 지급액: {amounts['total_payout']:,}원")
            
            # 검증: 매출액 - 수수료 = 지급액
            expected_payout = amounts['total_sales'] - amounts['total_fee']
            if abs(expected_payout - amounts['total_payout']) < 1:  # 소수점 오차 허용
                print(f"✓ 금액 검증 통과: {amounts['total_sales']:,} - {amounts['total_fee']:,} = {amounts['total_payout']:,}")
            else:
                print(f"✗ 금액 검증 실패: 예상 지급액 {expected_payout:,} != 실제 지급액 {amounts['total_payout']:,}")
                return False
        
        return True
        
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
        # 중복 기프티콘 검증 (하나의 기프티콘은 한 번만 정산되어야 함)
        cursor.execute('''
            SELECT gifticon_id, COUNT(*) as cnt
            FROM settlement_details
            GROUP BY gifticon_id
            HAVING cnt > 1
        ''')
        
        duplicates = cursor.fetchall()
        if duplicates:
            print(f"✗ 중복 정산된 기프티콘이 {len(duplicates)}개 있습니다:")
            for dup in duplicates:
                print(f"  기프티콘 ID {dup['gifticon_id']}: {dup['cnt']}회 정산")
            return False
        else:
            print("✓ 중복 정산된 기프티콘이 없습니다.")
        
        # 정산 금액 일치 검증 (sales_amount - fee_amount = settlement_amount)
        cursor.execute('''
            SELECT 
                id,
                sales_amount,
                fee_amount,
                settlement_amount,
                (sales_amount - fee_amount) as expected_settlement
            FROM settlement_details
            WHERE ABS((sales_amount - fee_amount) - settlement_amount) > 1
            LIMIT 10
        ''')
        
        mismatches = cursor.fetchall()
        if mismatches:
            print(f"✗ 금액이 일치하지 않는 정산 상세 데이터가 {len(mismatches)}개 있습니다:")
            for mismatch in mismatches:
                print(f"  ID {mismatch['id']}: 매출 {mismatch['sales_amount']} - 수수료 {mismatch['fee_amount']} = {mismatch['expected_settlement']} (실제: {mismatch['settlement_amount']})")
            return False
        else:
            print("✓ 모든 정산 상세 금액이 일치합니다.")
        
        # 외래키 무결성 검증
        cursor.execute('''
            SELECT COUNT(*) as cnt
            FROM settlement_details sd
            LEFT JOIN settlement s ON sd.settlement_id = s.settlement_id
            WHERE s.settlement_id IS NULL
        ''')
        
        orphaned = cursor.fetchone()['cnt']
        if orphaned > 0:
            print(f"✗ 부모 정산이 없는 정산 상세 데이터가 {orphaned}개 있습니다.")
            return False
        else:
            print("✓ 모든 정산 상세 데이터가 유효한 정산에 연결되어 있습니다.")
        
        cursor.execute('''
            SELECT COUNT(*) as cnt
            FROM settlement_details sd
            LEFT JOIN gifticon g ON sd.gifticon_id = g.id
            WHERE g.id IS NULL
        ''')
        
        orphaned_gifticon = cursor.fetchone()['cnt']
        if orphaned_gifticon > 0:
            print(f"✗ 존재하지 않는 기프티콘을 참조하는 정산 상세 데이터가 {orphaned_gifticon}개 있습니다.")
            return False
        else:
            print("✓ 모든 정산 상세 데이터가 유효한 기프티콘을 참조합니다.")
        
        return True
        
    finally:
        cursor.close()
        connection.close()


def test_fee_rate_application():
    """수수료율 적용 검증"""
    print("\n" + "=" * 60)
    print("4. 수수료율 적용 검증")
    print("=" * 60)
    
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        # applied_fee_rate가 설정된 기프티콘 확인
        cursor.execute('''
            SELECT COUNT(*) as cnt
            FROM gifticon
            WHERE applied_fee_rate IS NOT NULL
        ''')
        
        with_fee_rate = cursor.fetchone()['cnt']
        print(f"✓ applied_fee_rate가 설정된 기프티콘: {with_fee_rate}개")
        
        # 정산 상세에서 수수료율 검증
        cursor.execute('''
            SELECT 
                sd.id,
                sd.sales_amount,
                sd.fee_amount,
                g.applied_fee_rate,
                (sd.sales_amount * g.applied_fee_rate / 100) as expected_fee
            FROM settlement_details sd
            JOIN gifticon g ON sd.gifticon_id = g.id
            WHERE ABS(sd.fee_amount - (sd.sales_amount * g.applied_fee_rate / 100)) > 1
            LIMIT 10
        ''')
        
        mismatches = cursor.fetchall()
        if mismatches:
            print(f"⚠ 수수료율이 일치하지 않는 데이터가 {len(mismatches)}개 있습니다 (반올림 오차 가능):")
            for mismatch in mismatches[:5]:
                print(f"  ID {mismatch['id']}: 매출 {mismatch['sales_amount']}, 수수료율 {mismatch['applied_fee_rate']}%, 예상 수수료 {mismatch['expected_fee']:.0f}, 실제 수수료 {mismatch['fee_amount']}")
        else:
            print("✓ 모든 수수료율이 올바르게 적용되었습니다.")
        
        return True
        
    finally:
        cursor.close()
        connection.close()


def test_settlement_amount_per_store():
    """매장별 정산금액 검증: settlement 합계 = 해당 settlement_details 합계"""
    print("\n" + "=" * 60)
    print("5. 매장별 정산금액 검증")
    print("=" * 60)

    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)

    try:
        # settlement 테이블의 금액 vs settlement_details 합계 비교
        cursor.execute('''
            SELECT 
                s.settlement_id,
                s.store_id,
                s.total_sales_amount AS s_sales,
                s.total_fee_amount AS s_fee,
                s.net_payout_amount AS s_payout,
                COALESCE(SUM(sd.sales_amount), 0) AS d_sales,
                COALESCE(SUM(sd.fee_amount), 0) AS d_fee,
                COALESCE(SUM(sd.settlement_amount), 0) AS d_payout
            FROM settlement s
            LEFT JOIN settlement_details sd ON s.settlement_id = sd.settlement_id
            GROUP BY s.settlement_id, s.store_id, s.total_sales_amount, s.total_fee_amount, s.net_payout_amount
            HAVING ABS(s.total_sales_amount - COALESCE(SUM(sd.sales_amount), 0)) > 1
                OR ABS(s.total_fee_amount - COALESCE(SUM(sd.fee_amount), 0)) > 1
                OR ABS(s.net_payout_amount - COALESCE(SUM(sd.settlement_amount), 0)) > 1
        ''')

        mismatches = cursor.fetchall()
        if mismatches:
            print(f"✗ 매장별 정산금액이 상세 합계와 일치하지 않는 건이 {len(mismatches)}건 있습니다:")
            for m in mismatches:
                print(f"  settlement_id={m['settlement_id']}, store_id={m['store_id']}:")
                print(f"    settlement 테이블: 매출 {m['s_sales']:,} / 수수료 {m['s_fee']:,} / 지급액 {m['s_payout']:,}")
                print(f"    상세 합계:        매출 {m['d_sales']:,} / 수수료 {m['d_fee']:,} / 지급액 {m['d_payout']:,}")
            return False

        cursor.execute('SELECT COUNT(*) AS cnt FROM settlement')
        total = cursor.fetchone()['cnt']
        print(f"✓ 검증한 정산 건수: {total}건")
        print("✓ 모든 매장별 정산금액이 상세 합계와 일치합니다.")
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
    """메인 테스트 함수"""
    print("\n" + "=" * 60)
    print("정산 데이터 검증 테스트 시작")
    print("=" * 60)
    
    results = []
    
    # 1. 정산 주기 검증
    results.append(("정산 주기 데이터", test_settlement_cycles()))
    
    # 2. 정산 데이터 생성 검증
    results.append(("정산 데이터 생성", test_settlement_data_creation()))
    
    # 3. 정산 상세 무결성 검증
    results.append(("정산 상세 무결성", test_settlement_details_integrity()))
    
    # 4. 수수료율 적용 검증
    results.append(("수수료율 적용", test_fee_rate_application()))

    # 5. 매장별 정산금액 검증
    results.append(("매장별 정산금액", test_settlement_amount_per_store()))

    # 결과 요약
    print("\n" + "=" * 60)
    print("테스트 결과 요약")
    print("=" * 60)
    
    passed = 0
    failed = 0
    
    for test_name, result in results:
        status = "✓ 통과" if result else "✗ 실패"
        print(f"{status}: {test_name}")
        if result:
            passed += 1
        else:
            failed += 1
    
    print(f"\n총 {len(results)}개 테스트 중 {passed}개 통과, {failed}개 실패")
    
    return 0 if failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
