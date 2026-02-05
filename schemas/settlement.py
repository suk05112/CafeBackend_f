from pydantic import BaseModel, Field, field_validator


class Account(BaseModel):
    name: str
    code: str
    bank: str
    account: str


class AccountUpdateRequest(BaseModel):
    """계좌 정보 변경 요청 (검증 포함)"""
    name: str = Field(..., min_length=1, max_length=50, description="예금주명")
    code: str = Field(..., min_length=1, max_length=20, description="은행코드")
    bank: str = Field(..., min_length=1, max_length=100, description="은행명")
    account: str = Field(..., min_length=10, max_length=14, description="계좌번호")

    @field_validator("name", "bank", mode="before")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("account", mode="before")
    @classmethod
    def account_digits_only(cls, v: str) -> str:
        if not isinstance(v, str):
            raise ValueError("계좌번호는 문자열이어야 합니다")
        s = v.strip().replace("-", "").replace(" ", "")
        if not s.isdigit():
            raise ValueError("계좌번호는 숫자만 입력해 주세요")
        if len(s) < 10 or len(s) > 14:
            raise ValueError("계좌번호는 10~14자리여야 합니다")
        return s

    @field_validator("code", mode="before")
    @classmethod
    def code_strip(cls, v: str) -> str:
        if isinstance(v, str):
            return v.strip()
        return v
