from pydantic import BaseModel

class Account(BaseModel):
    name: str
    code: str
    bank: str
    account: str
    