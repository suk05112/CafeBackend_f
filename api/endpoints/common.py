"""
Common API 엔드포인트
"""
import traceback
from fastapi import APIRouter, HTTPException, status, Query
from pydantic import BaseModel
from typing import Literal
import pymysql
from botocore.exceptions import ClientError
import logging

from loguru import logger
from app.fcm_service import (
    send_fcm_notification_to_all_users,
    send_fcm_notification_to_all_owners,
    send_fcm_notification_to_all
)
from app.database import get_db_connection, close_db_connection
from core.s3_config import S3_CLIENT, BUCKET_NAME
from core.exceptions import InternalError
import boto3
from botocore.client import Config

router = APIRouter()

# CloudWatch 로거 설정 (health check 실패 시 로깅용)
cloudwatch_logger = logging.getLogger("cafe_backend")

# S3 설정
s3 = S3_CLIENT
bucket_name = BUCKET_NAME

# gifnut-common-resources 버킷용 S3 클라이언트 (ap-northeast-2 리전)
# 버킷이 ap-northeast-2에 있으므로 별도의 클라이언트 생성
common_resources_s3 = boto3.client(
    's3',
    aws_access_key_id='***REMOVED***',
    aws_secret_access_key='***REMOVED***',
    region_name='ap-northeast-2',  # common-gifnut-resources 버킷의 실제 리전
    config=Config(signature_version='s3v4')
)
common_resources_bucket = "gifnut-common-resources"


class NotificationRequest(BaseModel):
    title: str
    body: str
    target: Literal["all_users", "all_owners", "all"] = "all"
    use_marketing: bool = False


@router.get("/health")
def health_check():
    """
    Health check 엔드포인트
    실패 시에만 AWS CloudWatch에 로깅합니다.
    """
    connection = None
    try:
        # DB 연결 확인
        connection = get_db_connection()
        connection.ping(reconnect=False)
        
        return {"status": "healthy", "message": "Service is running"}
    except Exception as e:
        # Health check 실패 시에만 CloudWatch에 로깅
        error_message = f"Health check failed: {str(e)}"
        cloudwatch_logger.error(error_message)
        logger.error(f"Health check failed: {traceback.format_exc()}")
        
        # 실패해도 HTTP 200 반환 (healthcheck는 exit code로 판단)
        # 하지만 상태는 unhealthy로 표시
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=error_message
        )
    finally:
        if connection:
            close_db_connection(connection)


@router.get("/business-info")
def get_business_info():
    """사업자 정보 조회 API"""
    return {
        "business_number": '479-03-03427',
        "online_sales_number": '2025-서울강서-3226',
        "address": '서울특별시 강남구 강남대로 112길 47, 2층 661A호',
        "telephone": '02-2659-3004'
    }


@router.get("/gifnut-image")
def get_gifnut_image_url(
    expires_in: int = Query(3600, ge=1, le=604800, description="URL 유효기간 (초, 기본값: 3600초=1시간, 최대: 604800초=7일)")
):
    """
    gifnut.png 이미지의 presigned URL 조회 API
    common-gifnut-resources S3 버킷에서 gifnut.png 파일의 presigned URL을 생성합니다.
    """
    try:
        # Presigned URL 생성 (ap-northeast-2 리전의 S3 클라이언트 사용)
        presigned_url = common_resources_s3.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': common_resources_bucket,
                'Key': 'AppIcon.png.png'
            },
            ExpiresIn=expires_in
        )
        
        return {
            "url": presigned_url,
            "bucket": common_resources_bucket,
            "key": "gifnut-logo.png",
            "expires_in": expires_in,
            "expires_in_hours": expires_in / 3600
        }
        
    except ClientError as e:
        error_message = f"Failed to generate presigned URL: {str(e)}"
        logger.error(error_message)
        cloudwatch_logger.error(error_message)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=error_message
        )
    except Exception as e:
        error_message = f"Unexpected error: {str(e)}"
        logger.error(f"Error in get_gifnut_image_url: {traceback.format_exc()}")
        cloudwatch_logger.error(error_message)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=error_message
        )


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
        raise InternalError(e, "broadcast_notification")


