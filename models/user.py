from pydantic import BaseModel
from typing import Optional, Dict, Any

class User(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone_number: Optional[str] = None
    uid: Optional[str] = None
    firebase: Optional[Dict[str, Any]] = None
    provider: Optional[str] = None

class Inquiry(BaseModel):
    title: str
    content: str
    
class InquiryResponse(BaseModel):
    response: str

class FindAccountRequest(BaseModel):
    """아이디 찾기/비밀번호 찾기 공통 요청 모델"""
    name: str
    phone_number: str
    type: str  # "find_id" 또는 "find_password"
    