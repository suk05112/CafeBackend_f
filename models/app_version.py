"""App version models"""
from pydantic import BaseModel
from typing import Optional, Literal
from datetime import datetime


class AppVersionCreate(BaseModel):
    platform: Literal["ios", "android"]
    version: str
    is_force_update: bool = False
    memo: Optional[str] = None


class AppVersionUpdate(BaseModel):
    is_force_update: bool


class AppVersionResponse(BaseModel):
    id: int
    platform: str
    version: str
    is_force_update: bool
    memo: Optional[str] = None
    created_at: Optional[datetime] = None
