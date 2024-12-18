from pydantic import BaseModel

class Owner(BaseModel):
    name: str
    email: str
    phone_number: str
    uid: str
    
class OwnerInquiry(BaseModel):
    title: str
    content: str

class OwnerInquiryResponse(BaseModel):
    response: str
    