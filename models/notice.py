"""Notice models"""
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class NoticeCreate(BaseModel):
    title: str
    content: str

class NoticeUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None

class NoticeResponse(BaseModel):
    id: int
    title: str
    content: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

