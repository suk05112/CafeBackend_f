from pydantic import BaseModel
from typing import Optional

class Gifticon(BaseModel):
    type: int
    sender: str
    receiver: str
    receiver_phone_number: str
    menu_id: int
    store_id: int
    total_price: int
    payment_key: Optional[str] = None  # 결제 전에는 None
    payment: Optional[str] = None  # 결제 정보 (String)

class PaymentResult(BaseModel):
    order_id: int
    payment_key: str
    is_success: bool  # True: 성공, False: 실패
