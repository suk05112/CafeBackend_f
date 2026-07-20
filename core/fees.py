"""PG(결제대행사) 수수료율 공용 정의.

gifticon 발행잔액 계산(crud/stats.py)과 플랫폼 순수수료 배치 집계
(scripts/aggregate_daily_platform_stats.py) 양쪽에서 공유.
pgcode는 orders.pgcode 컬럼 값과 매핑됨.
"""

# GNB-169 / GNB-199: pgcode별 PG 수수료율 (%)
PG_FEE_RATE_MAP = {
    "creditcard":    2.7,
    "naverpay":      2.8,
    "kakaopay":      2.8,
    "applepay":      2.9,
    "samsungpay":    2.9,
    "banktransfer":  2.0,
    "voucher":       0.0,
    # 나머지는 신용카드 기본값 적용
}
PG_FEE_RATE_DEFAULT = 2.7
