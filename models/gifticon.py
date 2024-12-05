from pydantic import BaseModel

class Gifticon(BaseModel):
    type: int
    sender: str
    receiver: str
    receiver_phone_number: str
    menu_id: int
    store_id: int
    payment: str
    total_price: int
