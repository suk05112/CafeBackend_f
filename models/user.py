from pydantic import BaseModel

class User(BaseModel):
    name: str
    email: str
    phone_number: str

class Inquiry(BaseModel):
    title: str
    content: str
    
class InquiryResponse(BaseModel):
    response: str
    