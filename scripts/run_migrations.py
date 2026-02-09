#!/usr/bin/env python3
"""
마이그레이션 실행 스크립트
생성된 SQL 파일들을 데이터베이스에 실행합니다.
"""
import os
import sys
from pathlib import Path

# 프로젝트 루트를 Python 경로에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import pymysql
from core.config import settings

# 마이그레이션 파일 실행 순서
MIGRATION_FILES = [
    'create_platform_config_table.sql',
    'create_fee_promotions_table.sql',
    'add_applied_fee_rate_to_gifticon.sql',
    'create_order_history_table.sql',
    'create_refund_table.sql',
    'add_refund_reason.sql',
    'create_settlement_cycles_table.sql',
    'create_new_settlement_tables.sql',
    'add_settlement_failure_reason.sql',
    'create_stats_tables.sql',
    'create_terms_tables.sql',
    'add_fb_email_to_user.sql',
]

# RUN_TERMS_MIGRATE=1 일 때만 실행 (기존 약관 테이블 DROP 후 새 스키마로 생성, 데이터 삭제됨)
TERMS_FULL_MIGRATE_FILE = 'migrate_terms_to_new_schema.sql'

def run_migration_file(connection, file_path):
    """단일 마이그레이션 파일 실행"""
    print(f"\n실행 중: {file_path}")
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            sql_content = f.read()
        
        cursor = connection.cursor()
        
        # 세미콜론으로 구분된 여러 쿼리 실행
        # 주석과 빈 줄 제거 후 실행
        queries = []
        current_query = []
        
        for line in sql_content.split('\n'):
            line = line.strip()
            # 주석 제거
            if line.startswith('--'):
                continue
            if not line:
                continue
            
            current_query.append(line)
            
            # 세미콜론으로 쿼리 종료
            if line.endswith(';'):
                query = ' '.join(current_query)
                if query.strip():
                    queries.append(query)
                current_query = []
        
        # 남은 쿼리 추가
        if current_query:
            query = ' '.join(current_query)
            if query.strip():
                queries.append(query)
        
        # 각 쿼리 실행
        for query in queries:
            if query.strip():
                try:
                    cursor.execute(query)
                    print(f"  ✓ 쿼리 실행 완료")
                except pymysql.Error as e:
                    # 테이블이 이미 존재하는 경우는 무시
                    if "already exists" in str(e).lower() or "Duplicate" in str(e):
                        print(f"  ⚠ 테이블/컬럼이 이미 존재합니다: {str(e)[:100]}")
                    else:
                        print(f"  ✗ 쿼리 실행 실패: {str(e)[:200]}")
                        raise
        
        connection.commit()
        print(f"  ✓ {file_path} 완료")
        return True
        
    except Exception as e:
        print(f"  ✗ {file_path} 실행 실패: {str(e)}")
        connection.rollback()
        return False
    finally:
        cursor.close()


def main():
    """메인 함수"""
    # 환경에 따라 데이터베이스 이름 설정
    import os
    env = os.getenv("ENV", "dev")
    
    if env in ["prod", "production"]:
        db_name = "cafeplatform"
    else:
        db_name = "cafeplatform_dev"
    
    print(f"데이터베이스: {db_name}")
    print(f"호스트: {settings.db_host}")
    print(f"포트: {settings.db_port}")
    print(f"사용자: {settings.db_user}")
    print("\n마이그레이션 시작...")
    
    # 마이그레이션 파일 디렉토리
    migrations_dir = project_root / 'migrations'
    
    # 데이터베이스 연결 (데이터베이스 이름 지정)
    try:
        connection = pymysql.connect(
            host=settings.db_host,
            user=settings.db_user,
            password=settings.db_password,
            database=db_name,  # cafeplatform_dev 데이터베이스 사용
            port=settings.db_port,
            charset='utf8mb4',
            autocommit=False
        )
        print(f"\n✓ 데이터베이스 연결 성공: {db_name}")
    except pymysql.Error as e:
        print(f"\n✗ 데이터베이스 연결 실패: {str(e)}")
        print(f"  데이터베이스 '{db_name}'가 존재하는지 확인하세요.")
        sys.exit(1)
    
    # 각 마이그레이션 파일 실행
    success_count = 0
    fail_count = 0
    
    for migration_file in MIGRATION_FILES:
        file_path = migrations_dir / migration_file
        
        if not file_path.exists():
            print(f"\n⚠ 파일을 찾을 수 없습니다: {migration_file}")
            fail_count += 1
            continue
        
        if run_migration_file(connection, file_path):
            success_count += 1
        else:
            fail_count += 1

    # 약관 테이블 새 스키마 적용 (RUN_TERMS_MIGRATE=1 일 때만, terms/terms_version/user_terms_agreement/owner_terms_agreement 데이터 삭제됨)
    if os.getenv("RUN_TERMS_MIGRATE") == "1":
        terms_migrate_path = migrations_dir / TERMS_FULL_MIGRATE_FILE
        if terms_migrate_path.exists():
            print(f"\n⚠ RUN_TERMS_MIGRATE=1: {TERMS_FULL_MIGRATE_FILE} 실행 (약관 관련 테이블 데이터 초기화)")
            if run_migration_file(connection, terms_migrate_path):
                success_count += 1
            else:
                fail_count += 1
        else:
            print(f"\n⚠ 파일을 찾을 수 없습니다: {TERMS_FULL_MIGRATE_FILE}")
            fail_count += 1
    
    connection.close()
    
    # 결과 요약
    print("\n" + "="*50)
    print("마이그레이션 완료")
    print(f"성공: {success_count}개")
    print(f"실패: {fail_count}개")
    print("="*50)
    
    if fail_count > 0:
        sys.exit(1)


if __name__ == '__main__':
    main()
