from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from typing import Literal
import traceback
import pymysql
from loguru import logger
from app.database import get_db_connection
from app.fcm_service import (
    send_fcm_notification_to_all_users,
    send_fcm_notification_to_all_owners,
    send_fcm_notification_to_all
)

router = APIRouter()

@router.get("/health")
def health_check():
    """
    Health check 엔드포인트
    배포 스크립트에서 컨테이너 상태 확인용으로 사용
    """
    return {"status": "healthy", "message": "Service is running"}

class NotificationRequest(BaseModel):
    title: str
    body: str
    target: Literal["all_users", "all_owners", "all"] = "all"
    use_marketing: bool = False  # True: 마케팅 푸시 동의한 사용자만, False: 서비스 푸시 동의한 사용자만

@router.get("/business-info")
def getBusinessInfo():
    """
    사업자 정보 조회 API (공통)
    사업자 번호, 통신판매번호, 주소, 전화번호 반환
    user와 owner 모두 사용 가능
    매개변수 없이 호출: GET /business-info
    """
    return {
        "business_number": '479-03-03427',
        "online_sales_number": '2025-서울강서-3226',
        "address": '서울특별시 강서구 공항대로 543',
        "telephone": '02-1111-1111'
    }

@router.post("/notification/broadcast")
def broadcastNotification(notification: NotificationRequest):
    """
    공지사항이나 이벤트 알림을 권한이 있는 사용자에게 모두 보내는 API
    
    target: "all_users" (모든 유저), "all_owners" (모든 사장님), "all" (모두)
    use_marketing: True면 마케팅 푸시 동의한 사용자만, False면 서비스 푸시 동의한 사용자만
    """
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
        print(f"Error during broadcastNotification: {e}")
        traceback.print_exc()
        logger.error(f"Error during broadcastNotification: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error during broadcastNotification: {str(e)}"
        )

