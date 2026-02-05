from pydantic import BaseModel
from typing import Optional, Dict, Any, List

class User(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone_number: Optional[str] = None
    uid: Optional[str] = None
    firebase: Optional[Dict[str, Any]] = None
    provider: Optional[str] = None
    # 최초 회원가입 시 약관 동의 정보 (선택)
    agreements: Optional[List["TermsAgreeItem"]] = None

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


class TermsAgreeItem(BaseModel):
    """약관 동의 항목"""
    term_id: int
    term_version_id: int
    agreed: bool


class TermsAgreeRequest(BaseModel):
    """약관 동의 저장 요청"""
    user_id: int
    agreements: List[TermsAgreeItem]


# forward ref 해결 (User.agreements)
User.model_rebuild()
