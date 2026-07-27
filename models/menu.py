from pydantic import BaseModel
from typing import Optional

class Menu(BaseModel):
    name: str
    menu_id: int
    store_id: int
    description: Optional[str] = None
    price: int
    status: str  # "ACTIVE" | "INACTIVE"
    delete_image: bool = False
    change_image: bool = False


