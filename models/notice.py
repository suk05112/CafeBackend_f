"""Notice models"""
from pydantic import BaseModel
from typing import Optional, List
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

class NoticeListItem(BaseModel):
    id: int
    title: str
    created_at: Optional[str] = None

class NoticeDetail(BaseModel):
    id: int
    title: str
    content: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

