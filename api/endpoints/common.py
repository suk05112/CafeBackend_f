"""
Common API 엔드포인트
"""
import traceback
from fastapi import APIRouter, HTTPException, status, Query
from pydantic import BaseModel
from typing import Literal
import pymysql
from botocore.exceptions import ClientError

from loguru import logger
from app.fcm_service import (
    send_fcm_notification_to_all_users,
    send_fcm_notification_to_all_owners,
    send_fcm_notification_to_all
)
from app.database import get_db_connection
from app.s3_config import S3_CLIENT, BUCKET_NAME

router = APIRouter()

# S3 설정
s3 = S3_CLIENT
bucket_name = BUCKET_NAME


class NotificationRequest(BaseModel):
    title: str
    body: str
    target: Literal["all_users", "all_owners", "all"] = "all"
    use_marketing: bool = False


@router.get("/health")
def health_check():
    """Health check 엔드포인트"""
    return {"status": "healthy", "message": "Service is running"}


@router.get("/business-info")
def get_business_info():
    """사업자 정보 조회 API"""
    return {
        "business_number": '479-03-03427',
        "online_sales_number": '2025-서울강서-3226',
        "address": '서울특별시 강서구 공항대로 543',
        "telephone": '02-1111-1111'
    }


@router.post("/notification/broadcast")
def broadcast_notification(notification: NotificationRequest):
    """공지사항이나 이벤트 알림 브로드캐스트"""
    try:
        if notification.target == "all_users":
            result = send_fcm_notification_to_all_users(
                title=notification.title,
                body=notification.body,
                use_marketing=notification.use_marketing
            )
            return {
                "message": "Notification sent to all users",
                "result": result
            }
        elif notification.target == "all_owners":
            result = send_fcm_notification_to_all_owners(
                title=notification.title,
                body=notification.body,
                use_marketing=notification.use_marketing
            )
            return {
                "message": "Notification sent to all owners",
                "result": result
            }
        elif notification.target == "all":
            result = send_fcm_notification_to_all(
                title=notification.title,
                body=notification.body,
                use_marketing=notification.use_marketing
            )
            return {
                "message": "Notification sent to all users and owners",
                "result": result
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid target. Must be 'all_users', 'all_owners', or 'all'"
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in broadcast_notification: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error during broadcastNotification: {str(e)}"
        )


