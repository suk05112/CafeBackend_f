#!/usr/bin/env python3
"""
데이터베이스 연결 테스트 스크립트
"""
import sys
import os

# 프로젝트 루트를 Python 경로에 추가
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db.session import get_db_connection
from core.config import settings

def test_db_connection():
    """데이터베이스 연결을 테스트합니다."""
    print("=" * 50)
    print("데이터베이스 연결 테스트")
    print("=" * 50)
    print(f"DB Host: {settings.db_host}")
    print(f"DB Port: {settings.db_port}")
    print(f"DB User: {settings.db_user}")
    print(f"DB Name: {settings.db_name}")
    print("=" * 50)
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 간단한 쿼리 실행
        cursor.execute("SELECT 1 as test")
        result = cursor.fetchone()
        
        if result:
            print("✅ 데이터베이스 연결 성공!")
            print(f"테스트 쿼리 결과: {result}")
        else:
            print("⚠️  쿼리는 실행되었지만 결과가 없습니다.")
        
        cursor.close()
        conn.close()
        
        return True
        
    except Exception as e:
        print(f"❌ 데이터베이스 연결 실패!")
        print(f"오류 메시지: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_db_connection()
    sys.exit(0 if success else 1)


