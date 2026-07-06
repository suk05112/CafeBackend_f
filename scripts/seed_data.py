"""
테스트 데이터 시드 스크립트 (Store 41, User 60)

실제 API 로직을 그대로 재현:
  1. 주문/기프티콘 생성 (requestPaymentUrl 로직)
  2. mock 결제 완료 (updatePaymentResult 로직, PG 없이)
  3. 기프티콘 사용 처리 (useGifticon 로직)
  4. 환불 처리 (refund 로직)
  5. 날짜 보정 (INSERT 후 UPDATE로 과거 날짜 적용)
  6. 정산 배치 실행 (create_settlement_data + payout_date 기준일 override)

실행: cd /home/ubuntu/CafeBackend && ENV=prod python3 scripts/seed_data.py
"""

import sys
import os
import math
import uuid
import hashlib
from datetime import datetime, timedelta, date, timezone
from dataclasses import dataclass, field
from typing import Optional

# 프로젝트 루트를 path에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pymysql
from db.session import get_db_connection, close_db_connection
from crud import promotion as promotion_crud

# ── KST 헬퍼 ──────────────────────────────────────────────
KST = timezone(timedelta(hours=9))

def kst_now():
    return datetime.now(KST)

# ── 수수료 계산 (stats.py _calc_fee 동일) ────────────────
def calc_fee(sales: int, rate_pct: float):
    supply = math.floor(sales * rate_pct / 100)
    vat    = round(supply * 0.1)
    return supply, vat, supply + vat

# ── 주문번호 생성 ─────────────────────────────────────────
def generate_order_no(conn, ref_date: date) -> str:
    """ref_date 기준 yyddd + seq 형식 주문번호 생성"""
    cursor = conn.cursor(pymysql.cursors.DictCursor)
    try:
        yyddd = ref_date.strftime("%y") + str(ref_date.timetuple().tm_yday).zfill(3)
        cursor.execute(
            "SELECT COUNT(*) as cnt FROM orders WHERE DATE(created_at) = %s", (ref_date,)
        )
        seq = cursor.fetchone()['cnt'] + 1
        return f"{yyddd}{seq + 5000:05d}"
    finally:
        cursor.close()

# ── 기프티콘 코드 생성 ────────────────────────────────────
def generate_gift_code(store_id: int, user_id: int, gifticon_id: int, ref_date: date) -> str:
    yymm       = ref_date.strftime("%y%m")
    store_part = store_id % 10000
    user_part  = (user_id + 5000) % 10000
    seq        = gifticon_id % 10000
    raw        = f"{yymm}{store_part:04d}{user_part:04d}{seq:04d}"
    return f"{raw[:4]}-{raw[4:8]}-{raw[8:12]}-{raw[12:16]}"


# ── 시나리오 정의 ─────────────────────────────────────────
@dataclass
class GifticonScenario:
    menu_id:    int
    amount:     int
    status:     str          # USED | UNUSED | REFUNDED
    order_date: date         # 구매일
    used_date:  Optional[date] = None  # USED일 때만

@dataclass
class CycleScenario:
    cycle_id:    int
    period_start: date
    period_end:   date
    payout_date:  date
    settlement_status: str   # COMPLETED | PENDING | None(정산 없음)
    gifticons:   list = field(default_factory=list)


# 메뉴 ID는 스크립트 실행 후 INSERT된 ID로 채워짐
# 키: 메뉴명, 값: (price, category)
NEW_MENUS = {
    '아이스 라떼':  (4500, '음료'),
    '카페모카':     (5500, '음료'),
    '크루아상':     (3500, '베이커리'),
    '치즈케이크':   (6500, '디저트'),
    '아메리카노':   (4000, '음료'),
}

# 기존 메뉴 ID (변경 금지)
MENU_AA    = 33   # 아아    5000
MENU_PIZZA = 34   # 피자    6000


# 시나리오 테이블 (menu_id는 placeholder, 실행 시 교체)
# 아래 LATTE 등은 insert 후 채워짐
def build_scenarios(m: dict) -> list:
    """m = {메뉴명: id} 맵"""
    LATTE  = m['아이스 라떼']
    MOCHA  = m['카페모카']
    CROISS = m['크루아상']
    CAKE   = m['치즈케이크']
    AMER   = m['아메리카노']

    return [
        # ── 5월 cycle 205 (05/03~09): 프로모션 미적용, COMPLETED ──
        CycleScenario(
            cycle_id=205,
            period_start=date(2026, 5, 3), period_end=date(2026, 5, 9),
            payout_date=date(2026, 6, 2),
            settlement_status='COMPLETED',
            gifticons=[
                GifticonScenario(LATTE,  4500, 'USED',     date(2026, 5, 4), date(2026, 5, 4)),
                GifticonScenario(MOCHA,  5500, 'USED',     date(2026, 5, 5), date(2026, 5, 6)),
                GifticonScenario(AMER,   4000, 'USED',     date(2026, 5, 7), date(2026, 5, 7)),
                GifticonScenario(CROISS, 3500, 'REFUNDED', date(2026, 5, 8)),
            ]
        ),
        # ── 5월 cycle 206 (05/10~16): 프로모션 미적용, COMPLETED ──
        CycleScenario(
            cycle_id=206,
            period_start=date(2026, 5, 10), period_end=date(2026, 5, 16),
            payout_date=date(2026, 6, 9),
            settlement_status='COMPLETED',
            gifticons=[
                GifticonScenario(MENU_AA, 5000, 'USED', date(2026, 5, 11), date(2026, 5, 11)),
                GifticonScenario(CAKE,    6500, 'USED', date(2026, 5, 12), date(2026, 5, 13)),
                GifticonScenario(LATTE,   4500, 'USED', date(2026, 5, 13), date(2026, 5, 14)),
                GifticonScenario(AMER,    4000, 'USED', date(2026, 5, 15), date(2026, 5, 16)),
            ]
        ),
        # ── 5월 cycle 207 (05/17~23): 프로모션 미적용, COMPLETED ──
        CycleScenario(
            cycle_id=207,
            period_start=date(2026, 5, 17), period_end=date(2026, 5, 23),
            payout_date=date(2026, 6, 16),
            settlement_status='COMPLETED',
            gifticons=[
                GifticonScenario(MOCHA,     5500, 'USED',   date(2026, 5, 18), date(2026, 5, 19)),
                GifticonScenario(MENU_PIZZA, 6000, 'USED',  date(2026, 5, 20), date(2026, 5, 21)),
                GifticonScenario(LATTE,     4500, 'UNUSED', date(2026, 5, 22)),
            ]
        ),
        # ── 5월 cycle 208 (05/24~30): 프로모션 미적용, COMPLETED ──
        CycleScenario(
            cycle_id=208,
            period_start=date(2026, 5, 24), period_end=date(2026, 5, 30),
            payout_date=date(2026, 6, 23),
            settlement_status='COMPLETED',
            gifticons=[
                GifticonScenario(AMER,      4000, 'USED',     date(2026, 5, 25), date(2026, 5, 25)),
                GifticonScenario(CAKE,      6500, 'USED',     date(2026, 5, 26), date(2026, 5, 27)),
                GifticonScenario(MENU_AA,   5000, 'USED',     date(2026, 5, 28), date(2026, 5, 29)),
                GifticonScenario(MOCHA,     5500, 'REFUNDED', date(2026, 5, 29)),
            ]
        ),
        # ── 6월 cycle 77 (06/21~27): 프로모션 17 적용(3.5%), COMPLETED ──
        CycleScenario(
            cycle_id=77,
            period_start=date(2026, 6, 21), period_end=date(2026, 6, 27),
            payout_date=date(2026, 7, 21),
            settlement_status='COMPLETED',
            gifticons=[
                GifticonScenario(MENU_AA,   5000, 'USED',     date(2026, 6, 22), date(2026, 6, 22)),
                GifticonScenario(MENU_PIZZA, 6000, 'USED',    date(2026, 6, 23), date(2026, 6, 23)),
                GifticonScenario(LATTE,     4500, 'USED',     date(2026, 6, 24), date(2026, 6, 24)),
                GifticonScenario(MOCHA,     5500, 'REFUNDED', date(2026, 6, 25)),
            ]
        ),
        # ── 6월 cycle 78 (06/28~07/04): 프로모션 미적용, PENDING ──
        CycleScenario(
            cycle_id=78,
            period_start=date(2026, 6, 28), period_end=date(2026, 7, 4),
            payout_date=date(2026, 7, 28),
            settlement_status='PENDING',
            gifticons=[
                GifticonScenario(AMER,      4000, 'USED',   date(2026, 6, 29), date(2026, 6, 29)),
                GifticonScenario(CAKE,      6500, 'USED',   date(2026, 6, 30), date(2026, 7, 1)),
                GifticonScenario(MENU_PIZZA, 6000, 'USED',  date(2026, 7, 2),  date(2026, 7, 2)),
                GifticonScenario(LATTE,     4500, 'UNUSED', date(2026, 7, 3)),
            ]
        ),
        # ── 7월 cycle 79 (07/05~11): 현재 진행중, 정산 없음 ──
        CycleScenario(
            cycle_id=79,
            period_start=date(2026, 7, 5), period_end=date(2026, 7, 11),
            payout_date=date(2026, 8, 4),
            settlement_status=None,
            gifticons=[
                GifticonScenario(MENU_AA, 5000, 'USED',   date(2026, 7, 5), date(2026, 7, 5)),
                GifticonScenario(AMER,    4000, 'USED',   date(2026, 7, 6), date(2026, 7, 6)),
                GifticonScenario(CAKE,    6500, 'UNUSED', date(2026, 7, 6)),
            ]
        ),
    ]


# ── 핵심 함수들 ───────────────────────────────────────────

def insert_menu(conn, menu_name: str, price: int, category: str, store_id: int) -> int:
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO menu (menu_name, price, description, status, category, store_id, is_deleted) "
            "VALUES (%s, %s, %s, 'ACTIVE', %s, %s, 0)",
            (menu_name, price, f'{menu_name} 테스트 메뉴', category, store_id)
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        cursor.close()


def mock_purchase(conn, user_id: int, store_id: int, menu_id: int, amount: int,
                  order_date: date) -> tuple[int, int]:
    """
    requestPaymentUrl + updatePaymentResult 를 합친 mock 구매.
    반환: (order_id, gifticon_id)
    """
    cursor = conn.cursor()
    try:
        conn.begin()

        order_no = generate_order_no(conn, order_date)
        idempotency_key = str(uuid.uuid4())

        # orders INSERT (PENDING → 바로 COMPLETED로)
        cursor.execute(
            """INSERT INTO orders
               (store_id, user_id, payment_key, amount, status, order_no,
                payment, pgcode, idempotency_key)
               VALUES (%s, %s, %s, %s, 'COMPLETED', %s, %s, %s, %s)""",
            (store_id, user_id, f'MOCK-{order_no}', amount,
             order_no, '신용카드', 'creditcard', idempotency_key)
        )
        order_id = cursor.lastrowid

        # payments INSERT (SUCCESS)
        cursor.execute(
            "INSERT INTO payments (order_id, payment_method, paid_at, amount, status) "
            "VALUES (%s, '신용카드', NOW(), %s, 'SUCCESS')",
            (order_id, amount)
        )

        # gifticon INSERT (UNUSED, validity = order_date + 365일)
        validity = order_date + timedelta(days=365)
        cursor.execute(
            """INSERT INTO gifticon
               (user_id, type, sender, receiver, receiver_phone,
                menu_id, store_id, order_id, status, validity, receiver_id)
               VALUES (%s, 0, '김고객', '김고객', '01011110001',
                       %s, %s, %s, 'UNUSED', %s, %s)""",
            (user_id, menu_id, store_id, order_id, validity, user_id)
        )
        gifticon_id = cursor.lastrowid

        # gift_code 생성
        gift_code = generate_gift_code(store_id, user_id, gifticon_id, order_date)
        cursor.execute(
            "UPDATE gifticon SET gift_code = %s WHERE id = %s",
            (gift_code, gifticon_id)
        )

        # orders_gifticon INSERT
        cursor.execute(
            "INSERT INTO orders_gifticon (user_id, receiver_id, order_id, menu_id, gifticon_id, store_id) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (user_id, user_id, order_id, menu_id, gifticon_id, store_id)
        )

        conn.commit()
        return order_id, gifticon_id
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()


def mock_use_gifticon(conn, gifticon_id: int, amount: int, used_datetime: datetime):
    """
    useGifticon 로직 재현:
      - gifticon.status = USED, used_at = used_datetime
      - settlement_details INSERT (settlement_id=NULL)
    """
    cursor = conn.cursor()
    try:
        conn.begin()
        cursor.execute(
            "UPDATE gifticon SET status='USED', used_at=%s WHERE id=%s AND status='UNUSED'",
            (used_datetime, gifticon_id)
        )
        cursor.execute(
            "INSERT INTO settlement_details (settlement_id, gifticon_id, sales_amount) VALUES (NULL, %s, %s)",
            (gifticon_id, amount)
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()


def mock_refund(conn, order_id: int, gifticon_id: int):
    """환불 처리: order REFUNDED, gifticon REFUNDED, payment REFUNDED"""
    cursor = conn.cursor()
    try:
        conn.begin()
        cursor.execute("UPDATE orders SET status='REFUNDED' WHERE id=%s", (order_id,))
        cursor.execute("UPDATE gifticon SET status='REFUNDED' WHERE id=%s", (gifticon_id,))
        cursor.execute("UPDATE payments SET status='REFUNDED' WHERE order_id=%s", (order_id,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()


def backdate(conn, order_id: int, gifticon_id: int, order_date: date):
    """
    INSERT는 NOW()로 들어가므로 과거 날짜로 UPDATE 보정.
    orders, payments, gifticon, orders_gifticon 모두 보정.
    """
    order_dt = datetime.combine(order_date, datetime.min.time()).replace(hour=10, minute=0, second=0)
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE orders SET created_at=%s, updated_at=%s WHERE id=%s",
            (order_dt, order_dt, order_id)
        )
        cursor.execute(
            "UPDATE payments SET paid_at=%s WHERE order_id=%s",
            (order_dt, order_id)
        )
        cursor.execute(
            "UPDATE gifticon SET created_at=%s, updated_at=%s WHERE id=%s",
            (order_dt, order_dt, gifticon_id)
        )
        cursor.execute(
            "UPDATE orders_gifticon SET created_at=%s, updated_at=%s WHERE order_id=%s",
            (order_dt, order_dt, order_id)
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()


def backdate_used_at(conn, gifticon_id: int, used_date: date):
    """used_at, updated_at을 과거 날짜로 보정"""
    used_dt = datetime.combine(used_date, datetime.min.time()).replace(hour=12, minute=0, second=0)
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE gifticon SET used_at=%s, updated_at=%s WHERE id=%s",
            (used_dt, used_dt, gifticon_id)
        )
        # settlement_details의 created_at도 보정
        cursor.execute(
            "UPDATE settlement_details SET created_at=%s WHERE gifticon_id=%s",
            (used_dt, gifticon_id)
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()


def run_settlement_batch(conn, cycle_id: int, period_start: date, period_end: date,
                         payout_date: date, settlement_status: str):
    """
    create_settlement_data 로직을 그대로 재현하되,
    payout_date를 직접 받아 프로모션 조회 기준일로 사용.
    정산 완료 후 status를 settlement_status로 업데이트.
    """
    cursor = conn.cursor(pymysql.cursors.DictCursor)
    try:
        # settlement_id IS NULL 인 기프티콘 중, 해당 주기 used_at 범위의 매장별 집계
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
            print(f"  [cycle {cycle_id}] 정산할 기프티콘 없음 (used_at 범위: {period_start}~{period_end})")
            return

        for row in store_rows:
            store_id     = row['store_id']
            total_sales  = int(row['total_sales'] or 0)
            bank_name    = row['bank_name'] or ''
            account_number = row['account_number'] or ''

            # payout_date 기준 프로모션 조회 (과거 날짜 override 핵심)
            fee_info         = promotion_crud.get_fee_info_for_settlement(store_id, payout_date)
            base_fee_rate    = fee_info['base_fee_rate']
            applied_fee_rate = fee_info['applied_fee_rate']
            applied_promo_id = fee_info['applied_promo_id']

            orig_supply, orig_vat, orig_fee = calc_fee(total_sales, base_fee_rate)

            if applied_promo_id is not None:
                promo_supply, promo_vat, promo_fee = calc_fee(total_sales, applied_fee_rate)
                total_fee = promo_fee
            else:
                promo_supply = promo_vat = promo_fee = None
                total_fee = orig_fee

            net_payout = total_sales - total_fee

            conn.begin()
            cursor.execute("""
                INSERT INTO settlement (
                    store_id, cycle_id, period_start, period_end,
                    total_sales_amount, total_fee_amount, net_payout_amount,
                    base_fee_rate, applied_promo_id, applied_fee_rate,
                    original_fee_supply, original_fee_vat, original_fee_amount,
                    promo_fee_supply, promo_fee_vat, promo_fee_amount,
                    status, payout_date, bank_name, account_number
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'PENDING',%s,%s,%s)
            """, (
                store_id, cycle_id, period_start, period_end,
                total_sales, total_fee, net_payout,
                base_fee_rate, applied_promo_id, applied_fee_rate,
                orig_supply, orig_vat, orig_fee,
                promo_supply, promo_vat, promo_fee,
                payout_date, bank_name, account_number
            ))
            settlement_id = cursor.lastrowid

            # settlement_details에 settlement_id 연결
            cursor.execute("""
                UPDATE settlement_details sd
                JOIN gifticon g ON sd.gifticon_id = g.id
                SET sd.settlement_id = %s
                WHERE sd.settlement_id IS NULL
                  AND g.store_id = %s
                  AND g.used_at >= %s
                  AND g.used_at < DATE_ADD(%s, INTERVAL 1 DAY)
            """, (settlement_id, store_id, period_start, period_end))

            # COMPLETED면 status 업데이트
            if settlement_status == 'COMPLETED':
                cursor.execute(
                    "UPDATE settlement SET status='COMPLETED' WHERE settlement_id=%s",
                    (settlement_id,)
                )

            conn.commit()

            promo_str = f"promo {applied_promo_id} ({applied_fee_rate}%)" if applied_promo_id else f"기본 ({base_fee_rate}%)"
            print(f"  [cycle {cycle_id}] settlement_id={settlement_id} | "
                  f"매출={total_sales:,} 수수료={total_fee:,} 실지급={net_payout:,} | "
                  f"{promo_str} | {settlement_status}")
    finally:
        cursor.close()


# ── 메인 ──────────────────────────────────────────────────

def main():
    USER_ID  = 60
    STORE_ID = 41

    conn = get_db_connection()

    try:
        print("=" * 60)
        print("1. 메뉴 추가")
        print("=" * 60)
        menu_id_map = {}
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        cursor.execute("SELECT id, menu_name FROM menu WHERE store_id=%s AND is_deleted=0", (STORE_ID,))
        existing = {r['menu_name']: r['id'] for r in cursor.fetchall()}
        cursor.close()

        for name, (price, category) in NEW_MENUS.items():
            if name in existing:
                menu_id_map[name] = existing[name]
                print(f"  이미 존재: {name} (id={existing[name]})")
            else:
                mid = insert_menu(conn, name, price, category, STORE_ID)
                menu_id_map[name] = mid
                print(f"  추가: {name} (id={mid}, {price}원)")

        scenarios = build_scenarios(menu_id_map)

        print()
        print("=" * 60)
        print("2. 주문/기프티콘/정산 생성")
        print("=" * 60)

        for cycle in scenarios:
            print(f"\n[cycle {cycle.cycle_id}] {cycle.period_start} ~ {cycle.period_end}"
                  f" | 정산: {cycle.settlement_status or '없음'}")

            for g in cycle.gifticons:
                order_id, gifticon_id = mock_purchase(
                    conn, USER_ID, STORE_ID, g.menu_id, g.amount, g.order_date
                )

                # 과거 날짜 보정
                backdate(conn, order_id, gifticon_id, g.order_date)

                if g.status == 'USED':
                    used_dt = datetime.combine(g.used_date, datetime.min.time()).replace(hour=12)
                    mock_use_gifticon(conn, gifticon_id, g.amount, used_dt)
                    backdate_used_at(conn, gifticon_id, g.used_date)
                    print(f"  ✓ USED   | order={order_id} gifticon={gifticon_id} "
                          f"menu={g.menu_id} {g.amount}원 | 구매={g.order_date} 사용={g.used_date}")

                elif g.status == 'REFUNDED':
                    mock_refund(conn, order_id, gifticon_id)
                    print(f"  ✓ REFUND | order={order_id} gifticon={gifticon_id} "
                          f"menu={g.menu_id} {g.amount}원 | 구매={g.order_date}")

                else:  # UNUSED
                    print(f"  ✓ UNUSED | order={order_id} gifticon={gifticon_id} "
                          f"menu={g.menu_id} {g.amount}원 | 구매={g.order_date}")

            # 정산 배치 실행
            if cycle.settlement_status:
                print(f"  → 정산 배치 실행 (payout_date={cycle.payout_date})")
                run_settlement_batch(
                    conn,
                    cycle.cycle_id,
                    cycle.period_start,
                    cycle.period_end,
                    cycle.payout_date,
                    cycle.settlement_status,
                )

        print()
        print("=" * 60)
        print("3. 검증")
        print("=" * 60)
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        cursor.execute("SELECT COUNT(*) AS cnt FROM orders WHERE store_id=%s", (STORE_ID,))
        print(f"  orders:             {cursor.fetchone()['cnt']}건")

        cursor.execute("SELECT COUNT(*) AS cnt FROM gifticon WHERE store_id=%s", (STORE_ID,))
        print(f"  gifticon:           {cursor.fetchone()['cnt']}건")

        cursor.execute("""
            SELECT status, COUNT(*) AS cnt FROM gifticon WHERE store_id=%s GROUP BY status
        """, (STORE_ID,))
        for r in cursor.fetchall():
            print(f"    {r['status']}: {r['cnt']}건")

        cursor.execute("SELECT COUNT(*) AS cnt FROM settlement WHERE store_id=%s", (STORE_ID,))
        print(f"  settlement:         {cursor.fetchone()['cnt']}건")

        cursor.execute("""
            SELECT s.cycle_id, s.period_start, s.period_end, s.total_sales_amount,
                   s.total_fee_amount, s.net_payout_amount,
                   s.applied_promo_id, s.applied_fee_rate, s.status,
                   COUNT(sd.id) AS detail_cnt
            FROM settlement s
            LEFT JOIN settlement_details sd ON sd.settlement_id = s.settlement_id
            WHERE s.store_id = %s
            GROUP BY s.settlement_id
            ORDER BY s.settlement_id
        """, (STORE_ID,))
        rows = cursor.fetchall()
        print(f"\n  {'cycle':>6} {'period':^22} {'매출':>8} {'수수료':>6} {'실지급':>8} "
              f"{'promo':>6} {'rate':>5} {'status':^10} {'detail':>6}")
        print("  " + "-"*80)
        for r in rows:
            promo = str(r['applied_promo_id']) if r['applied_promo_id'] else '-'
            print(f"  {r['cycle_id']:>6} {str(r['period_start'])+'~'+str(r['period_end']):^22} "
                  f"{int(r['total_sales_amount']):>8,} {int(r['total_fee_amount']):>6,} "
                  f"{int(r['net_payout_amount']):>8,} "
                  f"{promo:>6} {float(r['applied_fee_rate']):>4.1f}% "
                  f"{r['status']:^10} {r['detail_cnt']:>6}")

        cursor.close()
        print()
        print("완료!")

    finally:
        close_db_connection(conn)


if __name__ == '__main__':
    main()
