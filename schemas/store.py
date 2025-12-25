from pydantic import BaseModel
from typing import Union

class StoreCreate(BaseModel):
    owner_id: int
    store_name: str
    store_telephone: str
    store_description: str
    store_address: str
    store_lat: float
    store_lng: float
    store_photo_cnt: int


class InspectionStatusUpdate(BaseModel):
    inspection_status: Union[int, str]
    inspection_msg: str