from pydantic import BaseModel
from typing import Optional, Dict, Any

class User(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone_number: Optional[str] = None
    uid: Optional[str] = None
    firebase: Optional[Dict[str, Any]] = None

class Inquiry(BaseModel):
    title: str
    content: str
    
class InquiryResponse(BaseModel):
    response: str
    