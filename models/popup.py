"""Popup models"""
from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class PopupCreate(BaseModel):
    target_type: str  # 'user' or 'owner'
    title: str
    image_url: str
    link_url: Optional[str] = None
    is_active: bool = True
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None


class PopupUpdate(BaseModel):
    title: Optional[str] = None
    image_url: Optional[str] = None
    link_url: Optional[str] = None
    display_order: Optional[int] = None
    is_active: Optional[bool] = None
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None


class PopupResponse(BaseModel):
    id: int
    target_type: str
    title: str
    image_url: str
    link_url: Optional[str] = None
    display_order: int
    is_active: bool
    start_at: Optional[str] = None
    end_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
