#!/usr/bin/env python3
"""
마이그레이션 실행 스크립트
migration_history 테이블을 기반으로 미적용 파일만 실행하며, rollback을 지원합니다.
"""
import os
import re
import sys
from datetime import datetime
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import pymysql
from core.config import settings

# 기존 파일(버전 없음)은 이미 적용된 것으로 간주하여 추적하지 않음
# 신규 파일은 V{번호}__{설명}.up.sql / .down.sql 형식으로 작성

LEGACY_FILES = [
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
    'add_region_district_to_store.sql',
    'add_settlement_cycle_error_columns.sql',
    'add_tax_invoice_memo_to_settlement.sql',
    'add_terms_target.sql',
    'create_account_table.sql',
    'create_inquiry_tables.sql',
    'create_notice_tables.sql',
    'create_order_gifticon_table.sql',
    'create_owner_table.sql',
    'create_settlement_tables.sql',
    'migrate_terms_to_new_schema.sql',
    'rename_menu_menuId_to_id.sql',
    'rename_store_id_to_id.sql',
    'GNB-41_image_key_migration.sql',
]

VERSION_PATTERN = re.compile(r'^(V\d+)__(.+)\.up\.sql$')


def get_connection(db_name):
    return pymysql.connect(
        host=settings.db_host,
        user=settings.db_user,
        password=settings.db_password,
        database=db_name,
        port=settings.db_port,
        charset='utf8mb4',
        autocommit=False,
    )


def ensure_migration_history(connection):
    """migration_history 테이블이 없으면 생성"""
    sql = """
    CREATE TABLE IF NOT EXISTS migration_history (
        id              INT AUTO_INCREMENT PRIMARY KEY,
        version         VARCHAR(10),
        filename        VARCHAR(255),
        applied_at      DATETIME,
        rolled_back_at  DATETIME,
        status          ENUM('applied', 'rolled_back')
    )
    """
    with connection.cursor() as cursor:
        cursor.execute(sql)
    connection.commit()


def get_applied_versions(connection):
    """applied 상태인 version 목록 반환"""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT version FROM migration_history WHERE status = 'applied' ORDER BY version"
        )
        return {row[0] for row in cursor.fetchall()}


def record_applied(connection, version, filename):
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO migration_history (version, filename, applied_at, status) VALUES (%s, %s, %s, 'applied')",
            (version, filename, datetime.now()),
        )
    connection.commit()


def record_rolled_back(connection, version):
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE migration_history SET rolled_back_at = %s, status = 'rolled_back' WHERE version = %s AND status = 'applied'",
            (datetime.now(), version),
        )
    connection.commit()


def execute_sql_file(connection, file_path):
    """SQL 파일 내 쿼리를 순서대로 실행. 실패 시 rollback 후 False 반환."""
    with open(file_path, 'r', encoding='utf-8') as f:
        sql_content = f.read()

    queries = []
    current = []
    for line in sql_content.split('\n'):
        line = line.strip()
        if not line or line.startswith('--'):
            continue
        current.append(line)
        if line.endswith(';'):
            queries.append(' '.join(current))
            current = []
    if current:
        queries.append(' '.join(current))

    try:
        with connection.cursor() as cursor:
            for query in queries:
                if query.strip():
                    cursor.execute(query)
        connection.commit()
        return True
    except Exception as e:
        connection.rollback()
        print(f"  ✗ 실행 실패: {e}")
        return False


def discover_versioned_files(migrations_dir):
    """V번호__설명.up.sql 파일을 버전 순으로 반환"""
    files = []
    for path in migrations_dir.iterdir():
        m = VERSION_PATTERN.match(path.name)
        if m:
            files.append((m.group(1), path.name, path))
    files.sort(key=lambda x: x[0])
    return files


def cmd_migrate(connection, migrations_dir):
    ensure_migration_history(connection)
    applied = get_applied_versions(connection)

    versioned = discover_versioned_files(migrations_dir)
    if not versioned:
        print("적용할 마이그레이션 파일이 없습니다.")
        return

    pending = [(ver, fname, path) for ver, fname, path in versioned if ver not in applied]
    if not pending:
        print("모든 마이그레이션이 이미 적용되어 있습니다.")
        return

    success = fail = 0
    for version, filename, path in pending:
        print(f"\n적용 중: {filename}")
        if execute_sql_file(connection, path):
            record_applied(connection, version, filename)
            print(f"  ✓ {version} 완료")
            success += 1
        else:
            print(f"  ✗ {version} 실패 — 중단")
            fail += 1
            break

    print(f"\n성공: {success}개  실패: {fail}개")
    if fail:
        sys.exit(1)


def cmd_rollback(connection, migrations_dir, target_version):
    """target_version 이후 applied 항목을 역순으로 롤백"""
    ensure_migration_history(connection)

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT version, filename FROM migration_history WHERE status = 'applied' AND version > %s ORDER BY version DESC",
            (target_version,),
        )
        targets = cursor.fetchall()

    if not targets:
        print(f"{target_version} 이후 롤백할 항목이 없습니다.")
        return

    success = fail = 0
    for version, filename in targets:
        down_name = filename.replace('.up.sql', '.down.sql')
        down_path = migrations_dir / down_name
        print(f"\n롤백 중: {down_name}")
        if not down_path.exists():
            print(f"  ✗ down 파일 없음: {down_name}")
            fail += 1
            break
        if execute_sql_file(connection, down_path):
            record_rolled_back(connection, version)
            print(f"  ✓ {version} 롤백 완료")
            success += 1
        else:
            print(f"  ✗ {version} 롤백 실패 — 중단")
            fail += 1
            break

    print(f"\n롤백 성공: {success}개  실패: {fail}개")
    if fail:
        sys.exit(1)


def main():
    env = os.getenv("ENV", "dev")
    db_name = "cafeplatform" if env in ("prod", "production") else "cafeplatform_dev"

    print(f"환경: {env}  DB: {db_name}")
    print(f"호스트: {settings.db_host}:{settings.db_port}  사용자: {settings.db_user}")

    try:
        connection = get_connection(db_name)
        print(f"✓ DB 연결 성공: {db_name}\n")
    except pymysql.Error as e:
        print(f"✗ DB 연결 실패: {e}")
        sys.exit(1)

    migrations_dir = project_root / 'migrations'
    args = sys.argv[1:]

    try:
        if args and args[0] == 'rollback':
            if len(args) < 2:
                print("사용법: python run_migrations.py rollback V003")
                sys.exit(1)
            cmd_rollback(connection, migrations_dir, args[1])
        else:
            cmd_migrate(connection, migrations_dir)
    finally:
        connection.close()


if __name__ == '__main__':
    main()
