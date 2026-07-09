from pydantic import BaseModel
from typing import List, Optional


class OwnerTermsAgreeItem(BaseModel):
    term_id: int
    term_version_id: int
    agreed: bool


class Owner(BaseModel):
    login_id: str
    email: str
    uid: str
    client_tx_id: str  # mobileOK 본인확인 거래 ID (name/phone/birthdate/gender는 mok_client_tx에서 조회)
    agreements: Optional[List[OwnerTermsAgreeItem]] = None

class OwnerFind(BaseModel):
    name: str
    phone_number: str

class OwnerFindPw(BaseModel):
    login_id: str
    phone_number: str
    
class OwnerInquiry(BaseModel):
    title: str
    content: str

class OwnerInquiryResponse(BaseModel):
    response: str


class OwnerTermsAgreeRequest(BaseModel):
    owner_id: int
    agreements: List[OwnerTermsAgreeItem]
