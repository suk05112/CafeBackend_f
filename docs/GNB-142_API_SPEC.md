# GNB-142: 정산 API 응답 스키마 변경 (앱 명세)

**변경 배경:** 프로모션 적용 방식을 개별 기프티콘 단위 → 정산 주기 총액 단위로 변경.
프로모션은 정산 지급 예정일(`payout_date`) 기준 활성 프로모션을 조회하여 적용.

**영향 API (앱 팀 확인 필요):**
- `GET /owner/settlement/preview/{store_id}` — 진행 중 정산 미리보기
- `GET /owner/settlement/{store_id}` — 정산 목록 (진행 중 preview + 과거 정산)
- `GET /owner/settlement/detail/{settlement_id}` — 정산 상세

---

## 1. GET /owner/settlement/preview/{store_id}

**설명:** 진행 중인 정산 주기(오늘이 `period_start_date ~ period_end_date` 사이인 cycle)의 예상 정산 미리보기.
- 진행 중 주기가 없거나 매출이 없으면 `404`.
- 프로모션은 해당 주기의 `payout_date` 기준으로 조회 (지급 예정일에 유효한 프로모션 적용).

**응답 예시 (프로모션 적용됨):**
```json
{
  "settlement": {
    "settlement_id": null,
    "store_id": 42,
    "cycle_id": 15,
    "period_start": "2026-07-05",
    "period_end": "2026-07-11",
    "total_sales_amount": 500000,
    "base_fee_rate": 3.50,
    "applied_fee_rate": 1.50,
    "applied_promo_id": 7,
    "applied_promo_title": "여름 프로모션 1.5%",
    "original_fee_supply": 17500,
    "original_fee_vat": 1750,
    "original_fee_amount": 19250,
    "promo_fee_supply": 7500,
    "promo_fee_vat": 750,
    "promo_fee_amount": 8250,
    "total_fee_amount": 8250,
    "net_payout_amount": 491750,
    "status": "PENDING",
    "payout_date": null,
    "expected_payout_date": "2026-08-01",
    "failure_reason": null
  },
  "details": [
    {
      "id": 12345,
      "gifticon_id": 98765,
      "menu_name": "아메리카노",
      "used_at": "2026-07-06 09:30",
      "amount": 4500
    }
  ]
}
```

**응답 예시 (프로모션 미적용):**
```json
{
  "settlement": {
    "settlement_id": null,
    "store_id": 42,
    "cycle_id": 15,
    "period_start": "2026-07-05",
    "period_end": "2026-07-11",
    "total_sales_amount": 500000,
    "base_fee_rate": 3.50,
    "applied_fee_rate": 3.50,
    "applied_promo_id": null,
    "applied_promo_title": null,
    "original_fee_supply": 17500,
    "original_fee_vat": 1750,
    "original_fee_amount": 19250,
    "promo_fee_supply": null,
    "promo_fee_vat": null,
    "promo_fee_amount": null,
    "total_fee_amount": 19250,
    "net_payout_amount": 480750,
    "status": "PENDING",
    "payout_date": null,
    "expected_payout_date": "2026-08-01",
    "failure_reason": null
  },
  "details": [ ... ]
}
```

---

## 2. GET /owner/settlement/{store_id}?past_months=3

**설명:** 진행 중 preview + 과거 N달 정산 목록. `past_months` 기본 3, 1~24.
- `settlement_id`가 `null`이면 진행 중 preview (아직 정산 데이터 미생성 상태)
- 정렬: `period_start` 내림차순 (진행 중 preview가 맨 앞)

**응답 예시:**
```json
{
  "settlements": [
    {
      "settlement_id": null,
      "cycle_id": 15,
      "period_start": "2026-07-05",
      "period_end": "2026-07-11",
      "total_sales_amount": 500000,
      "base_fee_rate": 3.50,
      "applied_fee_rate": 1.50,
      "applied_promo_id": 7,
      "applied_promo_title": "여름 프로모션 1.5%",
      "original_fee_supply": 17500,
      "original_fee_vat": 1750,
      "original_fee_amount": 19250,
      "promo_fee_supply": 7500,
      "promo_fee_vat": 750,
      "promo_fee_amount": 8250,
      "total_fee_amount": 8250,
      "net_payout_amount": 491750,
      "expected_amount": 491750.0,
      "fee_amount": 8250.0,
      "expected_payout_date": "2026-08-01",
      "status": "PENDING",
      "payout_date": null,
      "failure_reason": null
    },
    {
      "settlement_id": 1234,
      "cycle_id": 14,
      "period_start": "2026-06-28",
      "period_end": "2026-07-04",
      "total_sales_amount": 380000,
      "base_fee_rate": 3.50,
      "applied_fee_rate": 3.50,
      "applied_promo_id": null,
      "applied_promo_title": null,
      "original_fee_supply": 13300,
      "original_fee_vat": 1330,
      "original_fee_amount": 14630,
      "promo_fee_supply": null,
      "promo_fee_vat": null,
      "promo_fee_amount": null,
      "total_fee_amount": 14630,
      "net_payout_amount": 365370,
      "expected_amount": 365370.0,
      "fee_amount": 14630.0,
      "expected_payout_date": "2026-07-25",
      "status": "COMPLETED",
      "payout_date": "2026-07-25",
      "failure_reason": null
    }
  ]
}
```

---

## 3. GET /owner/settlement/detail/{settlement_id}

**설명:** 특정 정산의 헤더 + 건별 내역. 응답 형태는 preview와 동일한 구조. `settlement_id`가 실제 값.

**응답 예시:**
```json
{
  "settlement": {
    "settlement_id": 1234,
    "store_id": 42,
    "cycle_id": 14,
    "period_start": "2026-06-28",
    "period_end": "2026-07-04",
    "total_sales_amount": 380000,
    "base_fee_rate": 3.50,
    "applied_fee_rate": 3.50,
    "applied_promo_id": null,
    "applied_promo_title": null,
    "original_fee_supply": 13300,
    "original_fee_vat": 1330,
    "original_fee_amount": 14630,
    "promo_fee_supply": null,
    "promo_fee_vat": null,
    "promo_fee_amount": null,
    "total_fee_amount": 14630,
    "net_payout_amount": 365370,
    "status": "COMPLETED",
    "payout_date": "2026-07-25",
    "failure_reason": null
  },
  "details": [
    {
      "id": 12000,
      "gifticon_id": 95000,
      "menu_name": "카페라떼",
      "used_at": "2026-06-28 10:15",
      "amount": 5000
    }
  ]
}
```

---

## 4. 컬럼 사전 (settlement 응답)

| 필드 | 타입 | 설명 |
|---|---|---|
| `settlement_id` | int \| null | 정산 ID (preview는 null) |
| `cycle_id` | int | 정산 주기 ID |
| `period_start` / `period_end` | string(YYYY-MM-DD) | 정산 대상 매출 기간 |
| `total_sales_amount` | int | 매출 총액(원) |
| `base_fee_rate` | number | 플랫폼 기본 수수료율(%) |
| `applied_promo_id` | int \| null | 적용된 프로모션 ID (없으면 null) |
| `applied_promo_title` | string \| null | 적용된 프로모션 이름 |
| `applied_fee_rate` | number | 최종 적용 수수료율(%) — 프로모션 없으면 base와 동일 |
| `original_fee_supply` / `_vat` / `_amount` | int | 프로모션 미적용 수수료 (공급가/VAT/총액) |
| `promo_fee_supply` / `_vat` / `_amount` | int \| null | 프로모션 적용 수수료. 프로모션 없으면 모두 null |
| `total_fee_amount` | int | 실제 부과 수수료. 프로모션 있으면 `promo_fee_amount`, 없으면 `original_fee_amount` |
| `net_payout_amount` | int | `total_sales_amount - total_fee_amount` |
| `status` | string | `PENDING` / `COMPLETED` / `FAILED` / `HOLD` / `READY` |
| `payout_date` | string(YYYY-MM-DD) \| null | 실제 지급 완료일 |
| `expected_payout_date` | string(YYYY-MM-DD) \| null | 지급 예정일 (list/preview에만) |
| `failure_reason` | string \| null | FAILED 상태의 사유 |

### details 배열 항목
| 필드 | 타입 | 설명 |
|---|---|---|
| `id` | int | settlement_details.id |
| `gifticon_id` | int | 기프티콘 ID |
| `menu_name` | string \| null | 메뉴 이름 |
| `used_at` | string("YYYY-MM-DD HH:MM") \| null | 기프티콘 사용 시각 |
| `amount` | int | 개별 매출액 |

**중요:** 개별 항목의 수수료/정산금액은 더 이상 응답에 포함되지 않음. 수수료는 정산 헤더(`total_fee_amount` 등)만 제공.

---

## 5. 주요 변경 요약 (Before → After)

| 항목 | 변경 전 | 변경 후 |
|---|---|---|
| 프로모션 적용 시점 | 주문 생성 시 (기프티콘별) | 정산 생성 시 (매장 총액) |
| 프로모션 조회 기준일 | `order_date` | `payout_date` (지급 예정일) |
| 기프티콘 응답에 수수료 정보 | 있음 (`base_fee_rate` 등) | **없음** (삭제) |
| settlement_details 응답 필드 | `sales_amount`, `fee_amount`, `settlement_amount` | `sales_amount`만 |
| settlement 응답 필드 | `total_sales_amount`, `total_fee_amount`, `net_payout_amount` | **+ 프로모션 관련 9개 컬럼 추가** |

## 6. 앱 반영 시 확인 사항
1. 기프티콘 상세 조회 응답에서 수수료 필드를 파싱하고 있다면 제거
2. 정산 상세 UI에서 개별 항목의 수수료 표시하고 있다면 헤더 수수료로 이동
3. 프로모션 적용 여부 배지/텍스트 표기 시 `applied_promo_id` 유무 + `applied_promo_title` 활용
4. `original_fee_amount` vs `promo_fee_amount` 대비를 UI에 노출할지 결정 (할인 금액 표시 가능)
