#!/usr/bin/env python3
"""
정산 주기 데이터 생성 스크립트
1년치 정산 주기 데이터를 생성하여 DB에 저장합니다.
"""
import sys
import os
from datetime import date

# 프로젝트 루트를 Python 경로에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crud.settlement_cycle import generate_settlement_cycles

def main():
    """메인 함수"""
    # 오늘 날짜부터 1년치 생성
    start_date = date.today()
    months = 12
    
    print(f"정산 주기 데이터 생성 시작...")
    print(f"시작일: {start_date}")
    print(f"생성 기간: {months}개월")
    print()
    
    try:
        count = generate_settlement_cycles(start_date, months)
        print(f"✓ {count}개의 정산 주기가 생성되었습니다.")
        print()
        print("생성 완료!")
        return 0
    except Exception as e:
        print(f"✗ 오류 발생: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == '__main__':
    sys.exit(main())
