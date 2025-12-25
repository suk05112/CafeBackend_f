from pydantic import BaseModel

class Menu(BaseModel):
    name: str
    menu_id: int
    store_id :int
    description: str
    price: int
    status: int


