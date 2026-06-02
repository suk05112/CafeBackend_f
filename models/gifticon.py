from pydantic import BaseModel
from typing import Optional

VALID_PGCODES = {
    "creditcard", "banktransfer", "virtualaccount", "mobile", "voucher",
    "book", "culture", "smartculture", "teencash", "tmoney", "cvs",
    "eggmoney", "phonebill", "cashbee", "kakaopay", "payco", "checkpay",
    "toss", "ssgpay", "naverpay", "samsungpay", "applepay",
}

class Gifticon(BaseModel):
    type: int
    sender: str
    receiver: str
    receiver_phone_number: str
    menu_id: int
    store_id: int
    total_price: int
    pgcode: str = "creditcard"
    payment_key: Optional[str] = None  # 결제 전에는 None
    payment: Optional[str] = None  # 결제 정보 (String)
    idempotency_key: Optional[str] = None  # 앱에서 생성한 UUID, 이중 결제 방지용

class PaymentResult(BaseModel):
    # Payletter 결제 결과 콜백 필드
    order_id: int           # 주문 ID (user_id로 전달)
    tid: str                # 페이레터 거래 ID
    cid: str                # 클라이언트 ID
    amount: int             # 결제 금액
    user_id: str            # 페이레터 user_id (order_id를 문자열로 전달)
    transaction_date: str   # 거래 일시
    payhash: str            # SHA256(user_id + amount + tid + API_Key)
