from pydantic import BaseModel
from typing import Union, Optional

class StoreCreate(BaseModel):
    owner_id: int
    store_name: str
    store_telephone: str
    store_description: str
    store_address: str
    store_lat: float
    store_lng: float
    image_count: Optional[int] = None
    district_code: Optional[str] = None  # 군/구 코드 (예: "23" = 강남구)
    logo_changed: bool = False
    business_changed: bool = False
    business_number: Optional[str] = None


class InspectionStatusUpdate(BaseModel):
    inspection_status: Union[int, str]
    inspection_msg: Optional[str] = ""