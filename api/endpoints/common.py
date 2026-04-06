"""
Common API 엔드포인트
"""
import html
import json
import traceback
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, status, Query, Request
from fastapi.responses import HTMLResponse
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
    aws_access_key_id='***REMOVED_AWS_KEY***',
    aws_secret_access_key='***REMOVED_AWS_SECRET***',
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
        "address": '서울특별시 강서구 공항대로 543',
        "telephone": '010-2544-6458'
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
                'Key': 'gifnut-logo.png'
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


def _ppay_return_query_from_mapping(data: dict) -> dict:
    """앱 `PayletterPpayCheckoutPage`와 동일 키(code, tid, order_no)."""
    out = {}
    for key in ("code", "tid", "order_no", "message"):
        val = data.get(key)
        if val is not None and str(val) != "":
            out[key] = str(val)
    return out


def _ppay_html_redirect_deeplink(path: str, query: dict) -> HTMLResponse:
    q = urlencode(query) if query else ""
    dest = f"gifnut://payletter{path}"
    if q:
        dest = f"{dest}?{q}"
    esc = html.escape(dest)
    js_dest = json.dumps(dest)
    body = f"""<!DOCTYPE html><html><head><meta charset="utf-8"/>
<meta http-equiv="refresh" content="0;url={esc}"/>
<script>location.replace({js_dest});</script>
<title>Redirect</title>
</head><body></body></html>"""
    return HTMLResponse(content=body)


@router.api_route("/payletter/ppay/app-return", methods=["GET", "POST"])
async def payletter_ppay_app_return(request: Request):
    """PPAY return_url — GET 쿼리 또는 POST 폼 → 앱 딥링크로 이동."""
    if request.method == "POST":
        try:
            form = await request.form()
            data = {k: form.get(k) for k in form.keys()}
        except Exception:
            data = {}
    else:
        data = dict(request.query_params)
    params = _ppay_return_query_from_mapping(data)
    return _ppay_html_redirect_deeplink("/return", params)


@router.api_route("/payletter/ppay/app-cancel", methods=["GET", "POST"])
async def payletter_ppay_app_cancel(_request: Request):
    """PPAY cancel_url — WebView가 이 URL을 열면 결제 취소로 처리."""
    return _ppay_html_redirect_deeplink("/cancel", {})


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


