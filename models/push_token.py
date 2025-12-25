from pydantic import BaseModel
from typing import Optional
from enum import Enum

class DeviceType(str, Enum):
    ios = "ios"
    android = "android"

class PushTokenCreate(BaseModel):
    """처음 가입 시 모든 정보를 받는 모델"""
    fcm_token: str
    device_type: DeviceType
    allow_service_push: bool = True
    allow_marketing_push: bool = False

class PushTokenUpdate(BaseModel):
    """동의 여부 변경 시 사용하는 모델"""
    allow_service_push: Optional[bool] = None
    allow_marketing_push: Optional[bool] = None

