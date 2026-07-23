#!/usr/bin/env python3
"""
GNB-198: settlement_details 건별 기본 수수료 백필

V039 마이그레이션/useGifticon 코드 배포 이전에 이미 사용(USED)되었지만
아직 정산 배치(settlement_id 연결)가 되지 않은 건은 fee_supply/fee_vat/fee_amount/
settlement_amount가 NULL이다. 이 스크립트는 현재 platform_config.base_fee_rate
기준으로 그 값들을 1회성으로 채운다.

실행:
  ENV=dev  python3 scripts/backfill_settlement_details_fee.py
  ENV=prod python3 scripts/backfill_settlement_details_fee.py
"""
import os
import sys
import math
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import pymysql
from core.config import settings


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


def main():
    env = os.getenv('ENV', 'dev')
    db_name = 'cafeplatform' if env in ('prod', 'production') else 'cafeplatform_dev'
    print(f"환경: {env}  DB: {db_name}")

    conn = get_connection(db_name)
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute("SELECT base_fee_rate FROM platform_config WHERE config_id = 1")
            fee_rate = float(cursor.fetchone()['base_fee_rate'])
            print(f"base_fee_rate: {fee_rate}%")

            cursor.execute("""
                SELECT id, sales_amount
                FROM settlement_details
                WHERE settlement_id IS NULL AND fee_amount IS NULL
            """)
            rows = cursor.fetchall()
            print(f"보정 대상: {len(rows)}건")

            if not rows:
                return

            for row in rows:
                sales_amount = int(row['sales_amount'])
                fee_supply = math.floor(sales_amount * fee_rate / 100)
                fee_vat = round(fee_supply * 0.1)
                fee_amount = fee_supply + fee_vat
                settlement_amount = sales_amount - fee_amount

                cursor.execute("""
                    UPDATE settlement_details
                    SET fee_rate = %s, fee_supply = %s, fee_vat = %s,
                        fee_amount = %s, settlement_amount = %s
                    WHERE id = %s
                """, (fee_rate, fee_supply, fee_vat, fee_amount, settlement_amount, row['id']))

        conn.commit()
        print(f"완료: {len(rows)}건 보정")
    except Exception as e:
        conn.rollback()
        print(f"실패: {e}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == '__main__':
    main()
